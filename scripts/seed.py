"""Datos de prueba para ver el sistema funcionando.

Crea clientes, mascotas, servicios y visitas en fechas escalonadas, de
forma que se puedan ver de una vez los estados que importan: quien se
atraso y sale en la lista de WhatsApp, quien vino hace poco y no sale,
una mascota sin visitas, y una visita pendiente de cobro.

Uso:
    python scripts/seed.py
    python scripts/seed.py --telefono 6123-4567   # para probar wa.me
                                                  # contra tu propio numero
    python scripts/seed.py --force                # sobre una base con datos

Se niega a correr si la base ya tiene clientes, salvo --force: esto es
para desarrollo, y no tiene nada que hacer sobre datos de verdad.
"""
import argparse
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app                                   # noqa: E402
from app.clock import shift, today                           # noqa: E402
from app.repos import clients, pets, services, visits        # noqa: E402

NOTE = "Cliente de prueba (scripts/seed.py)"


def build(phone_for_whatsapp):
    """Cada cliente existe para mostrar un estado distinto."""
    bano = services.create("Baño completo", "Baño, secado y cepillado",
                           {"small": 1500, "medium": 2000, "large": 2800})
    corte = services.create("Corte de pelo", None,
                            {"small": 2500, "medium": 3200, "large": 4000})
    unias = services.create("Corte de uñas", None, {"any": 500})

    hoy = today()
    hecho = []

    # 1. El caso que se quiere ver: atrasado hace mucho.
    #    Su telefono es el que se pase por --telefono, para poder tocar
    #    "Escribirle" y que WhatsApp abra de verdad.
    ana = clients.create({
        "name": "Ana Vega", "phone": phone_for_whatsapp[0],
        "phone_display": phone_for_whatsapp[1], "document": None,
        "email": None, "address": None, "notes": NOTE,
    })
    rocky = pets.create(_pet(ana, "Rocky", "medium", breed="Cocker",
                             temperament="se mueve mucho al secar"))
    visits.create(ana, shift(hoy, -62), "Vino con las uñas muy largas",
                  [(rocky, bano, 2000), (rocky, unias, 500)],
                  status="completed")
    hecho.append(("Ana Vega", "atrasada hace 62 días — sale de primera en la lista"))

    # 2. Atrasado, pero apenas pasado del plazo.
    beto = clients.create(_client("Beto Lima", "6033-4455"))
    kira = pets.create(_pet(beto, "Kira", "small", breed="Schnauzer"))
    visits.create(beto, shift(hoy, -21), None,
                  [(kira, corte, 2500)], status="completed")
    hecho.append(("Beto Lima", "atrasado hace 21 días — también sale"))

    # 3. Vino hace poco: NO debe salir en atrasados.
    cira = clients.create(_client("Cira Paz", "6077-8899"))
    nina = pets.create(_pet(cira, "Nina", "large", breed="Labrador"))
    visits.create(cira, shift(hoy, -4), None,
                  [(nina, bano, 2800)], status="completed")
    hecho.append(("Cira Paz", "vino hace 4 días — NO sale en atrasados"))

    # 4. Dos mascotas, una sin visitas: el hueco tiene que verse.
    dora = clients.create(_client("Dora Sáez", "6011-2233"))
    toby = pets.create(_pet(dora, "Toby", "small", breed="Poodle"))
    luna = pets.create(_pet(dora, "Luna", "large"))
    visits.create(dora, shift(hoy, -30), None,
                  [(toby, bano, 1500), (toby, corte, 2500)],
                  status="completed")
    hecho.append(("Dora Sáez", "Toby atrasado, Luna sin visitas registradas"))

    # 5. Recibida hoy y sin cobrar: el flujo de cobro al entregar.
    elsa = clients.create(_client("Elsa Mora", "6044-5566"))
    max_ = pets.create(_pet(elsa, "Max", "medium"))
    visits.create(elsa, hoy, None, [(max_, bano, 2000), (max_, unias, 500)])
    hecho.append(("Elsa Mora", "recibida hoy, pendiente de cobro ($25.00)"))

    return hecho


def _client(name, phone_display):
    from app.phone import normalize_phone
    e164, display = normalize_phone(phone_display)
    return {"name": name, "phone": e164, "phone_display": display,
            "document": None, "email": None, "address": None, "notes": NOTE}


def _pet(client_id, name, size, breed=None, temperament=None):
    return {"client_id": client_id, "name": name, "species": "dog",
            "breed": breed, "size": size, "sex": None, "birthdate": None,
            "weight_kg": None, "temperament": temperament,
            "medical_notes": None, "is_active": 1}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--telefono", default="6123-4567",
                        help="numero del cliente atrasado, para probar wa.me")
    parser.add_argument("--force", action="store_true",
                        help="sembrar aunque la base ya tenga clientes")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        from app.phone import PhoneError, normalize_phone
        try:
            phone = normalize_phone(args.telefono)
        except PhoneError as exc:
            raise SystemExit(f"--telefono: {exc}")

        existing = clients.count_active()
        if existing and not args.force:
            raise SystemExit(
                f"La base ya tiene {existing} cliente(s). "
                "Si de verdad quieres sembrar encima, usa --force."
            )

        for name, why in build(phone):
            print(f"  {name:<12} {why}")
        from app.database import get_db
        get_db().commit()

    print("\nListo. Para ver el flujo de WhatsApp:")
    print("  Resumen -> «clientes llevan más de N días sin venir» -> Escribirle")
    print(f"  El botón de Ana Vega abre WhatsApp con {args.telefono}.")
