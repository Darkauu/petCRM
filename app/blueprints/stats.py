"""Resumen: pocas cifras, ciertas y accionables.

La regla que ordena esta pantalla: una metrica que no cambia una
decision no va. Y si la data del periodo tiene huecos, el hueco se
muestra antes que las cifras, porque un numero construido sobre
registros incompletos es peor que no tener el numero.
"""
from datetime import date

from flask import Blueprint, render_template, request

from app.clock import month_bounds, shift, span_days, today, week_bounds
from app.repos import settings, stats

bp = Blueprint("stats", __name__, url_prefix="/resumen")

PERIODS = [
    ("semana", "Esta semana"),
    ("semana_pasada", "Semana pasada"),
    ("mes", "Este mes"),
    ("mes_pasado", "Mes pasado"),
]


@bp.get("/")
def summary():
    desde, hasta, period = _range()
    days = span_days(desde, hasta)

    # Periodo inmediatamente anterior, del mismo largo, para comparar.
    prev_hasta = shift(desde, -1)
    prev_desde = shift(prev_hasta, -(days - 1))

    now = stats.period_summary(desde, hasta)
    before = stats.period_summary(prev_desde, prev_hasta)
    follow = settings.followup_days()

    return render_template(
        "stats/summary.html",
        desde=desde, hasta=hasta, period=period, periods=PERIODS,
        now=now,
        before=before,
        delta=_delta(now["cents"], before["cents"]),
        avg_cents=(now["cents"] // now["pets"]) if now["pets"] else None,
        services=stats.services_breakdown(desde, hasta),
        clients=stats.client_split(desde, hasta),
        follow=follow,
        overdue=stats.overdue_count(follow),
        gaps=stats.days_without_records(desde, hasta, settings.working_days()),
        empty_visits=stats.visits_without_services(desde, hasta),
    )


@bp.get("/atrasados")
def overdue():
    follow = settings.followup_days()
    return render_template(
        "stats/overdue.html",
        rows=stats.overdue_clients(follow),
        follow=follow,
    )


def _delta(now_cents, before_cents):
    """Variacion contra el periodo anterior. None cuando no hay con que
    comparar: inventar un 100% sobre cero no dice nada."""
    if not before_cents:
        return None
    return round((now_cents - before_cents) * 100 / before_cents)


def _range():
    """El rango sale de 'desde'/'hasta', o del atajo 'p'."""
    desde = request.args.get("desde", "")
    hasta = request.args.get("hasta", "")
    if _is_date(desde) and _is_date(hasta) and desde <= hasta:
        return desde, hasta, None

    period = request.args.get("p", "semana")
    now = today()
    if period == "semana_pasada":
        return (*week_bounds(shift(now, -7)), period)
    if period == "mes":
        return (*month_bounds(now), period)
    if period == "mes_pasado":
        first, _ = month_bounds(now)
        return (*month_bounds(shift(first, -1)), period)
    return (*week_bounds(now), "semana")


def _is_date(value):
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False
