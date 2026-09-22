"""Application factory."""
from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import database, labels, money, phone, schema
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
    _register_context(app)
    _register_schema_guard(app)

    @app.get("/health")
    def health():
        found = schema.current_version(database.get_db())
        expected = app.config["SCHEMA_VERSION"]
        if found != expected:
            return {"status": "schema_mismatch",
                    "schema": found, "expected": expected}, 503
        return {"status": "ok", "schema": found}

    return app


def _register_blueprints(app):
    from app.blueprints.clients import bp as clients_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.pets import bp as pets_bp
    from app.blueprints.services import bp as services_bp
    from app.blueprints.settings import bp as settings_bp
    from app.blueprints.stats import bp as stats_bp
    from app.blueprints.visits import bp as visits_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(visits_bp)


def _register_schema_guard(app):
    """Corta el paso cuando la base y el codigo no van a la misma version.

    Sin esto, una base sin migrar no falla al arrancar: falla mas tarde,
    con un error de SQLite crudo, justo cuando se intenta guardar algo.
    """
    expected = schema.expected_version(app.config["MIGRATIONS_DIR"])
    app.config["SCHEMA_VERSION"] = expected

    @app.before_request
    def guard():
        # 'static' queda fuera o la pagina de error se veria sin estilos.
        # 'health' responde el desajuste en JSON, para poder vigilarlo.
        if request.endpoint in ("static", "health"):
            return None

        db = database.get_db()
        found = schema.current_version(db)
        if found == expected:
            return None

        return render_template(
            "errors/schema.html",
            found=found,
            expected=expected,
            missing=expected - found,
            empty=schema.is_empty(db),
        ), 503


def _register_context(app):
    """Nombre del negocio y plazo de atraso, disponibles en toda plantilla."""
    from app.repos import settings

    @app.context_processor
    def inject_business():
        try:
            return {
                "biz_name": settings.business_name(),
                "follow_days": settings.followup_days(),
            }
        except Exception:
            # Las paginas de error tienen que poder pintarse aunque la
            # base no responda; si no, un fallo se vuelve dos.
            return {"biz_name": "", "follow_days": 15}


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
