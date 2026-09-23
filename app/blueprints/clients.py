"""Clientes: alta, edicion y ficha con sus mascotas."""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.database import get_db
from app.forms import clean_client
from app.phone import format_phone
from app.repos import clients, pets, settings, visits

bp = Blueprint("clients", __name__, url_prefix="/clientes")


# Cada filtro es una pregunta que el duenio se hace de verdad. La clave
# de la URL elige una de estas funciones; nada de lo que llega por la
# peticion entra en una consulta.
FILTROS = [
    ("escribir", "Por escribir",
     lambda r, plazo: r["last_visit_date"] is not None and r["days"] > plazo),
    ("sin-visitas", "Sin visitas",
     lambda r, plazo: r["last_visit_date"] is None),
    ("pequenos", "Perros pequeños",
     lambda r, plazo: "small" in (r["sizes"] or "")),
    ("medianos", "Perros medianos",
     lambda r, plazo: "medium" in (r["sizes"] or "")),
    ("grandes", "Perros grandes",
     lambda r, plazo: "large" in (r["sizes"] or "")),
    # Despues de migrar el cuaderno hay fichas a medias. Sin una forma
    # de listarlas, el hueco se descubre con el cliente enfrente.
    ("incompletos", "Datos incompletos",
     lambda r, plazo: not r["phone"] or r["pets_sin_talla"] > 0),
]


@bp.get("/")
def index():
    term = request.args.get("q", "")
    elegido = request.args.get("f", "")
    plazo = settings.followup_days()

    todos = clients.list_with_status(term)

    # Se cuentan todos los grupos en una sola pasada: el numero al lado
    # de cada pestania es parte de la respuesta, no un adorno.
    grupos = [{"key": "", "label": "Todos", "count": len(todos)}]
    for key, label, cumple in FILTROS:
        grupos.append({"key": key, "label": label,
                       "count": sum(1 for r in todos if cumple(r, plazo))})

    rows = todos
    for key, _label, cumple in FILTROS:
        if key == elegido:
            rows = [r for r in todos if cumple(r, plazo)]
            break
    else:
        elegido = ""

    # Al buscar a quien escribirle, primero el que mas lleva esperando.
    if elegido == "escribir":
        rows = sorted(rows, key=lambda r: r["days"], reverse=True)

    return render_template(
        "clients/list.html", rows=rows, term=term, grupos=grupos,
        elegido=elegido, plazo=plazo,
    )


@bp.get("/buscar")
def search_json():
    """Coincidencias para el buscador que responde mientras se escribe.

    'destino' decide a donde lleva cada resultado: a la ficha del
    cliente o a registrarle una visita. La URL la arma el servidor, asi
    la pantalla no tiene que saber como se construyen las rutas.
    """
    term = (request.args.get("q") or "").strip()
    if not term:
        return {"rows": []}

    endpoint = ("visits.create" if request.args.get("destino") == "visita"
                else "clients.detail")

    rows = []
    for row in clients.search(term, limit=8):
        phone = row["phone_display"] or format_phone(row["phone"])
        pets = row["pet_names"]
        rows.append({
            "name": row["name"],
            "sub": f"{pets} \u00b7 {phone}" if pets else phone,
            "url": url_for(endpoint, client_id=row["id"]),
        })
    return {"rows": rows}


@bp.get("/<int:client_id>")
def detail(client_id):
    client = clients.get(client_id)
    if client is None:
        return render_template("errors/404.html"), 404
    return render_template(
        "clients/detail.html",
        client=client,
        pets=pets.list_for_client(client_id),
        visits=visits.list_for_client(client_id),
        total=clients.lifetime(client_id),
    )


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    if request.method == "GET":
        return render_template("clients/form.html", client={}, errors={})

    data, errors = clean_client(request.form)
    if not errors and data["phone"]:
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
    if not errors and data["phone"]:
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
