"""Catalogo de servicios y precios."""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.database import get_db
from app.forms import clean_service
from app.repos import services

bp = Blueprint("services", __name__, url_prefix="/servicios")


@bp.get("/")
def index():
    rows = services.list_all(include_inactive=True)
    return render_template(
        "services/list.html", rows=rows, prices=services.prices_map()
    )


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    if request.method == "GET":
        return render_template(
            "services/form.html", service={}, prices={}, errors={}
        )

    data, errors = clean_service(request.form)
    if errors:
        return render_template(
            "services/form.html", service=data, prices=data["prices"], errors=errors
        ), 400

    try:
        services.create(data["name"], data["description"], data["prices"])
    except sqlite3.IntegrityError:
        get_db().rollback()
        return render_template(
            "services/form.html",
            service=data,
            prices=data["prices"],
            errors={"name": "Ya existe un servicio con ese nombre."},
        ), 400

    flash(f"Servicio «{data['name']}» creado.", "ok")
    return redirect(url_for("services.index"))


@bp.route("/<int:service_id>/editar", methods=["GET", "POST"])
def edit(service_id):
    service = services.get(service_id)
    if service is None:
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        return render_template(
            "services/form.html",
            service=service,
            prices=services.prices_for(service_id),
            errors={},
        )

    data, errors = clean_service(request.form)
    if errors:
        data["id"] = service_id
        return render_template(
            "services/form.html", service=data, prices=data["prices"], errors=errors
        ), 400

    try:
        services.update(
            service_id,
            data["name"],
            data["description"],
            data["prices"],
            data["is_active"],
        )
    except sqlite3.IntegrityError:
        get_db().rollback()
        data["id"] = service_id
        return render_template(
            "services/form.html",
            service=data,
            prices=data["prices"],
            errors={"name": "Ya existe un servicio con ese nombre."},
        ), 400

    flash("Servicio actualizado.", "ok")
    return redirect(url_for("services.index"))


@bp.post("/<int:service_id>/estado")
def toggle(service_id):
    service = services.get(service_id)
    if service is None:
        return render_template("errors/404.html"), 404
    services.set_active(service_id, not service["is_active"])
    flash(
        "Servicio reactivado." if not service["is_active"]
        else "Servicio sacado del catálogo. El histórico no cambia.",
        "ok",
    )
    return redirect(url_for("services.index"))
