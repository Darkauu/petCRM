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


def week_bounds(day):
    """Lunes y domingo de la semana en que cae 'day'."""
    d = date.fromisoformat(day)
    monday = d - timedelta(days=d.weekday())
    return monday.isoformat(), (monday + timedelta(days=6)).isoformat()


def month_bounds(day):
    """Primer y ultimo dia del mes en que cae 'day'."""
    d = date.fromisoformat(day)
    first = d.replace(day=1)
    if first.month == 12:
        last = first.replace(year=first.year + 1, month=1) - timedelta(days=1)
    else:
        last = first.replace(month=first.month + 1) - timedelta(days=1)
    return first.isoformat(), last.isoformat()


def days_between(desde, hasta):
    """Todas las fechas del rango, inclusivo."""
    start, end = date.fromisoformat(desde), date.fromisoformat(hasta)
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def span_days(desde, hasta):
    return (date.fromisoformat(hasta) - date.fromisoformat(desde)).days + 1


def weekday_of(day):
    """Lunes = 0 ... domingo = 6."""
    return date.fromisoformat(day).weekday()
