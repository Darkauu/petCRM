"""Entrar y salir.

Un solo negocio, un solo duenio: no hay registro abierto. La primera
cuenta se crea cuando no existe ninguna, y despues esa pantalla deja de
existir.
"""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app.repos import users

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8
MAX_FAILURES = 8          # intentos fallidos antes de frenar
LOCK_MINUTES = 15


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
    if row is None or not check_password_hash(row["password_hash"], password):
        users.log_attempt(row["id"] if row else None, email, ip, False)
        return render_template(
            "auth/login.html", email=email,
            error="Correo o contraseña incorrectos.",
        ), 401

    users.log_attempt(row["id"], email, ip, True)
    users.clear_failures(email, ip)
    users.touch_login(row["id"])
    login_user(_wrap(row), remember=True)
    return redirect(request.args.get("next") or url_for("main.home"))


@bp.post("/salir")
def logout():
    logout_user()
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("auth.login"))


def _wrap(row):
    from app.auth import User
    return User(row)
