"""Registro de visitas.

La pantalla que se usa decenas de veces por semana, de pie y con prisa.
Todo aqui esta ordenado para el caso repetido: cliente que ya existe,
mascota que ya existe, servicio de siempre. El caso completo se puede
alcanzar, pero no es el que manda.
"""
from datetime import date

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app.clock import shift, today
from app.forms import clean_visit
from app.repos import clients, pets, services, visits

bp = Blueprint("visits", __name__, url_prefix="/visitas")


@bp.get("/")
def index():
    # 'dia' viene de la URL: si trae basura se cae a hoy en vez de
    # reventar al calcular el dia anterior.
    day = request.args.get("dia") or ""
    try:
        date.fromisoformat(day)
    except ValueError:
        day = today()
    count, cents = visits.day_total(day)
    return render_template(
        "visits/day.html",
        day=day,
        rows=visits.list_for_date(day),
        count=count,
        total_cents=cents,
        is_today=(day == today()),
        prev_day=shift(day, -1),
        next_day=shift(day, 1),
    )


@bp.get("/nueva")
def pick_client():
    """Paso 1: a quien se atendio. Los ultimos atendidos van de primero."""
    term = request.args.get("q", "")
    return render_template(
        "visits/pick.html",
        term=term,
        rows=clients.search(term) if term else None,
        recent=visits.recent_clients(),
    )


@bp.route("/nueva/<int:client_id>", methods=["GET", "POST"])
def create(client_id):
    client = clients.get(client_id)
    if client is None:
        return render_template("errors/404.html"), 404

    pet_rows = pets.list_for_client(client_id)
    service_rows = services.list_all()

    if not pet_rows:
        flash("Ese cliente no tiene mascotas registradas todavía.", "ok")
        return redirect(url_for("pets.create", client_id=client_id))
    if not service_rows:
        flash("No hay servicios en el catálogo. Crea al menos uno.", "ok")
        return redirect(url_for("services.create"))

    if request.method == "GET":
        return render_template(
            "visits/form.html",
            client=client, pet_rows=pet_rows, service_rows=service_rows,
            grid=_grid(client_id, pet_rows, service_rows),
            picked=set(), visit={"visit_date": today()}, errors={},
        )

    data, errors = clean_visit(
        request.form,
        {row["id"] for row in pet_rows},
        {row["id"] for row in service_rows},
        today(),
    )
    if errors:
        return _rerender(client, pet_rows, service_rows, data, errors), 400

    visits.create(client_id, data["visit_date"], data["notes"], data["lines"])
    flash(f"Visita de {client['name']} registrada.", "ok")
    return redirect(url_for("visits.index", dia=data["visit_date"]))


@bp.route("/<int:visit_id>/editar", methods=["GET", "POST"])
def edit(visit_id):
    visit = visits.get(visit_id)
    if visit is None:
        return render_template("errors/404.html"), 404

    client = clients.get(visit["client_id"])
    if client is None:
        return render_template("errors/404.html"), 404

    pet_rows = pets.list_for_client(visit["client_id"])
    lines = visits.lines_for(visit_id)

    # Un servicio que ya salio del catalogo sigue apareciendo si esta
    # visita lo usa: si no, editar la fecha lo borraria del historico.
    service_rows = list(services.list_all())
    known = {row["id"] for row in service_rows}
    for line in lines:
        if line["service_id"] not in known:
            extra = services.get(line["service_id"])
            if extra is not None:
                service_rows.append(extra)
                known.add(extra["id"])

    existing = {(l["pet_id"], l["service_id"]): l["price_cents"] for l in lines}

    if request.method == "GET":
        return render_template(
            "visits/form.html",
            client=client, pet_rows=pet_rows, service_rows=service_rows,
            grid=_grid(visit["client_id"], pet_rows, service_rows, existing),
            picked=set(existing), visit=visit, errors={},
        )

    data, errors = clean_visit(
        request.form,
        {row["id"] for row in pet_rows},
        known,
        today(),
    )
    if errors:
        data["id"] = visit_id
        return _rerender(client, pet_rows, service_rows, data, errors), 400

    visits.update(visit_id, data["visit_date"], data["notes"], data["lines"])
    flash("Visita actualizada.", "ok")
    return redirect(url_for("visits.index", dia=data["visit_date"]))


@bp.post("/<int:visit_id>/archivar")
def archive(visit_id):
    visit = visits.get(visit_id)
    if visit is None:
        return render_template("errors/404.html"), 404
    visits.archive(visit_id)
    flash("Visita eliminada.", "ok")
    return redirect(url_for("visits.index", dia=visit["visit_date"]))


def _rerender(client, pet_rows, service_rows, data, errors):
    """Vuelve a pintar el formulario sin perder lo que ya habia marcado."""
    picked = {(pet, svc) for pet, svc, _ in data["lines"]}
    picked |= {
        tuple(int(part) for part in key.split("_")[1:])
        for key in errors if key.startswith("price_")
    }
    grid = _grid(
        client["id"], pet_rows, service_rows,
        {(pet, svc): cents for pet, svc, cents in data["lines"]},
    )
    return render_template(
        "visits/form.html",
        client=client, pet_rows=pet_rows, service_rows=service_rows,
        grid=grid, picked=picked, visit=data, errors=errors,
    )


def _grid(client_id, pet_rows, service_rows, existing=None):
    """Precio precargado para cada par mascota/servicio.

    Orden de preferencia: lo que ya tiene esta visita, lo que se le cobro
    a esa mascota la ultima vez, y de ultimo el precio de lista por talla.
    El de en medio es el que hace que el duenio solo confirme en vez de
    escribir.
    """
    last = visits.last_prices(client_id)
    catalog = services.prices_map()
    grid = {}

    for pet in pet_rows:
        for service in service_rows:
            key = (pet["id"], service["id"])
            if existing and key in existing:
                grid[key] = {"cents": existing[key], "source": "visit"}
            elif key in last:
                grid[key] = {"cents": last[key], "source": "last"}
            else:
                by_size = catalog.get(service["id"], {})
                cents = by_size.get(pet["size"], by_size.get("any"))
                grid[key] = {
                    "cents": cents,
                    "source": "catalog" if cents is not None else "none",
                }
    return grid
