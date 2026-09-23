"""Clientes: alta, edicion y ficha con sus mascotas."""
import sqlite3

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.database import get_db
from app.forms import clean_client
from app import segments
from app.phone import format_phone
from app.repos import clients, pets, settings, visits

bp = Blueprint("clients", __name__, url_prefix="/clientes")


# Definidos en app/segments.py, que es de donde los lee tambien la
# pantalla de envios: la misma pregunta tiene que dar el mismo numero
# en los dos lados.
FILTROS = segments.PANEL
PAGINA = clients.PAGINA


@bp.get("/")
def index():
    term = request.args.get("q", "")
    elegido = request.args.get("f", "")
    if elegido not in segments.CLAVES_PANEL:
        elegido = ""
    claves = [elegido] if elegido else []
    plazo = settings.followup_days()

    # Los numeros de las pestanias salen de UNA consulta, no de traerse
    # la tabla entera y contarla en memoria.
    cuentas = clients.group_counts(term, FILTROS, plazo)
    grupos = [{"key": "", "label": "Todos", "count": cuentas.get("", 0)}]
    grupos += [{"key": key, "label": label, "count": cuentas.get(key, 0)}
               for key, label, _cond in FILTROS]

    # Buscando se muestra todo lo que coincide: quien escribio un nombre
    # ya acoto solo. Sin buscar, la lista va de a diez, porque una base
    # de trescientos clientes no tiene por que viajar entera al celular
    # cada vez que se abre la pantalla.
    paginado = not term.strip()
    total = cuentas.get(elegido or "", 0)
    pagina = _pagina(request.args.get("p"), total, PAGINA)

    rows = clients.list_with_status(
        term, claves=claves, plazo=plazo, pagina=pagina,
        por_pagina=PAGINA if paginado else None,
    )

    return render_template(
        "clients/list.html", rows=rows, term=term, grupos=grupos,
        elegido=elegido, plazo=plazo,
        paginado=paginado, pagina=pagina, total=total,
        paginas=max(1, -(-total // PAGINA)) if paginado else 1,
    )


def _pagina(crudo, total, por_pagina):
    """El numero de pagina que pidieron, acotado a las que existen.

    Llega de la URL: una pagina 900 o un 'abc' no pueden dejar la
    pantalla en blanco ni reventar.
    """
    try:
        pedida = int(crudo)
    except (TypeError, ValueError):
        return 1
    ultima = max(1, -(-total // por_pagina))
    return min(max(1, pedida), ultima)


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

    a_visita = request.args.get("destino") == "visita"
    endpoint = "visits.create" if a_visita else "clients.detail"
    # Se venia de un dia pasado: el resultado tiene que llevar esa fecha
    # igual que los enlaces de la lista de abajo.
    extra = {"dia": request.args.get("dia")} if a_visita else {}

    rows = []
    for row in clients.search(term, limit=8):
        phone = format_phone(row["phone"]) or "sin tel\u00e9fono"
        pets = row["pet_names"]
        rows.append({
            "name": row["name"],
            "sub": f"{pets} \u00b7 {phone}" if pets else phone,
            "url": url_for(endpoint, client_id=row["id"], **extra),
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
