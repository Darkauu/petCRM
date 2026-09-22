"""Traduccion de enums a espanol.

El esquema guarda las claves en ingles ('small', 'dog'). La traduccion
vive aqui y se expone como filtros de Jinja, para que ninguna plantilla
tenga que conocer las claves.
"""
from datetime import date

SIZES = [
    ("small", "Pequeño"),
    ("medium", "Mediano"),
    ("large", "Grande"),
]

SPECIES = [
    ("dog", "Perro"),
    ("cat", "Gato"),
]

SEXES = [
    ("male", "Macho"),
    ("female", "Hembra"),
]

_SIZE = dict(SIZES)
_SPECIES = dict(SPECIES)
_SEX = dict(SEXES)

SIZE_KEYS = [k for k, _ in SIZES]
SPECIES_KEYS = [k for k, _ in SPECIES]
SEX_KEYS = [k for k, _ in SEXES]


def size_label(key):
    return _SIZE.get(key, "")


def species_label(key):
    return _SPECIES.get(key, "")


def sex_label(key):
    return _SEX.get(key, "")


_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic"]
_WEEKDAYS = ["lun", "mar", "mi\u00e9", "jue", "vie", "s\u00e1b", "dom"]


def short_date(iso, weekday=False):
    """'2026-09-21' -> '21 sep' (o 'lun 21 sep')."""
    if not iso:
        return ""
    try:
        d = date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    out = f"{d.day} {_MONTHS[d.month - 1]}"
    return f"{_WEEKDAYS[d.weekday()]} {out}" if weekday else out


def init_app(app):
    app.jinja_env.filters["size"] = size_label
    app.jinja_env.filters["species"] = species_label
    app.jinja_env.filters["sex"] = sex_label
    app.jinja_env.filters["fecha"] = short_date
    app.jinja_env.globals["SIZES"] = SIZES
    app.jinja_env.globals["SPECIES"] = SPECIES
    app.jinja_env.globals["SEXES"] = SEXES
