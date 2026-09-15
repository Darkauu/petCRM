"""Application factory."""
from flask import Flask, render_template

from app import database, money, phone
from app.config import get_config


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    database.init_app(app)
    money.init_app(app)
    phone.init_app(app)

    _register_blueprints(app)
    _register_error_handlers(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _register_blueprints(app):
    # F1 en adelante:
    # from app.blueprints.auth import bp as auth_bp
    # app.register_blueprint(auth_bp)
    pass


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500