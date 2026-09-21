"""Pantalla de inicio: el punto de partida en el celular."""
from flask import Blueprint, render_template

from app.repos import clients, pets, services

bp = Blueprint("main", __name__)


@bp.get("/")
def home():
    return render_template(
        "main/home.html",
        client_count=clients.count_active(),
        pet_count=pets.count_active(),
        service_count=services.count_active(),
    )
