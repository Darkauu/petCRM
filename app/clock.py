"""Fecha local del negocio.

El servidor corre en UTC y SQLite entiende datetime('now') como UTC.
Panama es UTC-5 todo el ano (no hay horario de verano), asi que un
corrimiento fijo alcanza. Sin esto, todo lo registrado despues de las
7:00 p.m. hora local cae con la fecha del dia siguiente.
"""
from datetime import date, datetime, timedelta, timezone

OFFSET_HOURS = -5

# Fragmento reutilizable para consultas: fecha de calendario local.
SQL_TODAY = "date('now', '-5 hours')"


def now():
    return datetime.now(timezone.utc) + timedelta(hours=OFFSET_HOURS)


def today():
    """'YYYY-MM-DD' en hora de Panama."""
    return now().strftime("%Y-%m-%d")


def shift(day, days):
    """'2026-09-21' +/- N dias, para moverse entre dias en la agenda."""
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()
