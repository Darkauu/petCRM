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
from app.money import format_money
from app.phone import format_phone
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
    totals = visits.day_total(day)
    return render_template(
        "visits/day.html",
        day=day,
        rows=visits.list_for_date(day),
        totals=totals,
        is_today=(day == today()),
        prev_day=shift(day, -1),
        next_day=shift(day, 1),
    )


@bp.get("/buscar")
def search_json():
    """Coincidencias para el buscador que responde mientras se escribe.

    Devuelve la URL ya armada por el servidor: la pantalla no tiene que
    saber como se construyen las rutas.
    """
    term = (request.args.get("q") or "").strip()
    if not term:
        return {"rows": []}

    rows = []
    for row in clients.search(term, limit=8):
        phone = row["phone_display"] or format_phone(row["phone"])
        pets = row["pet_names"]
        rows.append({
            "name": row["name"],
            "sub": f"{pets} \u00b7 {phone}" if pets else phone,
            "url": url_for("visits.create", client_id=row["id"]),
        })
    return {"rows": rows}


@bp.get("/pendientes")
def pending():
    """Todo lo recibido y todavia sin cobrar, sin importar el dia."""
    return render_template("visits/pending.html", rows=visits.pending_all())


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

    charging = bool(request.form.get("charge"))
    visit_id = visits.create(
        client_id, data["visit_date"], data["notes"], data["lines"],
        status="completed" if charging else "pending",
    )
    total = visits.total_for(visit_id)
    if charging:
        flash(f"{client['name']}: cobrado {format_money(total)}.", "ok")
    else:
        flash(
            f"{client['name']} recibido. Queda pendiente de cobro "
            f"por {format_money(total)}.",
            "ok",
        )
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


@bp.post("/<int:visit_id>/cobrar")
def charge(visit_id):
    """Un toque al entregar la mascota: valida la visita y dice cuanto."""
    visit = visits.get(visit_id)
    if visit is None:
        return render_template("errors/404.html"), 404

    total = visits.total_for(visit_id)
    if visits.charge(visit_id):
        flash(f"{visit['client_name']}: cobrado {format_money(total)}.", "ok")
    else:
        # Doble toque, o alguien ya la cobro desde otra pantalla.
        flash(f"Esa visita ya no estaba pendiente.", "ok")
    return redirect(_back(visit))


@bp.post("/<int:visit_id>/cancelar")
def cancel(visit_id):
    """Se llevaron la mascota sin atenderla: no se cobra, pero queda
    el registro de que vinieron."""
    visit = visits.get(visit_id)
    if visit is None:
        return render_template("errors/404.html"), 404

    if visits.cancel(visit_id):
        flash(f"Visita de {visit['client_name']} cerrada sin cobro.", "ok")
    else:
        flash("Esa visita ya no estaba pendiente.", "ok")
    return redirect(_back(visit))


@bp.post("/<int:visit_id>/reabrir")
def reopen(visit_id):
    """Para deshacer un cobro o una cancelacion hecha por error."""
    visit = visits.get(visit_id)
    if visit is None:
        return render_template("errors/404.html"), 404

    if visits.reopen(visit_id):
        flash("Visita devuelta a pendiente de cobro.", "ok")
    return redirect(url_for("visits.edit", visit_id=visit_id))


def _back(visit):
    """Vuelve a donde se venia: la lista de pendientes o el dia."""
    if request.form.get("from") == "pending":
        return url_for("visits.pending")
    return url_for("visits.index", dia=visit["visit_date"])


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
