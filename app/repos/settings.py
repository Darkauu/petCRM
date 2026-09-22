"""Ajustes del negocio (tabla setting, clave/valor).

Aqui viven los criterios que son juicio del duenio y no del sistema:
que dias abre y a partir de cuantos dias considera que un cliente se
atraso. Se leen una vez por request y se guardan en g.
"""
from flask import g

from app.database import execute, query_all

DEFAULTS = {
    "business_name": "",
    "working_days": "0,1,2,3,4,5,6",
    "followup_days": "15",
}


def all_settings():
    if "settings" not in g:
        data = dict(DEFAULTS)
        for row in query_all("SELECT key, value FROM setting"):
            if row["value"] is not None:
                data[row["key"]] = row["value"]
        g.settings = data
    return g.settings


def get(key, default=""):
    return all_settings().get(key, default)


def save(pairs):
    for key, value in pairs.items():
        execute(
            """
            INSERT INTO setting (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE
               SET value = excluded.value, updated_at = datetime('now')
            """,
            (key, value),
        )
    g.pop("settings", None)


def working_days():
    """Dias que abre, lunes = 0. Si el valor esta corrupto, los siete:
    de este numero depende que se marque un hueco, y marcar de mas es
    menos danino que esconder un dia sin registrar."""
    raw = get("working_days", DEFAULTS["working_days"])
    days = {
        int(part) for part in str(raw).split(",")
        if part.strip().isdigit() and 0 <= int(part) <= 6
    }
    return days or {0, 1, 2, 3, 4, 5, 6}


def followup_days():
    raw = get("followup_days", DEFAULTS["followup_days"])
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return int(DEFAULTS["followup_days"])
    return value if 1 <= value <= 365 else int(DEFAULTS["followup_days"])


def business_name():
    return (get("business_name") or "").strip()
