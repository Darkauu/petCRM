"""Usuarios de la aplicacion.

app_user y login_event vienen de la migracion 001. login_event no es
decorativo: de ahi sale el freno a los intentos repetidos.
"""
from app.database import execute, query_one


def count_active():
    row = query_one("SELECT COUNT(*) AS n FROM app_user WHERE is_active = 1")
    return row["n"] if row else 0


def get_by_id(user_id):
    return query_one(
        "SELECT * FROM app_user WHERE id = ? AND is_active = 1", (user_id,)
    )


def get_by_email(email):
    return query_one(
        "SELECT * FROM app_user WHERE email = ? AND is_active = 1",
        ((email or "").strip().lower(),),
    )


def create(email, password_hash, display_name, role="owner"):
    cur = execute(
        """
        INSERT INTO app_user (email, password_hash, display_name, role)
        VALUES (?, ?, ?, ?)
        """,
        ((email or "").strip().lower(), password_hash, display_name, role),
    )
    return cur.lastrowid


def set_password(user_id, password_hash):
    execute(
        """
        UPDATE app_user
           SET password_hash = ?, updated_at = datetime('now')
         WHERE id = ?
        """,
        (password_hash, user_id),
    )


def touch_login(user_id):
    execute(
        "UPDATE app_user SET last_login_at = datetime('now') WHERE id = ?",
        (user_id,),
    )


def log_attempt(user_id, email_tried, ip, success):
    execute(
        """
        INSERT INTO login_event (user_id, email_tried, ip, success)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, (email_tried or "").strip().lower(), ip, 1 if success else 0),
    )


def recent_failures(email, ip, minutes=15):
    """Fallos recientes del mismo correo o de la misma IP.

    Se mira por ambos: por correo para que no sirva de nada cambiar de
    red, y por IP para que no sirva de nada ir probando correos.
    """
    row = query_one(
        """
        SELECT COUNT(*) AS n FROM login_event
         WHERE success = 0
           AND created_at > datetime('now', ?)
           AND (email_tried = ? OR ip = ?)
        """,
        (f"-{int(minutes)} minutes", (email or "").strip().lower(), ip),
    )
    return row["n"] if row else 0


def clear_failures(email, ip):
    """Tras un ingreso correcto, el contador vuelve a cero: si no, el
    duenio quedaria frenado por sus propios dedazos."""
    execute(
        """
        DELETE FROM login_event
         WHERE success = 0 AND (email_tried = ? OR ip = ?)
        """,
        ((email or "").strip().lower(), ip),
    )
