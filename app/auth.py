"""Control de acceso.

El sistema completo queda detras de una sesion: no hay pantalla publica
mas que la de entrar. En vez de decorar vista por vista —donde olvidar
una es cuestion de tiempo— se cierra todo de entrada y se abre solo lo
que tiene que estar abierto.
"""
from flask import redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user

from app.repos import users

login_manager = LoginManager()

# Lo unico alcanzable sin sesion.
PUBLIC = {"auth.login", "auth.setup", "auth.logout", "static", "health"}


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]
        self.display_name = row["display_name"] or row["email"]
        self.role = row["role"]


@login_manager.user_loader
def load_user(user_id):
    try:
        row = users.get_by_id(int(user_id))
    except (TypeError, ValueError):
        return None
    return User(row) if row else None


def init_app(app):
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @app.before_request
    def require_login():
        if app.config.get("LOGIN_DISABLED"):
            return None
        if request.endpoint in PUBLIC:
            return None

        # Sin ninguna cuenta creada, todo lleva a crear la primera.
        if users.count_active() == 0:
            return redirect(url_for("auth.setup"))

        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.full_path))
        return None
