"""Runner de migraciones basado en PRAGMA user_version.

Uso:
    python scripts/migrate.py            # aplica pendientes
    python scripts/migrate.py --status   # solo informa

Regla: los archivos de migrations/ NUNCA se editan una vez aplicados.
Un cambio de esquema es siempre un archivo nuevo.
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import Config  # noqa: E402

NAME_RE = re.compile(r"^(\d{3})_.+\.sql$")


def discover(migrations_dir):
    found = []
    for path in sorted(Path(migrations_dir).glob("*.sql")):
        m = NAME_RE.match(path.name)
        if not m:
            print(f"  ! ignorado (nombre invalido): {path.name}")
            continue
        found.append((int(m.group(1)), path))
    return found


def current_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def apply_all(db_path, migrations_dir, dry_run=False):
    if not Path(db_path).exists():
        raise SystemExit(f"No existe la base: {db_path}. Corre scripts/init_db.py")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")   # off durante DDL
    try:
        version = current_version(conn)
        print(f"Base: {db_path}")
        print(f"Version actual: {version}")

        pending = [(n, p) for n, p in discover(migrations_dir) if n > version]
        if not pending:
            print("Sin migraciones pendientes.")
            return

        for number, path in pending:
            print(f"  -> {path.name}" + ("  [dry-run]" if dry_run else ""))
            if dry_run:
                continue
            sql = path.read_text(encoding="utf-8")
            try:
                conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
            except sqlite3.Error as e:
                conn.rollback()
                raise SystemExit(f"FALLO en {path.name}: {e}")

            got = current_version(conn)
            if got != number:
                raise SystemExit(
                    f"FALLO: {path.name} dejo user_version={got}, se esperaba {number}. "
                    "Cada migracion debe terminar con PRAGMA user_version = N;"
                )
        print(f"Listo. Version final: {current_version(conn)}")
    finally:
        conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=Config.DB_PATH)
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    apply_all(args.db, Config.MIGRATIONS_DIR, dry_run=args.status)