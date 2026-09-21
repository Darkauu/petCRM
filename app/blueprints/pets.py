"""Mascotas: siempre colgadas de un cliente."""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.forms import clean_pet
from app.repos import clients, pets

bp = Blueprint("pets", __name__)


@bp.route("/clientes/<int:client_id>/mascotas/nueva", methods=["GET", "POST"])
def create(client_id):
    client = clients.get(client_id)
    if client is None:
        return render_template("errors/404.html"), 404

    if request.method == "GET":
        return render_template(
            "pets/form.html", client=client, pet={}, errors={}
        )

    data, errors = clean_pet(request.form, client_id)
    if errors:
        return render_template(
            "pets/form.html", client=client, pet=data, errors=errors
        ), 400

    pets.create(data)
    flash(f"{data['name']} quedo registrado.", "ok")

    # "Guardar y agregar otra": el cliente con tres perros los mete de corrido.
    if request.form.get("and_another"):
        return redirect(url_for("pets.create", client_id=client_id))
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.route("/mascotas/<int:pet_id>/editar", methods=["GET", "POST"])
def edit(pet_id):
    pet = pets.get_with_client(pet_id)
    if pet is None:
        return render_template("errors/404.html"), 404
    client = clients.get(pet["client_id"])

    if request.method == "GET":
        return render_template("pets/form.html", client=client, pet=pet, errors={})

    data, errors = clean_pet(request.form, pet["client_id"])
    if errors:
        data["id"] = pet_id
        return render_template(
            "pets/form.html", client=client, pet=data, errors=errors
        ), 400

    pets.update(pet_id, data)
    flash("Mascota actualizada.", "ok")
    return redirect(url_for("clients.detail", client_id=pet["client_id"]))


@bp.post("/mascotas/<int:pet_id>/archivar")
def archive(pet_id):
    pet = pets.get_with_client(pet_id)
    if pet is None:
        return render_template("errors/404.html"), 404
    pets.archive(pet_id)
    flash("Mascota archivada.", "ok")
    return redirect(url_for("clients.detail", client_id=pet["client_id"]))
