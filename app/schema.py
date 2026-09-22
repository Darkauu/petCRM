"""Version del esquema, y como se pone la base al dia.

Dos cosas viven aqui:

  - Que version necesita este codigo. No hay constante que mantener: es
    el numero de la migracion mas alta en migrations/. Quien agregue
    004_loquesea.sql hace que el codigo espere la 4 sin tocar nada mas.

  - Como migrar sola la base al arrancar. Que el duenio tenga que
    acordarse de correr un comando despues de cada actualizacion es una
    trampa: si se le olvida, el sistema revienta a mitad de atender. Y
    un comando escrito a mano puede apuntar a otro archivo. La
    aplicacion migra la base que ELLA abre, que es la unica que importa,
    y siempre despues de respaldarla.
"""
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:                     # Windows: no hay flock
    fcntl = None

_NAME_RE = re.compile(r"^(\d{3})_.+\.sql$")


class MigrationError(RuntimeError):
    pass


# ---- Version -----------------------------------------------------------

def expected_version(migrations_dir):
    numbers = []
    for path in Path(migrations_dir).glob("*.sql"):
        match = _NAME_RE.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers) if numbers else 0


def current_version(db):
    return db.execute("PRAGMA user_version").fetchone()[0]


def is_empty(db):
    """Una base recien creada (o inexistente) no tiene ni la tabla client."""
    row = db.execute(
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'table' AND name = 'client'"
    ).fetchone()
    return row[0] == 0


# ---- Migracion automatica ----------------------------------------------

@contextmanager
def _exclusive(path):
    """Un solo proceso migra. Con varios workers de gunicorn, el resto
    espera aqui y despues encuentra la base ya al dia."""
    if fcntl is None:
        yield
        return
    lock_path = Path(str(path) + ".migrate.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _pending(conn, migrations_dir):
    current = current_version(conn)
    found = []
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        match = _NAME_RE.match(path.name)
        if match and int(match.group(1)) > current:
            found.append((int(match.group(1)), path))
    return current, found


def _backup(db_path, version):
    """Copia por la API de sqlite y no por el sistema de archivos: con WAL
    activo, copiar el .db suelto deja fuera lo que todavia vive en el -wal."""
    folder = Path(db_path).parent / "respaldos"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{Path(db_path).stem}-v{version}-{stamp}.db"

    source = sqlite3.connect(str(db_path))
    copy = sqlite3.connect(str(target))
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    return target


def _restore(backup, path):
    for suffix in ("-wal", "-shm"):
        stale = Path(str(path) + suffix)
        if stale.exists():
            stale.unlink()
    shutil.copyfile(backup, path)


def ensure_migrated(db_path, migrations_dir):
    """Deja la base al dia. Devuelve que se hizo, para poder registrarlo.

    Si algo falla a mitad, se restaura el respaldo: es preferible quedar
    en la version vieja, con el aviso en pantalla, que con una base a
    medio migrar.
    """
    path = Path(db_path)
    if not path.exists():
        return {"action": "missing"}

    with _exclusive(path):
        conn = sqlite3.connect(str(path))
        closed = False
        try:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("PRAGMA busy_timeout = 10000")

            before, pending = _pending(conn, migrations_dir)
            if not pending:
                return {"action": "ok", "version": before}

            backup = _backup(path, before)
            applied = []
            current_file = None
            try:
                for number, sql_file in pending:
                    current_file = sql_file
                    sql = sql_file.read_text(encoding="utf-8")
                    conn.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
                    got = current_version(conn)
                    if got != number:
                        raise MigrationError(
                            f"dejo user_version={got}, se esperaba {number}"
                        )
                    applied.append(sql_file.name)
            except Exception as exc:
                conn.close()
                closed = True
                _restore(backup, path)
                raise MigrationError(
                    f"Fallo al aplicar {current_file.name}: {exc}. "
                    f"La base quedo como estaba (respaldo: {backup.name})."
                ) from exc

            return {
                "action": "migrated",
                "from": before,
                "version": current_version(conn),
                "applied": applied,
                "backup": str(backup),
            }
        finally:
            if not closed:
                conn.close()
