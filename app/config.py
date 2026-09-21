"""Configuracion por entorno. Cualquier valor sensible viene de .env."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    DB_PATH = str(BASE_DIR / os.environ.get("DB_PATH", "data/petcrm.db"))
    MIGRATIONS_DIR = str(BASE_DIR / "migrations")

    TIMEZONE = "America/Panama"

    # Sesion
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False   # True en produccion (HTTPS)
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12

    MAX_CONTENT_LENGTH = 5 * 1024 * 1024   # limite de subida (import Excel)

    # Dias sin venir a partir de los cuales una mascota se marca como
    # atrasada. Es un valor provisional del negocio, no una regla fija.
    FOLLOWUP_DAYS = 15


class DevelopmentConfig(Config):
    DEBUG = True
    # Sin esto, ni la sesion ni el CSRF arrancan en una maquina limpia
    # que todavia no tiene .env. Produccion sigue exigiendo la real.
    SECRET_KEY = Config.SECRET_KEY or "dev-inseguro-no-usar-en-produccion"


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    def __init__(self):
        if not Config.SECRET_KEY or len(Config.SECRET_KEY) < 32:
            raise RuntimeError(
                "SECRET_KEY ausente o demasiado corta para produccion."
            )


def get_config():
    env = os.environ.get("FLASK_ENV", "development")
    return ProductionConfig() if env == "production" else DevelopmentConfig()