"""Respaldos que no dependen de que alguien se acuerde.

Uno al dia, guardado junto a la base. La copia se hace con la API
backup() de sqlite y no copiando el archivo: con WAL activo, copiar el
.db suelto deja fuera lo que todavia vive en el -wal.

El nombre lleva la fecha y nada mas, asi que "ya hay uno de hoy" es
mirar si el archivo existe. No hace falta guardar en ningun lado cuando
fue el ultimo.

Los respaldos previos a una migracion se llaman distinto (-vN-) y esta
limpieza no los toca: son pocos y son los que mas duelen perder.
"""
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from app.schema import _exclusive          # mismo candado que la migracion

DAILY_KEEP = 14
CHECK_EVERY_SECONDS = 3600

_last_check = 0.0


def folder_for(db_path):
    return Path(db_path).parent / "respaldos"


def daily_name(db_path, day=None):
    stamp = (day or datetime.now()).strftime("%Y%m%d")
    return f"{Path(db_path).stem}-diario-{stamp}.db"


def make(db_path, target):
    source = sqlite3.connect(str(db_path))
    copy = sqlite3.connect(str(target))
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    return target


def prune(db_path, keep=DAILY_KEEP):
    """Deja los 'keep' mas recientes. Solo mira los diarios."""
    folder = folder_for(db_path)
    if not folder.exists():
        return []
    prefix = f"{Path(db_path).stem}-diario-"
    daily = sorted(
        (p for p in folder.glob(f"{prefix}*.db")),
        key=lambda p: p.name,
        reverse=True,
    )
    removed = []
    for old in daily[keep:]:
        old.unlink()
        removed.append(old.name)
    return removed


def ensure_daily(db_path, keep=DAILY_KEEP):
    """Hace el respaldo de hoy si todavia no existe."""
    path = Path(db_path)
    if not path.exists():
        return {"action": "missing"}

    folder = folder_for(path)
    target = folder / daily_name(path)
    if target.exists():
        return {"action": "ok", "backup": str(target)}

    with _exclusive(path):
        if target.exists():          # otro worker lo hizo mientras esperaba
            return {"action": "ok", "backup": str(target)}
        folder.mkdir(parents=True, exist_ok=True)
        make(path, target)

    return {
        "action": "created",
        "backup": str(target),
        "removed": prune(path, keep),
    }


def init_app(app):
    """Un respaldo al arrancar y, despues, una revision por hora.

    Sin esto, un servidor que lleva semanas sin reiniciarse se quedaria
    con el respaldo del dia que arranco.
    """
    if not app.config.get("AUTO_BACKUP", True):
        return

    _run(app)

    @app.before_request
    def maybe_backup():
        global _last_check
        now = time.monotonic()
        if now - _last_check < CHECK_EVERY_SECONDS:
            return None
        _last_check = now
        _run(app)
        return None


def _run(app):
    global _last_check
    _last_check = time.monotonic()
    try:
        result = ensure_daily(
            app.config["DB_PATH"], app.config.get("BACKUP_KEEP", DAILY_KEEP)
        )
    except Exception as exc:                     # noqa: BLE001
        # Un respaldo que falla no puede tumbar el sistema, pero tampoco
        # puede pasar en silencio.
        app.logger.error("No se pudo respaldar la base: %s", exc)
        return
    if result["action"] == "created":
        app.logger.info("Respaldo del dia: %s", result["backup"])
        for name in result.get("removed", []):
            app.logger.info("Respaldo viejo eliminado: %s", name)
