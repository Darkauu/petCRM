"""Ajustes del negocio.

Son pocos a proposito: solo lo que es criterio del duenio y el sistema
no tiene forma de adivinar.
"""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.repos import settings

bp = Blueprint("settings", __name__, url_prefix="/ajustes")

WEEKDAYS = [
    (0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"),
    (4, "Viernes"), (5, "Sábado"), (6, "Domingo"),
]


@bp.route("/", methods=["GET", "POST"])
def edit():
    if request.method == "GET":
        return render_template(
            "settings/form.html",
            weekdays=WEEKDAYS,
            business_name=settings.business_name(),
            working=settings.working_days(),
            follow=settings.followup_days(),
            errors={},
        )

    errors = {}
    name = (request.form.get("business_name") or "").strip()[:120]

    chosen = sorted(
        int(value) for value in request.form.getlist("working_days")
        if value.isdigit() and 0 <= int(value) <= 6
    )
    if not chosen:
        errors["working_days"] = "Marca al menos un día."

    raw_follow = (request.form.get("followup_days") or "").strip()
    try:
        follow = int(raw_follow)
        if not 1 <= follow <= 365:
            raise ValueError
    except ValueError:
        errors["followup_days"] = "Pon un número de días entre 1 y 365."
        follow = settings.followup_days()

    if errors:
        return render_template(
            "settings/form.html",
            weekdays=WEEKDAYS,
            business_name=name,
            working=set(chosen),
            follow=follow,
            errors=errors,
        ), 400

    settings.save({
        "business_name": name,
        "working_days": ",".join(str(day) for day in chosen),
        "followup_days": str(follow),
    })
    flash("Ajustes guardados.", "ok")
    return redirect(url_for("settings.edit"))
