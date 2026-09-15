"""Crea la base del negocio y aplica todas las migraciones.

Uso:
    python scripts/init_db.py
    python scripts/init_db.py --force     # borra y recrea (solo desarrollo)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app.config import Config          # noqa: E402
from scripts.migrate import apply_all  # noqa: E402


def create(db_path, force=False):
    path = Path(db_path)
    if path.exists():
        if not force:
            print(f"Ya existe: {path}. Se aplicaran solo las migraciones pendientes.")
            return
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()
        print(f"Base anterior eliminada: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    # PERSISTENTE: se aplica una sola vez, queda grabado en el archivo.
    mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.close()
    print(f"Base creada: {path} (journal_mode={mode})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=Config.DB_PATH)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    create(args.db, force=args.force)
    apply_all(args.db, Config.MIGRATIONS_DIR)