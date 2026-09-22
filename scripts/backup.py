"""Respaldo de la base, a mano o desde cron.

La aplicacion ya hace uno al dia sola. Esto sirve para forzar uno antes
de tocar algo, o para programarlo desde cron si se prefiere que no
dependa de que la aplicacion este levantada:

    0 3 * * *  cd /ruta/al/proyecto && .venv/bin/python scripts/backup.py

Uso:
    python scripts/backup.py            # el del dia, si no existe
    python scripts/backup.py --forzar   # uno nuevo con la hora en el nombre
    python scripts/backup.py --listar
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import backups                # noqa: E402
from app.config import Config          # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=Config.DB_PATH)
    parser.add_argument("--forzar", action="store_true")
    parser.add_argument("--listar", action="store_true")
    parser.add_argument("--conservar", type=int, default=backups.DAILY_KEEP)
    args = parser.parse_args()

    folder = backups.folder_for(args.db)

    if args.listar:
        if not folder.exists():
            raise SystemExit(f"No hay respaldos todavia en {folder}")
        for path in sorted(folder.glob("*.db")):
            size = path.stat().st_size / 1024
            print(f"  {path.name:<40} {size:8.1f} KB")
        raise SystemExit(0)

    if not Path(args.db).exists():
        raise SystemExit(f"No existe la base: {args.db}")

    if args.forzar:
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / f"{Path(args.db).stem}-manual-{stamp}.db"
        backups.make(args.db, target)
        print(f"Respaldo creado: {target}")
    else:
        result = backups.ensure_daily(args.db, args.conservar)
        if result["action"] == "created":
            print(f"Respaldo creado: {result['backup']}")
            for name in result.get("removed", []):
                print(f"  eliminado por antiguedad: {name}")
        elif result["action"] == "ok":
            print(f"Ya existe el respaldo de hoy: {result['backup']}")
        else:
            print(f"No existe la base: {args.db}")
