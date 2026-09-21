"""Application factory."""
from flask import Flask, render_template
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import database, labels, money, phone
from app.config import get_config

csrf = CSRFProtect()


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    database.init_app(app)
    money.init_app(app)
    phone.init_app(app)
    labels.init_app(app)
    csrf.init_app(app)

    _register_blueprints(app)
    _register_error_handlers(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


def _register_blueprints(app):
    from app.blueprints.clients import bp as clients_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.pets import bp as pets_bp
    from app.blueprints.services import bp as services_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(services_bp)


def _register_error_handlers(app):
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        # Pasa cuando la pestana quedo abierta y la sesion expiro.
        return render_template("errors/expired.html"), 400
