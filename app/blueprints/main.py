"""Pantalla de inicio: el punto de partida en el celular."""
from flask import Blueprint, render_template

from app.clock import today
from app.repos import clients, pets, services, visits

bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    count, cents = visits.day_total(today())
    return render_template(
        "main/home.html",
        today_count=count,
        today_cents=cents,
        client_count=clients.count_active(),
        pet_count=pets.count_active(),
        service_count=services.count_active(),
    )
