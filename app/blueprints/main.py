"""Pantalla de inicio: el punto de partida en el celular."""
from flask import Blueprint, render_template

from app.clock import today
from app.repos import clients, pets, services, visits

bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    hoy = today()
    totals = visits.day_total(hoy)
    pend = visits.pending_summary()
    return render_template(
        "main/home.html",
        hoy=hoy,
        totals=totals,
        pending=pend,
        # La lista completa, no solo el conteo: quien entra en la maniana
        # tiene que ver de una a quien le falta cobrarle, y a que hora
        # se recibio a esa mascota.
        pending_rows=visits.pending_all(),
        # Una pendiente de un dia anterior no se olvido por un rato:
        # se quedo colgada, y eso se avisa distinto.
        pending_stale=bool(pend["oldest"] and pend["oldest"] < hoy),
        client_count=clients.count_active(),
        pet_count=pets.count_active(),
        service_count=services.count_active(),
    )
