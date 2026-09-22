"""Entrar y salir.

Un solo negocio, un solo duenio: no hay registro abierto. La primera
cuenta se crea cuando no existe ninguna, y despues esa pantalla deja de
existir.
"""
import sqlite3
from urllib.parse import urlparse

from flask import (Blueprint, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.repos import users

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
MAX_PASSWORD = 200        # arriba de esto solo se gasta CPU en el hash
MAX_FAILURES = 8          # intentos fallidos antes de frenar
LOCK_MINUTES = 15

# Se compara contra este hash cuando el correo no existe, para que
# responder "no existe" tarde lo mismo que responder "clave mala". Sin
# esto, el tiempo de respuesta delata cuales correos estan registrados.
_DUMMY_HASH = generate_password_hash("no-existe-pero-cuesta-lo-mismo")


def safe_next(target):
    """Solo rutas de este mismo sitio.

    Sin esto, un enlace como /entrar?next=https://sitio-falso manda al
    duenio a una copia justo despues de entrar, que es cuando menos
    sospecha.
    """
    if not target or "\\" in target:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target


@bp.route("/crear-cuenta", methods=["GET", "POST"])
def setup():
    """Solo existe mientras no haya ninguna cuenta."""
    if users.count_active():
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return render_template("auth/setup.html", email="", errors={})

    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("display_name") or "").strip()[:80]
    password = request.form.get("password") or ""
    repeat = request.form.get("password2") or ""
    errors = {}

    if "@" not in email or len(email) < 5:
        errors["email"] = "Escribe un correo válido."
    if len(password) < MIN_PASSWORD:
        errors["password"] = f"Usa al menos {MIN_PASSWORD} caracteres."
    elif len(password) > MAX_PASSWORD:
        errors["password"] = f"Máximo {MAX_PASSWORD} caracteres."
    elif password != repeat:
        errors["password2"] = "Las dos contraseñas no coinciden."

    if errors:
        return render_template(
            "auth/setup.html", email=email, errors=errors
        ), 400

    try:
        user_id = users.create(email, generate_password_hash(password), name)
    except sqlite3.IntegrityError:
        return render_template(
            "auth/setup.html", email=email,
            errors={"email": "Ese correo ya está registrado."},
        ), 400

    session.clear()          # identificador de sesion nuevo al entrar
    login_user(_wrap(users.get_by_id(user_id)), remember=True)
    users.touch_login(user_id)
    flash("Cuenta creada. Ya puedes usar el sistema.", "ok")
    return redirect(url_for("main.home"))


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if users.count_active() == 0:
        return redirect(url_for("auth.setup"))
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "GET":
        return render_template("auth/login.html", email="", error=None)

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    ip = request.remote_addr or ""

    if users.recent_failures(email, ip, LOCK_MINUTES) >= MAX_FAILURES:
        # No se dice si el correo existe: eso seria decirle a quien
        # prueba cual de los dos datos acerto.
        return render_template(
            "auth/login.html", email=email,
            error=f"Demasiados intentos. Espera {LOCK_MINUTES} minutos.",
        ), 429

    row = users.get_by_email(email)
    # La comprobacion corre siempre, exista o no el correo: asi las dos
    # respuestas tardan lo mismo.
    stored = row["password_hash"] if row else _DUMMY_HASH
    correct = check_password_hash(stored, password[:MAX_PASSWORD])

    if row is None or not correct:
        users.log_attempt(row["id"] if row else None, email, ip, False)
        return render_template(
            "auth/login.html", email=email,
            error="Correo o contraseña incorrectos.",
        ), 401

    users.log_attempt(row["id"], email, ip, True)
    users.clear_failures(email, ip)
    users.touch_login(row["id"])
    session.clear()          # identificador de sesion nuevo al entrar
    login_user(_wrap(row), remember=True)
    return redirect(safe_next(request.args.get("next")) or url_for("main.home"))


@bp.post("/salir")
def logout():
    # El orden importa: logout_user() deja en la sesion la marca que
    # borra la cookie de "recordarme". Limpiar despues borraria esa
    # marca, la cookie sobreviviria y el siguiente request volveria a
    # entrar solo. Se limpia antes.
    session.clear()
    logout_user()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("auth.login"))


def _wrap(row):
    from app.auth import User
    return User(row)
