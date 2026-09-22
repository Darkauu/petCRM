"""Prueba de humo de extremo a extremo.

Levanta la aplicacion contra una base temporal recien migrada y recorre
los flujos de la Fase 1. No usa pytest a proposito: se corre igual que
los demas scripts del proyecto, sin instalar nada extra.

Uso:
    python scripts/smoke.py
"""
import contextlib
import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app                     # noqa: E402
from app.config import DevelopmentConfig       # noqa: E402
from scripts.migrate import apply_all          # noqa: E402

FAILURES = []


def check(label, condition, detail=""):
    print(("  ok    " if condition else "  FALLA ") + label
          + (f"   {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(label)


def fresh_db():
    """Base nueva con TODAS las migraciones aplicadas por el runner real."""
    path = tempfile.mktemp(suffix=".db")
    sqlite3.connect(path).close()
    with contextlib.redirect_stdout(io.StringIO()):
        apply_all(path, str(BASE_DIR / "migrations"))
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

    print("\nRecibir la mascota")
    body = client.get("/visitas/nueva").get_data(as_text=True)
    check("el selector avisa cuando no hay visitas previas",
          "Todav" in body and "primera" in body)

    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1", "2:1"],
                          "price_1_1": "18", "price_2_1": "25"})
    check("visita con dos mascotas en un solo registro", r.status_code == 302,
          r.get_data(as_text=True)[:300])

    body = client.get("/visitas/").get_data(as_text=True)
    check("la visita nace pendiente, no cobrada", "por cobrar" in body, body[:400])
    check("el boton lleva el monto encima", "Cobrar $43.00" in body)
    check("lo pendiente NO suma en lo cobrado del dia", "$0.00" in body)

    body = client.get("/clientes/1").get_data(as_text=True)
    check("una visita pendiente no cuenta como ultima visita de la mascota",
          body.count("Sin visitas registradas") == 2)

    body = client.get("/visitas/nueva/1").get_data(as_text=True)
    check("y tampoco sirve de referencia de precio: sale el de lista",
          'value="15.00"' in body and "\u00faltimo cobro" not in body)

    print("\nCobrar al entregar")
    r = client.post("/visitas/1/cobrar", follow_redirects=True)
    body = r.get_data(as_text=True)
    check("el cobro dice cuanto se factur\u00f3", "cobrado $43.00" in body, body[:400])
    check("ahora si cuenta como cobrado del dia", "$43.00" in body)
    check("y el boton de cobrar desaparece", "Cobrar $43.00" not in body)

    r = client.post("/visitas/1/cobrar", follow_redirects=True)
    check("un segundo toque no vuelve a cobrar",
          "ya no estaba pendiente" in r.get_data(as_text=True))

    r = client.post("/visitas/1/reabrir", follow_redirects=True)
    check("un cobro hecho por error se puede deshacer",
          "pendiente de cobro" in r.get_data(as_text=True))
    r = client.post("/visitas/1/cobrar", follow_redirects=True)
    check("y volver a cobrarse", "cobrado $43.00" in r.get_data(as_text=True))

    body = client.get("/clientes/1").get_data(as_text=True)
    check("cobrada, ya cuenta como ultima visita", "Hace 0" in body)

    body = client.get("/visitas/nueva/1").get_data(as_text=True)
    check("y ya sirve de referencia: sale el ultimo cobro",
          'value="18.00"' in body and "\u00faltimo cobro" in body)

    print("\nSe la llevaron sin atender")
    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:2"], "price_1_2": "5"})
    check("segunda visita recibida", r.status_code == 302)
    body = client.get("/visitas/pendientes").get_data(as_text=True)
    check("aparece en la lista de pendientes", "Cobrar $5.00" in body)

    r = client.post("/visitas/2/cancelar", data={"from": "pending"},
                    follow_redirects=True)
    body = r.get_data(as_text=True)
    check("cerrarla sin cobro", "cerrada sin cobro" in body)
    check("la lista de pendientes queda vacia",
          "No queda nada pendiente" in body)

    body = client.get("/visitas/").get_data(as_text=True)
    check("queda el registro de que vinieron",
          "se retir\u00f3 sin atender" in body)
    check("pero no suma un centavo", "$48.00" not in body)

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
        "INSERT INTO visit (client_id, visit_date, status) "
        "VALUES (1, date('now','-5 hours','-20 days'), 'completed')"
    )
    conn.execute(
        "INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
        "VALUES ((SELECT MAX(id) FROM visit), 1, 1, 1500)"
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


def run_stats(db_path):
    """Fase 3: el resumen, y sobre todo que los huecos se vean."""
    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False

    app = create_app(Cfg)
    client = app.test_client()

    with app.app_context():
        from app.clock import today, week_bounds
        hoy = today()
        lunes, _ = week_bounds(hoy)

    print("\nResumen sin datos")
    body = client.get("/resumen/").get_data(as_text=True)
    check("el resumen carga con la base vacia", "$0.00" in body)
    check("y no inventa una comparacion contra cero",
          "vs." not in body)

    client.post("/clientes/nuevo", data={"name": "Ana Vega", "phone": "60011122"})
    client.post("/clientes/1/mascotas/nueva",
                data={"name": "Rocky", "size": "medium"})
    client.post("/clientes/1/mascotas/nueva",
                data={"name": "Nina", "size": "small"})
    client.post("/clientes/nuevo", data={"name": "Beto Lima", "phone": "60033344"})
    client.post("/clientes/2/mascotas/nueva",
                data={"name": "Kira", "size": "small"})
    client.post("/servicios/nuevo",
                data={"name": "Bano", "price_mode": "any", "price_any": "20"})
    client.post("/servicios/nuevo",
                data={"name": "Corte", "price_mode": "any", "price_any": "70"})

    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1", "1:2", "2:1"],
                          "price_1_1": "20", "price_1_2": "70",
                          "price_2_1": "20", "charge": "1"})
    check("visita de hoy registrada y cobrada de una", r.status_code == 302)
    r = client.post("/visitas/nueva/2",
                    data={"pick": ["3:1"], "price_3_1": "20",
                          "visit_date": lunes, "charge": "1"})
    check("visita del lunes registrada y cobrada", r.status_code == 302)

    print("\nCifras del periodo")
    body = client.get("/resumen/?p=semana").get_data(as_text=True)
    check("suma lo facturado en la semana", "$130.00" in body, body[:200])
    check("cuenta 3 perros atendidos en 2 visitas",
          ">3<" in body and ">2<" in body)
    # Se mira solo la seccion de servicios: arriba hay mensajes flash
    # acumulados que tambien nombran los servicios.
    barras = body[body.index("Qu\u00e9 pesa m\u00e1s"):]
    check("ordena por plata y no por cantidad: corte 1 vez ($70) "
          "gana a bano 3 veces ($60)",
          barras.index("Corte") < barras.index("Bano"))
    check("el promedio por perro es correcto", "$43.33" in body)

    print("\nClientes")
    check("los dos son nuevos esta semana",
          ">2<" in body and "nuevos" in body)
    body_prev = client.get("/resumen/?p=semana_pasada").get_data(as_text=True)
    check("la semana pasada no arrastra los datos de esta",
          "$130.00" not in body_prev)

    print("\nLos huecos se ven")
    # Rango fijo en el pasado: si dependiera de la semana en curso, la
    # prueba daria distinto segun el dia en que se corra.
    with app.app_context():
        from app.clock import shift, weekday_of
        base = shift(hoy, -60)
        fin = shift(base, 6)
        dia_base = weekday_of(base)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO visit (client_id, visit_date, status) "
                 "VALUES (1, ?, 'completed')", (base,))
    conn.execute(
        "INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
        "VALUES ((SELECT MAX(id) FROM visit), 1, 1, 2000)"
    )
    conn.commit()
    conn.close()

    rango = f"/resumen/?desde={base}&hasta={fin}"
    body = client.get(rango).get_data(as_text=True)
    check("marca los 6 dias del rango sin un solo registro",
          "6 d\u00edas sin registrar" in body, body[:300])
    check("y avisa que por eso el total esta incompleto", "incompleto" in body)
    check("el dia que si tiene registro no se marca como hueco",
          short_date_of(app, base, True) not in body)

    futuro = f"/resumen/?desde={hoy}&hasta=" + shift_of(app, hoy, 10)
    body = client.get(futuro).get_data(as_text=True)
    check("un dia que todavia no llega no es un hueco",
          "sin registrar" not in body)

    print("\nEl calendario lo pone el duenio")
    r = client.post("/ajustes/",
                    data={"business_name": "Peluqueria Canina Ana",
                          "working_days": [str(dia_base)],
                          "followup_days": "15"})
    check("guardar ajustes", r.status_code == 302)
    body = client.get(rango).get_data(as_text=True)
    check("al marcar los otros dias como cerrados, los huecos se van",
          "sin registrar" not in body)
    check("el nombre del negocio sale en la cabecera",
          "Peluqueria Canina Ana" in client.get("/").get_data(as_text=True))

    print("\nA quien escribirle")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO client (name, phone) VALUES ('Cira Paz','+50760055566')")
    cira = conn.execute("SELECT id FROM client WHERE name='Cira Paz'").fetchone()[0]
    conn.execute("INSERT INTO pet (client_id, name, size) VALUES (?,'Toby','large')",
                 (cira,))
    toby = conn.execute("SELECT id FROM pet WHERE name='Toby'").fetchone()[0]
    conn.execute("INSERT INTO visit (client_id, visit_date, status) "
                 "VALUES (?, date('now','-5 hours','-40 days'), 'completed')",
                 (cira,))
    visita = conn.execute("SELECT MAX(id) FROM visit").fetchone()[0]
    conn.execute("INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
                 "VALUES (?, ?, 1, 2000)", (visita, toby))
    conn.commit()
    conn.close()

    body = client.get("/resumen/").get_data(as_text=True)
    check("el resumen avisa de quien se atraso", "sin venir" in body)
    body = client.get("/resumen/atrasados").get_data(as_text=True)
    check("la lista nombra al atrasado", "Cira Paz" in body)
    check("con los dias que lleva", "40 d\u00edas" in body)
    check("y el boton de WhatsApp listo", "wa.me/50760055566" in body)
    check("quien vino hoy no aparece en la lista", "Ana Vega" not in body)

    r = client.post("/ajustes/",
                    data={"business_name": "Peluqueria Canina Ana",
                          "working_days": [str(dia_base)], "followup_days": "60"})
    check("subir el plazo a 60 dias", r.status_code == 302)
    body = client.get("/resumen/atrasados").get_data(as_text=True)
    check("con el plazo mas largo ya nadie esta atrasado",
          "Cira Paz" not in body)

    print("\nLo pendiente no infla las cifras")
    r = client.post("/visitas/nueva/1",
                    data={"pick": ["1:1"], "price_1_1": "999"})
    check("visita recibida y sin cobrar", r.status_code == 302)

    # El inicio va primero para consumir el mensaje flash, que tambien
    # nombra el monto y falsearia la comprobacion siguiente.
    body = client.get("/").get_data(as_text=True)
    check("el inicio avisa que hay algo pendiente", "pendiente de cobro" in body)
    check("y hoy todavia no es una alarma", "La m\u00e1s vieja" not in body)

    body = client.get("/resumen/?p=semana").get_data(as_text=True)
    check("no entra en lo facturado del periodo",
          "$130.00" in body and "$999.00" not in body)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO visit (client_id, visit_date, status) "
                 "VALUES (1, date('now','-5 hours','-3 days'), 'pending')")
    conn.execute("INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
                 "VALUES ((SELECT MAX(id) FROM visit), 1, 1, 2000)")
    conn.commit()
    conn.close()

    body = client.get("/").get_data(as_text=True)
    check("una pendiente de otro dia si se marca como alarma",
          "La m\u00e1s vieja" in body)
    body = client.get("/visitas/pendientes").get_data(as_text=True)
    check("la lista de pendientes las junta sin importar el dia",
          body.count("Cobrar ") == 2)

    print("\nAjustes se defienden")
    r = client.post("/ajustes/", data={"working_days": [], "followup_days": "15"})
    check("no deja cerrar los siete dias", r.status_code == 400)
    r = client.post("/ajustes/", data={"working_days": ["0"], "followup_days": "0"})
    check("no acepta un plazo de cero dias", r.status_code == 400)
    body = client.get("/resumen/?desde=basura&hasta=peor").get_data(as_text=True)
    check("un rango invalido en la URL cae a la semana en curso",
          "Esta semana" in body)


def short_date_of(app, iso, weekday=False):
    with app.app_context():
        from app.labels import short_date
        return short_date(iso, weekday)


def shift_of(app, iso, days):
    with app.app_context():
        from app.clock import shift
        return shift(iso, days)


if __name__ == "__main__":
    for runner in (run_flow, run_csrf, run_stats):
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
