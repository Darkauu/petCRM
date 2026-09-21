"""Prueba de humo de extremo a extremo.

Levanta la aplicacion contra una base temporal recien migrada y recorre
los flujos de la Fase 1. No usa pytest a proposito: se corre igual que
los demas scripts del proyecto, sin instalar nada extra.

Uso:
    python scripts/smoke.py
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app                     # noqa: E402
from app.config import DevelopmentConfig       # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    print(("  ok    " if condition else "  FALLA ") + label
          + (f"   {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(label)


def fresh_db():
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.executescript(
        (BASE_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8")
    )
    conn.commit()
    conn.close()
    return path


def run_flow(db_path):
    """Los caminos que el duenio recorre todos los dias."""
    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False

    app = create_app(Cfg)
    client = app.test_client()

    print("\nClientes y mascotas")
    r = client.get("/")
    check("el inicio carga", r.status_code == 200, r.status_code)
    r = client.get("/no-existe")
    check("una ruta inexistente da 404 y no una excepcion", r.status_code == 404)

    r = client.post("/clientes/nuevo",
                    data={"name": "Marta Rios", "phone": "6123-4567"})
    check("el alta de cliente sigue al alta de mascota",
          r.status_code == 302 and "/mascotas/nueva" in r.headers["Location"])

    r = client.post("/clientes/nuevo",
                    data={"name": "Otra", "phone": "+507 6123 4567"})
    check("el mismo telefono en otro formato se detecta como duplicado",
          r.status_code == 400 and "Marta Rios" in r.get_data(as_text=True))

    r = client.post("/clientes/1/mascotas/nueva",
                    data={"name": "Toby", "size": "small",
                          "breed": "Schnauzer", "temperament": "muerde al secar"})
    check("alta de mascota", r.status_code == 302)
    r = client.post("/clientes/1/mascotas/nueva",
                    data={"name": "Luna", "size": "large", "and_another": "1"})
    check("'guardar y agregar otra' regresa al formulario",
          r.status_code == 302 and "/mascotas/nueva" in r.headers["Location"])
    r = client.post("/clientes/1/mascotas/nueva", data={"name": "SinTalla"})
    check("no se guarda una mascota sin tamanio",
          r.status_code == 400)

    body = client.get("/clientes/1").get_data(as_text=True)
    check("la ficha lista las dos mascotas", "Toby" in body and "Luna" in body)
    check("la ficha avisa que no hay visitas registradas",
          body.count("Sin visitas registradas") == 2)
    check("la ficha muestra el manejo del perro", "muerde al secar" in body)

    print("\nBusqueda")
    check("por nombre de mascota",
          "Marta Rios" in client.get("/clientes/?q=toby").get_data(as_text=True))
    check("por telefono",
          "Marta Rios" in client.get("/clientes/?q=6123").get_data(as_text=True))

    print("\nCatalogo")
    r = client.post("/servicios/nuevo",
                    data={"name": "Bano completo", "price_mode": "size",
                          "price_small": "15", "price_medium": "20.50",
                          "price_large": "25"})
    check("servicio con precio por tamanio", r.status_code == 302)
    r = client.post("/servicios/nuevo",
                    data={"name": "Corte de unias", "price_mode": "any",
                          "price_any": "$5,00"})
    check("servicio con precio unico y coma decimal", r.status_code == 302)
    r = client.post("/servicios/nuevo",
                    data={"name": "Malo", "price_mode": "any",
                          "price_any": "1.999"})
    check("un precio con tres decimales se rechaza en vez de redondearse",
          r.status_code == 400)

    body = client.get("/servicios/").get_data(as_text=True)
    check("el catalogo muestra los precios",
          "$15.00" in body and "$20.50" in body and "$5.00" in body)

    with app.app_context():
        from app.repos import services
        check("el precio busca la talla exacta",
              services.price_for(1, "medium") == 2050)
        check("y cae a 'any' cuando no hay precio por talla",
              services.price_for(2, "large") == 500)

    print("\nRegistrar visita")
    body = client.get("/visitas/nueva").get_data(as_text=True)
    check("el selector avisa cuando no hay visitas previas",
          "Todav" in body and "primera" in body)

    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1", "2:1"],
                          "price_1_1": "18", "price_2_1": "25"})
    check("visita con dos mascotas en un solo registro", r.status_code == 302,
          r.get_data(as_text=True)[:300])

    body = client.get("/visitas/").get_data(as_text=True)
    check("el dia suma lo cobrado", "$43.00" in body, body[:400])
    check("el dia nombra a las dos mascotas",
          "Toby" in body and "Luna" in body)

    body = client.get("/visitas/nueva/1").get_data(as_text=True)
    check("el precio se precarga con el ultimo cobro, no con el de lista",
          'value="18.00"' in body)
    check("y se dice de donde salio", "\u00faltimo cobro" in body)

    print("\nEl historico no se reescribe")
    r = client.post("/servicios/1/editar",
                    data={"name": "Bano completo", "price_mode": "size",
                          "price_small": "30", "price_medium": "40",
                          "price_large": "50"})
    check("subir los precios del catalogo", r.status_code == 302)
    body = client.get("/visitas/").get_data(as_text=True)
    check("la visita ya cobrada sigue valiendo lo mismo", "$43.00" in body)

    print("\nEl formulario no se deja manipular")
    r = client.post("/visitas/nueva/1",
                    data={"pick": ["999:1"], "price_999_1": "10"})
    check("una mascota ajena se ignora y no se guarda nada",
          r.status_code == 400 and "al menos un servicio" in r.get_data(as_text=True))
    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1"], "price_1_1": "10",
                          "visit_date": "2099-01-01"})
    check("una fecha futura se rechaza",
          r.status_code == 400 and "futuro" in r.get_data(as_text=True))
    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1"], "price_1_1": "no es plata"})
    body = r.get_data(as_text=True)
    check("un precio ilegible se rechaza", r.status_code == 400)
    check("el servicio marcado no se pierde al volver",
          'value="1:1"' in body and "checked" in body)
    check("y se devuelve lo que se escribio, no otro numero",
          "no es plata" in body and 'value="18.00"' not in body)

    print("\nCorregir una visita")
    r = client.post("/visitas/1/editar",
                    data={"pick": ["1:1", "2:1"],
                          "price_1_1": "20", "price_2_1": "25",
                          "notes": "Luna vino con garrapatas"})
    check("editar la visita", r.status_code == 302)
    body = client.get("/visitas/").get_data(as_text=True)
    check("el total refleja la correccion", "$45.00" in body)
    check("la nota queda visible", "garrapatas" in body)

    body = client.get("/clientes/1").get_data(as_text=True)
    check("la ficha del cliente muestra la visita", "$45.00" in body)
    check("y el marcador dice que vino hoy", "Hace 0" in body)

    print("\nMarcador de ultima visita")
    check("eliminar la visita", client.post("/visitas/1/archivar").status_code == 302)
    body = client.get("/visitas/").get_data(as_text=True)
    check("el dia vuelve a cero", "$0.00" in body)
    body = client.get("/clientes/1").get_data(as_text=True)
    check("la visita eliminada deja de contar para el marcador",
          body.count("Sin visitas registradas") == 2)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO visit (client_id, visit_date) "
        "VALUES (1, date('now','-5 hours','-20 days'))"
    )
    conn.execute(
        "INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
        "VALUES (2, 1, 1, 1500)"
    )
    conn.commit()
    conn.close()

    body = client.get("/clientes/1").get_data(as_text=True)
    check("cuenta los dias desde la ultima visita", "Hace 20" in body)
    check("ofrece escribirle al pasarse del plazo", "Escribirle" in body)
    check("la mascota sin visitas sigue marcada como hueco",
          "Sin visitas registradas" in body)

    print("\nInicio")
    body = client.get("/").get_data(as_text=True)
    check("el inicio ofrece registrar visita como accion principal",
          "Registrar visita" in body)

def run_csrf(db_path):
    print("\nProteccion CSRF")

    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True          # CSRF activo a proposito

    client = create_app(Cfg).test_client()
    r = client.post("/clientes/nuevo", data={"name": "X", "phone": "61234567"})
    check("un POST sin token se rechaza con una pagina entendible",
          r.status_code == 400 and "vencida" in r.get_data(as_text=True))


if __name__ == "__main__":
    for runner in (run_flow, run_csrf):
        path = fresh_db()
        try:
            runner(path)
        finally:
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(path + suffix):
                    os.unlink(path + suffix)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} fallas: {FAILURES}")
        raise SystemExit(1)
    print("Todo verde.")
