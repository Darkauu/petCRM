"""Capa de acceso a SQLite.

Toda consulta pasa por get_db(). Cuando llegue el multi-tenant (F9),
lo unico que cambia es de donde sale la ruta del archivo: el resto
de la aplicacion no se entera.
"""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g


def _connect(db_path):
    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DB_PATH"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        if exc is None:
            db.commit()
        else:
            db.rollback()
        db.close()


# ---- Helpers de consulta -------------------------------------------------

def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    """INSERT/UPDATE/DELETE. Devuelve el cursor (lastrowid, rowcount)."""
    return get_db().execute(sql, params)


@contextmanager
def transaction():
    """Agrupa varios execute() en una unidad.

    close_db() ya hace commit al final del request; lo que falta es
    garantizar el rollback cuando una operacion de varios pasos falla
    a la mitad (por ejemplo servicio + sus precios). Sin esto, el
    teardown confirmaria el trabajo incompleto.
    """
    db = get_db()
    try:
        yield db
    except Exception:
        db.rollback()
        raise


def init_app(app):
    app.teardown_appcontext(close_db)