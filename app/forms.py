"""Validacion de formularios.

Cada clean_* devuelve (datos, errores). 'errores' es {campo: mensaje},
para pintarlo junto al campo y no como una lista arriba: en el celular,
un error que obliga a hacer scroll para saber cual campo fallo es un
formulario abandonado.

Se valida a mano en vez de con WTForms porque la pantalla de visita
(F2) lleva filas dinamicas de mascota x servicio, que con FieldList y
JS plano sale peor. Flask-WTF se sigue usando para el CSRF.
"""
import re
from datetime import date

from app.labels import SEX_KEYS, SIZE_KEYS, SPECIES_KEYS
from app.money import MoneyError, parse_money
from app.phone import PhoneError, normalize_phone

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _text(form, field, maxlen=200):
    value = (form.get(field) or "").strip()
    return value[:maxlen] if value else None


def clean_client(form):
    errors = {}
    data = {
        "name": _text(form, "name", 120),
        "document": _text(form, "document", 40),
        "email": _text(form, "email", 120),
        "address": _text(form, "address", 300),
        "notes": _text(form, "notes", 1000),
        "phone": None,
        "phone_display": None,
    }

    if not data["name"]:
        errors["name"] = "El nombre es obligatorio."

    try:
        e164, display = normalize_phone(form.get("phone"))
        data["phone"], data["phone_display"] = e164, display
    except PhoneError as exc:
        errors["phone"] = str(exc)

    if data["email"] and not _EMAIL_RE.match(data["email"]):
        errors["email"] = "Correo inválido."

    return data, errors


def clean_pet(form, client_id):
    errors = {}
    data = {
        "client_id": client_id,
        "name": _text(form, "name", 80),
        "breed": _text(form, "breed", 80),
        "temperament": _text(form, "temperament", 500),
        "medical_notes": _text(form, "medical_notes", 1000),
        "species": (form.get("species") or "dog").strip(),
        "size": (form.get("size") or "").strip(),
        "sex": _text(form, "sex", 10),
        "birthdate": _text(form, "birthdate", 10),
        "weight_kg": None,
        "is_active": 0 if form.get("inactive") else 1,
    }

    if not data["name"]:
        errors["name"] = "El nombre es obligatorio."

    if data["size"] not in SIZE_KEYS:
        errors["size"] = "Elige el tamaño."

    if data["species"] not in SPECIES_KEYS:
        data["species"] = "dog"

    if data["sex"] not in SEX_KEYS:
        data["sex"] = None

    if data["birthdate"]:
        if not _DATE_RE.match(data["birthdate"]):
            errors["birthdate"] = "Usa el formato AAAA-MM-DD."
        else:
            try:
                parsed = date.fromisoformat(data["birthdate"])
                if parsed > date.today():
                    errors["birthdate"] = "La fecha no puede estar en el futuro."
            except ValueError:
                errors["birthdate"] = "Fecha inválida."

    raw_weight = (form.get("weight_kg") or "").strip().replace(",", ".")
    if raw_weight:
        try:
            weight = float(raw_weight)
            if weight <= 0 or weight > 150:
                raise ValueError
            data["weight_kg"] = weight
        except ValueError:
            errors["weight_kg"] = "Peso inválido."

    return data, errors


def clean_service(form):
    """Precio unico ('any') o precio por talla, segun el modo elegido."""
    errors = {}
    name = _text(form, "name", 120)
    description = _text(form, "description", 500)
    mode = "size" if form.get("price_mode") == "size" else "any"
    prices = {}

    if not name:
        errors["name"] = "El nombre es obligatorio."

    if mode == "any":
        try:
            prices["any"] = parse_money(form.get("price_any"))
        except MoneyError as exc:
            errors["price_any"] = str(exc)
    else:
        for size in SIZE_KEYS:
            raw = (form.get(f"price_{size}") or "").strip()
            if not raw:
                continue
            try:
                prices[size] = parse_money(raw)
            except MoneyError as exc:
                errors[f"price_{size}"] = str(exc)
        if not prices and "price_small" not in errors:
            errors["price_small"] = "Pon al menos un precio."

    return {
        "name": name,
        "description": description,
        "mode": mode,
        "prices": prices,
        "is_active": 0 if form.get("inactive") else 1,
    }, errors


def clean_visit(form, pet_ids, service_ids, today):
    """Lineas de la visita.

    'pet' trae las mascotas elegidas y 'pick' los servicios marcados, con
    la forma 'idMascota:idServicio'; price_<mascota>_<servicio> lleva lo
    que se cobro.

    Solo cuentan los servicios de una mascota elegida. Hace falta porque
    la pantalla esconde los servicios de las mascotas sin elegir, pero
    los deja en el formulario: si alguien marca un servicio y despues
    cierra esa mascota, lo marcado no debe cobrarse.

    pet_ids y service_ids acotan lo que se acepta, para que un formulario
    manipulado no cuelgue la visita de la mascota de otro cliente.
    """
    errors = {}
    visit_date = (form.get("visit_date") or "").strip() or today
    notes = _text(form, "notes", 1000)

    if not _DATE_RE.match(visit_date):
        errors["visit_date"] = "Usa el formato AAAA-MM-DD."
        visit_date = today
    else:
        try:
            if date.fromisoformat(visit_date) > date.fromisoformat(today):
                errors["visit_date"] = "La visita no puede ser a futuro."
        except ValueError:
            errors["visit_date"] = "Fecha inválida."

    elegidas = {
        int(value) for value in form.getlist("pet")
        if str(value).isdigit() and int(value) in pet_ids
    }

    lines = []
    seen = set()
    for raw in form.getlist("pick"):
        try:
            pet_id, service_id = (int(part) for part in raw.split(":", 1))
        except (ValueError, TypeError):
            continue
        if pet_id not in elegidas or service_id not in service_ids:
            continue
        if (pet_id, service_id) in seen:
            continue
        seen.add((pet_id, service_id))

        field = f"price_{pet_id}_{service_id}"
        try:
            lines.append((pet_id, service_id, parse_money(form.get(field))))
        except MoneyError as exc:
            errors[field] = str(exc)

    if not lines and not errors:
        errors["lines"] = ("Elige la mascota que atendiste."
                           if not elegidas else "Marca al menos un servicio.")

    return ({"visit_date": visit_date, "notes": notes, "lines": lines,
             "pets": elegidas}, errors)
