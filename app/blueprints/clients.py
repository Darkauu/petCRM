"""Clientes: alta, edicion y ficha con sus mascotas."""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.database import get_db
from app.forms import clean_client
from app.repos import clients, pets

bp = Blueprint("clients", __name__, url_prefix="/clientes")


@bp.get("/")
def index():
    term = request.args.get("q", "")
    return render_template(
        "clients/list.html", rows=clients.search(term), term=term
    )


@bp.get("/<int:client_id>")
def detail(client_id):
    client = clients.get(client_id)
    if client is None:
        return render_template("errors/404.html"), 404
    return render_template(
        "clients/detail.html", client=client, pets=pets.list_for_client(client_id)
    )


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    if request.method == "GET":
        return render_template("clients/form.html", client={}, errors={})

    data, errors = clean_client(request.form)
    if not errors:
        existing = clients.find_by_phone(data["phone"])
        if existing:
            errors["phone"] = (
                f"Ese telefono ya es de {existing['name']}."
            )

    if errors:
        return render_template("clients/form.html", client=data, errors=errors), 400

    try:
        client_id = clients.create(data)
    except sqlite3.IntegrityError as exc:
        get_db().rollback()
        return render_template(
            "clients/form.html", client=data, errors=_integrity_error(exc)
        ), 400

    flash(f"{data['name']} quedo registrado.", "ok")
    # Un cliente sin mascota no sirve para nada: se sigue directo al alta.
    return redirect(url_for("pets.create", client_id=client_id))


@bp.route("/<int:client_id>/editar", methods=["GET", "POST"])
def edit(client_id):
    client = clients.get(client_id)
    if client is None:
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        return render_template("clients/form.html", client=client, errors={})

    data, errors = clean_client(request.form)
    if not errors:
        existing = clients.find_by_phone(data["phone"])
        if existing and existing["id"] != client_id:
            errors["phone"] = f"Ese telefono ya es de {existing['name']}."

    if errors:
        data["id"] = client_id
        return render_template("clients/form.html", client=data, errors=errors), 400

    try:
        clients.update(client_id, data)
    except sqlite3.IntegrityError as exc:
        get_db().rollback()
        data["id"] = client_id
        return render_template(
            "clients/form.html", client=data, errors=_integrity_error(exc)
        ), 400

    flash("Cliente actualizado.", "ok")
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.post("/<int:client_id>/archivar")
def archive(client_id):
    if clients.get(client_id) is None:
        return render_template("errors/404.html"), 404
    clients.archive(client_id)
    flash("Cliente archivado. Su historial se conserva.", "ok")
    return redirect(url_for("clients.index"))


def _integrity_error(exc):
    text = str(exc)
    if "client.email" in text:
        return {"email": "Ese correo ya esta registrado."}
    if "client.document" in text:
        return {"document": "Esa cedula ya esta registrada."}
    if "client.phone" in text:
        return {"phone": "Ese telefono ya esta registrado."}
    return {"name": "No se pudo guardar. Revisa los datos."}
