"""Application factory."""
import logging
import secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, g, render_template, request
from flask_wtf.csrf import CSRFError, CSRFProtect

from app import auth, backups, database, labels, money, phone, schema
from app.config import get_config

csrf = CSRFProtect()


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or get_config())

    _register_logging(app)

    database.init_app(app)
    money.init_app(app)
    phone.init_app(app)
    labels.init_app(app)
    csrf.init_app(app)

    _register_blueprints(app)
    _register_error_handlers(app)
    _register_context(app)
    _register_schema_guard(app)
    # Despues de la guardia de esquema, a proposito: una base sin
    # migrar tiene que explicarse aunque nadie haya entrado.
    auth.init_app(app)
    backups.init_app(app)
    _register_security_headers(app)

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
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.clients import bp as clients_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.outreach import bp as outreach_bp
    from app.blueprints.pets import bp as pets_bp
    from app.blueprints.services import bp as services_bp
    from app.blueprints.settings import bp as settings_bp
    from app.blueprints.stats import bp as stats_bp
    from app.blueprints.visits import bp as visits_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(outreach_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(services_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(visits_bp)


def _register_logging(app):
    """En produccion, lo que falla queda escrito en un archivo.

    Sin esto, cuando algo se rompe a las nueve de la noche no queda
    rastro que mandar: el traceback se lo lleva el proceso.
    """
    if app.debug or app.testing:
        return

    folder = Path(app.config["LOG_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        folder / "app.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s [%(pathname)s:%(lineno)d]"
    ))
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _register_security_headers(app):
    """Cabeceras que cierran puertas que no se usan.

    La aplicacion no carga nada de afuera: todo el CSS y el JS son
    propios. Decirlo explicitamente evita que una inyeccion pueda traer
    algo de otro lado. 'unsafe-inline' en estilos es necesario porque
    las barras del resumen llevan su ancho en un atributo style.
    """
    @app.before_request
    def make_nonce():
        # Un nonce nuevo por peticion. Es lo que deja pasar el unico
        # script en linea que hay (el que fija el tema antes de pintar)
        # sin tener que permitir scripts en linea en general, que seria
        # regalar la defensa entera.
        g.csp_nonce = secrets.token_urlsafe(16)

    @app.context_processor
    def expose_nonce():
        return {"csp_nonce": g.get("csp_nonce", "")}

    @app.after_request
    def headers(response):
        csp = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            f"script-src 'self' 'nonce-{g.get('csp_nonce', '')}'; "
            "form-action 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000"
            )
        return response


def _register_schema_guard(app):
    """Corta el paso cuando la base y el codigo no van a la misma version.

    Sin esto, una base sin migrar no falla al arrancar: falla mas tarde,
    con un error de SQLite crudo, justo cuando se intenta guardar algo.
    """
    expected = schema.expected_version(app.config["MIGRATIONS_DIR"])
    app.config["SCHEMA_VERSION"] = expected
    app.config["SCHEMA_ERROR"] = None

    if app.config.get("AUTO_MIGRATE", True):
        try:
            result = schema.ensure_migrated(
                app.config["DB_PATH"], app.config["MIGRATIONS_DIR"]
            )
            if result["action"] == "migrated":
                app.logger.warning(
                    "Base migrada de v%s a v%s (%s). Respaldo en %s",
                    result["from"], result["version"],
                    ", ".join(result["applied"]), result["backup"],
                )
        except schema.MigrationError as exc:
            # No se tumba la aplicacion: se deja que la guardia explique
            # lo que paso, que es mas util que no poder ni arrancar.
            app.config["SCHEMA_ERROR"] = str(exc)
            app.logger.error("No se pudo migrar la base: %s", exc)

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
            error=app.config["SCHEMA_ERROR"],
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
