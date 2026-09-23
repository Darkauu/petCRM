"""Prueba de humo de extremo a extremo.

Levanta la aplicacion contra una base temporal recien migrada y recorre
los flujos de la Fase 1. No usa pytest a proposito: se corre igual que
los demas scripts del proyecto, sin instalar nada extra.

Uso:
    python scripts/smoke.py
"""
import contextlib
import io
import logging
import os
import pathlib
import re
import shutil
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


def sign_in(client):
    """Crea la cuenta del duenio y deja la sesion abierta."""
    client.post("/crear-cuenta", data={
        "display_name": "Duenio", "email": "duenio@ejemplo.com",
        "password": "clave-de-prueba", "password2": "clave-de-prueba",
    })
    return client


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
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())

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

    # Se teclea como se quiera; se ve siempre igual. Antes la misma
    # lista mostraba '61234567', '6123-4567' y '+507 6123 4567' segun
    # como lo hubiera escrito cada quien.
    client.post("/clientes/nuevo", data={"name": "Beto Lima", "phone": "60099887"})
    for ruta in ("/clientes/2", "/clientes/"):
        body = client.get(ruta).get_data(as_text=True)
        # Sin los href: 'tel:' y 'wa.me' llevan los digitos pelados a
        # proposito, y ahi si tienen que estar.
        visible = re.sub(r'href="[^"]*"', "", body)
        check(f"el telefono se ve como 6009-9887 en {ruta}",
              "6009-9887" in visible and "60099887" not in visible,
              visible[:400])
    body = client.get("/clientes/2/editar").get_data(as_text=True)
    check("y el formulario tambien lo abre en ese formato",
          'value="6009-9887"' in body, body[body.find('name="phone"') - 40:][:220])

    r = client.post("/clientes/2/editar",
                    data={"name": "Beto Lima", "phone": "no es un numero"})
    check("un telefono ilegible se devuelve tal cual para corregirlo",
          r.status_code == 400 and "no es un numero" in r.get_data(as_text=True))

    r = client.post("/clientes/1/mascotas/nueva",
                    data={"name": "Toby", "size": "small",
                          "breed": "Schnauzer", "temperament": "muerde al secar"})
    check("alta de mascota", r.status_code == 302)
    r = client.post("/clientes/1/mascotas/nueva",
                    data={"name": "Luna", "size": "large", "and_another": "1"})
    check("'guardar y agregar otra' regresa al formulario",
          r.status_code == 302 and "/mascotas/nueva" in r.headers["Location"])
    # Una mascota sin talla SI se guarda: del cuaderno entran asi, y
    # una talla inventada cobra mal el proximo bano. El hueco tiene
    # que quedar a la vista, que es lo que se comprueba abajo.
    r = client.post("/clientes/1/mascotas/nueva", data={"name": "SinTalla"})
    check("una mascota sin tamanio se guarda igual", r.status_code == 302,
          r.get_data(as_text=True)[:200])
    body = client.get("/clientes/1").get_data(as_text=True)
    check("pero el hueco queda escrito en la ficha",
          "falta el tama" in body.lower())
    check("y una talla inventada sigue sin colarse",
          client.post("/clientes/1/mascotas/nueva",
                      data={"name": "X", "size": "gigante"}).status_code == 400)

    body = client.get("/clientes/1").get_data(as_text=True)
    check("la ficha lista las dos mascotas", "Toby" in body and "Luna" in body)
    check("la ficha avisa que no hay visitas registradas",
          body.count("Sin visitas registradas") == 3)
    check("la ficha muestra el manejo del perro", "muerde al secar" in body)

    print("\nPanel de clientes: a quien escribirle, sin entrar a nadie")
    body = client.get("/clientes/").get_data(as_text=True)
    check("las pestanias de filtro estan",
          "Por escribir" in body and "Sin visitas" in body
          and "Perros grandes" in body)
    check("y cada una trae su numero", 'class="chip-n"' in body)

    # Toby vino hace 20 dias (insertado mas abajo no; aqui aun no hay
    # visitas), asi que de momento todos caen en "sin visitas".
    grupos = {
        "": client.get("/clientes/").get_data(as_text=True),
        "sin-visitas": client.get("/clientes/?f=sin-visitas").get_data(as_text=True),
        "pequenos": client.get("/clientes/?f=pequenos").get_data(as_text=True),
        "grandes": client.get("/clientes/?f=grandes").get_data(as_text=True),
    }
    check("sin visitas: sale Marta, que no tiene ninguna",
          "Marta Rios" in grupos["sin-visitas"])
    check("perros pequenios: Toby es pequenio, asi que sale su duenia",
          "Marta Rios" in grupos["pequenos"])
    check("perros grandes: Luna es grande, tambien sale",
          "Marta Rios" in grupos["grandes"])
    check("un filtro inventado no rompe: cae a todos",
          "Marta Rios" in
          client.get("/clientes/?f=inventado").get_data(as_text=True))

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
                    data={"pet": ["1", "2"], "pick": ["1:1", "2:1"],
                          "price_1_1": "18", "price_2_1": "25"})
    check("visita con dos mascotas en un solo registro", r.status_code == 302,
          r.get_data(as_text=True)[:300])

    body = client.get("/visitas/").get_data(as_text=True)
    check("la visita nace pendiente, no cobrada", "por cobrar" in body, body[:400])
    check("el boton lleva el monto encima", "Cobrar $43.00" in body)
    check("lo pendiente NO suma en lo cobrado del dia", "$0.00" in body)

    body = client.get("/clientes/1").get_data(as_text=True)
    check("una visita pendiente no cuenta como ultima visita de la mascota",
          body.count("Sin visitas registradas") == 3)

    body = client.get("/visitas/nueva/1").get_data(as_text=True)
    check("y tampoco sirve de referencia de precio: sale el de lista",
          'value="15.00"' in body and "\u00faltimo cobro" not in body)

    print("\nCobrar al entregar")
    r = client.post("/visitas/1/cobrar", follow_redirects=True)
    body = r.get_data(as_text=True)
    check("el cobro dice cuanto se factur\u00f3", "cobrado $43.00" in body, body[:400])
    check("ahora si cuenta como cobrado del dia", "$43.00" in body)
    check("y el boton de cobrar desaparece", "Cobrar $43.00" not in body)

    # Cobrando desde el inicio se vuelve a la seccion de pendientes, no
    # al tope: la lista vive abajo y con cada cobro habia que bajar otra
    # vez. El ancla lo resuelve sin JS; el JS lo afina al pixel.
    client.post("/visitas/1/reabrir")
    r = client.post("/visitas/1/cobrar", data={"from": "home"})
    check("cobrar desde el inicio vuelve a la seccion, no al tope",
          r.status_code == 302 and r.headers["Location"].endswith("#pendientes"),
          r.headers.get("Location"))
    body = client.get("/").get_data(as_text=True)
    check("y esa seccion existe para que el ancla caiga en algo",
          'id="pendientes"' in body)

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
                    data={"pet": ["1"], "pick": ["1:2"], "price_1_2": "5"})
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
                    data={"pet": ["999"], "pick": ["999:1"], "price_999_1": "10"})
    check("una mascota ajena se ignora y no se guarda nada",
          r.status_code == 400
          and "Elige la mascota" in r.get_data(as_text=True))
    r = client.post("/visitas/nueva/1",
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "10",
                          "visit_date": "2099-01-01"})
    check("una fecha futura se rechaza",
          r.status_code == 400 and "futuro" in r.get_data(as_text=True))
    r = client.post("/visitas/nueva/1",
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "no es plata"})
    body = r.get_data(as_text=True)
    check("un precio ilegible se rechaza", r.status_code == 400)
    check("el servicio marcado no se pierde al volver",
          'value="1:1"' in body and "checked" in body)
    check("y se devuelve lo que se escribio, no otro numero",
          "no es plata" in body and 'value="18.00"' not in body)

    print("\nCorregir una visita")
    r = client.post("/visitas/1/editar",
                    data={"pet": ["1", "2"], "pick": ["1:1", "2:1"],
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
          body.count("Sin visitas registradas") == 3)

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
    check("y la ficha dice cuanto ha dejado en total",
          "cobrado en total" in body and "Cliente desde" in body)

    # Lo que pidio el duenio: verlo desde el panel, sin entrar a nadie.
    lista = client.get("/clientes/?f=escribir").get_data(as_text=True)
    check("el panel de clientes ya trae el boton de WhatsApp",
          "wa.me" in lista and "Escribirle" in lista)
    # 'btn-sm btn-wa' es el boton de la FILA. El de arriba, que lleva a
    # escribirle a todo el grupo, es otra clase y no debe contarse aqui.
    check("y solo para quien se paso del plazo",
          lista.count("btn-sm btn-wa") == 1, lista.count("btn-sm btn-wa"))
    check("la mascota sin visitas sigue marcada como hueco",
          "Sin visitas registradas" in body)

    print("\nInicio")
    body = client.get("/").get_data(as_text=True)
    check("el inicio ofrece registrar visita como accion principal",
          "Registrar visita" in body)

def run_interface(db_path):
    """Lo que el servidor si puede comprobar de la interfaz.

    El comportamiento en el navegador (que el dialogo sea el de la app y
    que el buscador responda al escribir) lo cubre scripts/ui_check.py,
    que necesita un navegador y por eso no entra al CI.
    """
    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    client = sign_in(create_app(Cfg).test_client())
    client.post("/clientes/nuevo", data={"name": "Marta Rios", "phone": "61234567"})
    client.post("/clientes/1/mascotas/nueva", data={"name": "Toby", "size": "small"})
    client.post("/clientes/nuevo", data={"name": "Beto Lima", "phone": "60099887"})

    print("\nBuscador que responde al escribir")
    data = client.get("/clientes/buscar?q=tob").get_json()
    check("encuentra al duenio por el nombre de su perro",
          len(data["rows"]) == 1 and data["rows"][0]["name"] == "Marta Rios", data)
    check("trae las mascotas para distinguir homonimos",
          "Toby" in data["rows"][0]["sub"])
    check("busca por telefono",
          client.get("/clientes/buscar?q=6009").get_json()["rows"][0]["name"]
          == "Beto Lima")
    check("una busqueda vacia no devuelve el listin completo",
          client.get("/clientes/buscar?q=").get_json()["rows"] == [])
    check("sin coincidencias devuelve lista vacia y no un error",
          client.get("/clientes/buscar?q=zzzz").get_json()["rows"] == [])

    # Un solo endpoint; 'destino' decide a donde lleva el resultado.
    check("por defecto lleva a la ficha del cliente",
          data["rows"][0]["url"] == "/clientes/1")
    ida = client.get("/clientes/buscar?q=tob&destino=visita").get_json()
    check("y con destino=visita, a registrarle una visita",
          ida["rows"][0]["url"] == "/visitas/nueva/1")
    raro = client.get("/clientes/buscar?q=tob&destino=inventado").get_json()
    check("un destino desconocido cae a la ficha, no revienta",
          raro["rows"][0]["url"] == "/clientes/1")

    body = client.get("/visitas/nueva").get_data(as_text=True)
    check("registrar visita apunta al buscador",
          "data-search-url=" in body and "destino=visita" in body)
    check("el formulario sigue existiendo para cuando no hay JS",
          'action="/visitas/nueva"' in body and "Buscar</button>" in body)

    body = client.get("/clientes/").get_data(as_text=True)
    check("la lista de clientes usa el mismo buscador",
          'data-search-url="/clientes/buscar"' in body
          and 'id="search-results"' in body)
    check("y ahi tambien queda el formulario de siempre",
          'action="/clientes/"' in body and "Buscar</button>" in body)

    print("\nCabecera")
    body = client.get("/clientes/1").get_data(as_text=True)
    check("volver es una flecha, no la palabra escrita",
          ">Volver<" not in body and "<svg" in body.split("<main")[0])
    check("y conserva su nombre para quien no ve el icono",
          'aria-label="Volver"' in body)
    check("con su propio fondo, para que no se pierda en la cabecera",
          'class="back back-icon"' in body)
    check("el boton de dia y noche esta en toda pantalla",
          "data-tema" in body and "data-tema" in
          client.get("/resumen/").get_data(as_text=True))

    r = client.get("/resumen/")
    body = r.get_data(as_text=True)
    check("el resumen dice 'Demanda de servicio'", "Demanda de servicio" in body)
    check("y ya no dice 'Qu\u00e9 pesa m\u00e1s'", "pesa m" not in body)

    print("\nEl script del tema no abre la puerta a otros")
    import re as _re
    csp = r.headers["Content-Security-Policy"]
    nonce_csp = _re.search(r"nonce-([\w-]+)", csp)
    nonce_html = _re.search(r'<script nonce="([\w-]+)"', body)
    check("el script en linea va firmado con un nonce",
          bool(nonce_csp) and bool(nonce_html)
          and nonce_csp.group(1) == nonce_html.group(1))
    otro = _re.search(r"nonce-([\w-]+)",
                      client.get("/resumen/").headers["Content-Security-Policy"])
    check("y el nonce cambia en cada peticion, o no serviria de nada",
          otro.group(1) != nonce_csp.group(1))
    check("no se permitieron scripts en linea en general",
          "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0])

    print("\nConfirmacion propia, no la del navegador")
    check("el dialogo viene en el layout", 'id="confirm-dialog"' in body)
    check("y por lo tanto en cualquier pantalla",
          'id="confirm-dialog"' in client.get("/").get_data(as_text=True))

    body = client.get("/clientes/1/editar").get_data(as_text=True)
    check("cada accion destructiva trae su mensaje", "data-confirm=" in body)
    check("y el nombre de lo que va a pasar", 'data-confirm-ok="Archivar"' in body)

    js = (BASE_DIR / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    check("el confirm del navegador queda solo como ultimo recurso",
          js.count("window.confirm(") == 1 and "showModal" in js,
          f'{js.count("window.confirm(")} llamadas')
    check("los resultados se pintan con textContent y no con innerHTML",
          "innerHTML = \"\"" in js and "innerHTML =" not in js.replace(
              'innerHTML = ""', ""))


def run_auth(db_path):
    """Control de acceso: nada alcanzable sin sesion."""
    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False
        AUTO_BACKUP = False

    client = create_app(Cfg).test_client()

    print("\nSin ninguna cuenta creada")
    for url in ("/", "/clientes/", "/resumen/", "/visitas/nueva", "/ajustes/"):
        r = client.get(url)
        if r.status_code != 302 or "/crear-cuenta" not in r.headers["Location"]:
            check(f"{url} lleva a crear la cuenta", False,
                  f"{r.status_code} {r.headers.get('Location')}")
            break
    else:
        check("ninguna pantalla se abre; todas llevan a crear la cuenta", True)
    check("health sigue publico, para poder vigilar desde afuera",
          client.get("/health").status_code == 200)

    print("\nCrear la cuenta del duenio")
    r = client.post("/crear-cuenta", data={
        "display_name": "Alejandro", "email": "duenio@ejemplo.com",
        "password": "corta", "password2": "corta"})
    check("una contrasenia corta se rechaza",
          r.status_code == 400 and "al menos 8" in r.get_data(as_text=True))
    r = client.post("/crear-cuenta", data={
        "display_name": "Alejandro", "email": "duenio@ejemplo.com",
        "password": "clave-de-prueba", "password2": "otra-distinta"})
    check("dos contrasenias distintas se rechazan",
          r.status_code == 400 and "no coinciden" in r.get_data(as_text=True))
    larga = "a" * 5000
    r = client.post("/crear-cuenta", data={
        "display_name": "Alejandro", "email": "duenio@ejemplo.com",
        "password": larga, "password2": larga})
    check("una contrasenia absurdamente larga se rechaza en vez de "
          "quemar CPU en el hash",
          r.status_code == 400 and "ximo 200" in r.get_data(as_text=True))

    r = client.post("/crear-cuenta", data={
        "display_name": "Alejandro", "email": "duenio@ejemplo.com",
        "password": "clave-de-prueba", "password2": "clave-de-prueba"})
    check("cuenta creada y sesion abierta de una",
          r.status_code == 302 and client.get("/").status_code == 200)
    check("la pantalla de crear cuenta ya no existe",
          client.get("/crear-cuenta").headers.get("Location", "").endswith("/entrar"))

    with create_app(Cfg).app_context():
        from app.repos import users
        row = users.get_by_email("duenio@ejemplo.com")
        check("la contrasenia no se guarda en claro",
              "clave-de-prueba" not in row["password_hash"])

    print("\nSalir y volver a entrar")
    check("salir cierra la sesion", client.post("/salir").status_code == 302)
    r = client.get("/clientes/")
    check("y las pantallas vuelven a pedir sesion",
          r.status_code == 302 and "/entrar" in r.headers["Location"])

    r = client.post("/entrar", data={"email": "duenio@ejemplo.com",
                                     "password": "equivocada"})
    mal_clave = r.get_data(as_text=True)
    check("contrasenia equivocada no entra", r.status_code == 401)
    r = client.post("/entrar", data={"email": "nadie@ejemplo.com",
                                     "password": "loquesea"})
    check("un correo que no existe da el MISMO mensaje: no se revela cual fallo",
          "Correo o contrase" in mal_clave and "Correo o contrase" in r.get_data(as_text=True))

    r = client.post("/entrar", data={"email": "duenio@ejemplo.com",
                                     "password": "clave-de-prueba"})
    check("con la contrasenia correcta si entra",
          r.status_code == 302 and client.get("/").status_code == 200)

    print("\nA donde manda despues de entrar")
    def sesion_limpia():
        c = create_app(Cfg).test_client()
        c.post("/entrar", data={"email": "duenio@ejemplo.com",
                                "password": "clave-de-prueba"})
        return c

    # Sin esto, un enlace /entrar?next=https://sitio-falso manda al
    # duenio a una copia justo despues de entrar, que es cuando menos
    # sospecha.
    for destino in ("https://sitio-falso.example/robar",
                    "//sitio-falso.example/robar",
                    "/\\sitio-falso.example",
                    "javascript:alert(1)"):
        c = create_app(Cfg).test_client()
        r = c.post(f"/entrar?next={destino}",
                   data={"email": "duenio@ejemplo.com",
                         "password": "clave-de-prueba"})
        if r.headers.get("Location") != "/":
            check(f"se bloquea el salto fuera del sitio ({destino})", False,
                  r.headers.get("Location"))
            break
    else:
        check("un destino fuera del sitio se ignora y se va al inicio", True)

    c = create_app(Cfg).test_client()
    r = c.post("/entrar?next=/clientes/",
               data={"email": "duenio@ejemplo.com", "password": "clave-de-prueba"})
    check("pero un destino del propio sitio si se respeta",
          r.headers.get("Location") == "/clientes/", r.headers.get("Location"))

    print("\nSalir de verdad")
    c = sesion_limpia()
    check("entro", c.get("/").status_code == 200)
    c.post("/salir")
    r = c.get("/")
    check("tras salir no se vuelve a entrar solo con la cookie de recordarme",
          r.status_code == 302 and "/entrar" in r.headers["Location"],
          f"{r.status_code} {r.headers.get('Location')}")

    print("\nInyeccion SQL")
    c = sesion_limpia()
    veneno = "Robert'); DROP TABLE client;--"
    r = c.post("/clientes/nuevo", data={"name": veneno, "phone": "6555-1234"})
    check("un nombre con SQL adentro se guarda, no se ejecuta",
          r.status_code == 302, r.status_code)
    conn = sqlite3.connect(db_path)
    tablas = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    check("la tabla client sigue existiendo", "client" in tablas)
    guardado = conn.execute(
        "SELECT name FROM client ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    check("y el texto quedo tal cual, literal", guardado == veneno, guardado)

    body = c.get("/clientes/?q=" + "%27+OR+1%3D1--").get_data(as_text=True)
    check("una busqueda con comilla no rompe ni devuelve todo",
          "Nadie coincide" in body or "DROP" in body, body[:200])

    # Guardia estatica. Buscar cadenas sospechosas dentro del SQL es
    # fragil; la invariante que de verdad sostiene todo es otra: la capa
    # de datos no conoce la peticion. Todo lo que viene de afuera entra
    # como parametro de una funcion, y de ahi solo sale por un '?'.
    import re as _re
    usa_peticion = _re.compile(r"\brequest\.|^\s*from flask import .*\brequest\b",
                               _re.MULTILINE)
    culpables = []
    for archivo in sorted((BASE_DIR / "app" / "repos").glob("*.py")):
        if usa_peticion.search(archivo.read_text(encoding="utf-8")):
            culpables.append(archivo.name)
    check("ningun modulo de datos toca la peticion: lo de afuera solo "
          "entra como parametro", not culpables, culpables)

    print("\nFreno a los intentos repetidos")
    client.post("/salir")
    for _ in range(8):
        client.post("/entrar", data={"email": "duenio@ejemplo.com",
                                     "password": "probando"})
    r = client.post("/entrar", data={"email": "duenio@ejemplo.com",
                                     "password": "probando"})
    check("tras 8 fallos se frena", r.status_code == 429)
    check("y lo dice sin revelar nada mas",
          "Demasiados intentos" in r.get_data(as_text=True))
    r = client.post("/entrar", data={"email": "duenio@ejemplo.com",
                                     "password": "clave-de-prueba"})
    check("el freno tambien aplica a la contrasenia correcta",
          r.status_code == 429)

    print("\nCabeceras")
    headers = client.get("/entrar").headers
    check("se declara de donde puede venir el contenido",
          "default-src 'self'" in headers.get("Content-Security-Policy", ""))
    check("no se adivina el tipo de archivo",
          headers.get("X-Content-Type-Options") == "nosniff")
    check("no se puede meter en un iframe ajeno",
          headers.get("X-Frame-Options") == "DENY")


def run_backups(_unused):
    """Respaldos que no dependen de que alguien se acuerde."""
    from datetime import datetime, timedelta

    work = tempfile.mkdtemp()
    db = os.path.join(work, "petcrm.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        (BASE_DIR / "migrations" / "001_initial.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO client (name, phone) VALUES ('Marta','+50761234567')")
    conn.commit()
    conn.close()

    from app import backups

    print("\nRespaldo diario")
    first = backups.ensure_daily(db)
    check("se crea el del dia", first["action"] == "created", first)
    check("y queda junto a la base, en respaldos/",
          os.path.isdir(os.path.join(work, "respaldos")))

    again = backups.ensure_daily(db)
    check("llamarlo otra vez el mismo dia no duplica",
          again["action"] == "ok" and
          len(os.listdir(os.path.join(work, "respaldos"))) == 1)

    copia = sqlite3.connect(first["backup"])
    check("el respaldo es una base de verdad, con los datos dentro",
          copia.execute("SELECT name FROM client").fetchone()[0] == "Marta")
    copia.close()

    print("\nLimpieza por antiguedad")
    folder = pathlib.Path(work) / "respaldos"
    # Respaldos viejos, y uno previo a una migracion que NO debe borrarse.
    for days in range(1, 25):
        day = datetime.now() - timedelta(days=days)
        (folder / backups.daily_name(db, day)).write_bytes(b"x")
    (folder / "petcrm-v2-20260101-000000.db").write_bytes(b"x")

    removed = backups.prune(db, keep=14)
    quedan = sorted(p.name for p in folder.glob("*.db"))
    diarios = [n for n in quedan if "-diario-" in n]
    check("deja los 14 mas recientes", len(diarios) == 14, diarios)
    check("borra el resto", len(removed) == 11, len(removed))
    check("y NO toca el respaldo previo a una migracion",
          "petcrm-v2-20260101-000000.db" in quedan)

    print("\nRespaldo forzado a mano")
    import subprocess
    r = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "backup.py"),
         "--db", db, "--forzar"],
        capture_output=True, text=True)
    check("scripts/backup.py --forzar crea uno aparte",
          r.returncode == 0 and any("-manual-" in n for n in os.listdir(folder)),
          r.stdout + r.stderr)

    print("\nProduccion")
    from app.config import ProductionConfig
    import os as _os
    guardado = _os.environ.get("SECRET_KEY")
    try:
        from app import config as config_module
        config_module.Config.SECRET_KEY = None
        try:
            ProductionConfig()
            check("sin SECRET_KEY no arranca en produccion", False,
                  "arranco igual")
        except RuntimeError:
            check("sin SECRET_KEY no arranca en produccion: "
                  "no se despliega inseguro por descuido", True)

        config_module.Config.SECRET_KEY = "x" * 40
        cfg = ProductionConfig()
        check("en produccion la cookie de sesion va solo por HTTPS",
              cfg.SESSION_COOKIE_SECURE is True)
        check("y no es alcanzable desde JavaScript",
              cfg.SESSION_COOKIE_HTTPONLY is True)
    finally:
        config_module.Config.SECRET_KEY = guardado

    logs = tempfile.mkdtemp()

    class Prod(DevelopmentConfig):
        DB_PATH = db
        DEBUG = False           # ni debug ni testing: se escribe el registro
        TESTING = False
        LOG_DIR = logs
        AUTO_BACKUP = False
        SECRET_KEY = "x" * 40

    app = create_app(Prod)
    app.logger.error("prueba de registro")
    escrito = pathlib.Path(logs, "app.log").read_text(encoding="utf-8")
    check("fuera de desarrollo, lo que falla queda escrito en un archivo",
          "prueba de registro" in escrito, escrito[:200])
    check("con fecha y lugar, para poder mandarlo",
          "ERROR" in escrito and ".py:" in escrito)
    shutil.rmtree(logs, ignore_errors=True)

    shutil.rmtree(work, ignore_errors=True)


def run_auto_migrate(_unused):
    """La base se pone al dia sola al arrancar, y respaldada."""
    work = tempfile.mkdtemp()
    db = os.path.join(work, "petcrm.db")

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = WAL")
    for name in ("001_initial.sql", "002_resumen.sql"):
        conn.executescript(
            (BASE_DIR / "migrations" / name).read_text(encoding="utf-8"))
    conn.execute("INSERT INTO client (name, phone) VALUES ('Marta','+50761234567')")
    conn.execute("INSERT INTO pet (client_id, name, size) VALUES (1,'Toby','small')")
    conn.execute("INSERT INTO service (name) VALUES ('Bano')")
    conn.execute("INSERT INTO service_price (service_id, size, price_cents) "
                 "VALUES (1,'any',2000)")
    conn.execute("INSERT INTO visit (client_id, visit_date) VALUES (1,'2026-08-01')")
    conn.execute("INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents) "
                 "VALUES (1,1,1,2000)")
    conn.commit()
    conn.close()

    print("\nLa base se migra sola al arrancar")

    class Cfg(DevelopmentConfig):
        DB_PATH = db
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False     # aqui solo interesa el respaldo de migracion

    logging.disable(logging.CRITICAL)
    app = create_app(Cfg)
    logging.disable(logging.NOTSET)
    client = sign_in(app.test_client())

    conn = sqlite3.connect(db)
    from app.schema import expected_version
    ultima = expected_version(str(BASE_DIR / "migrations"))
    check("la version sube sola",
          conn.execute("PRAGMA user_version").fetchone()[0] == ultima, ultima)
    check("el cliente sigue ahi",
          conn.execute("SELECT name FROM client").fetchone()[0] == "Marta")
    check("la visita historica se conserva con su estado",
          conn.execute("SELECT status FROM visit").fetchone()[0] == "completed")
    check("y su linea de cobro",
          conn.execute("SELECT price_cents FROM visit_service").fetchone()[0] == 2000)
    conn.close()

    respaldos = os.listdir(os.path.join(work, "respaldos"))
    check("se respaldo antes de tocar nada", len(respaldos) == 1, respaldos)
    check("el respaldo dice de que version venia", "-v2-" in respaldos[0])

    r = client.post("/visitas/nueva/1",
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "20"})
    check("registrar una visita ya funciona, sin correr ningun comando",
          r.status_code == 302, r.get_data(as_text=True)[:200])
    check("health responde ok", client.get("/health").get_json()["status"] == "ok")

    print("\nUna migracion que falla no deja la base a medias")
    migs = tempfile.mkdtemp()
    for name in ("001_initial.sql", "002_resumen.sql", "003_cobro.sql"):
        shutil.copy(BASE_DIR / "migrations" / name, migs)
    # Crea algo y despues se rompe: sin rollback quedaria la tabla suelta.
    with open(os.path.join(migs, "004_rota.sql"), "w") as handle:
        handle.write("CREATE TABLE prueba (id INTEGER);\n"
                     "INSERT INTO tabla_que_no_existe (x) VALUES (1);\n"
                     "PRAGMA user_version = 4;\n")

    work2 = tempfile.mkdtemp()
    db2 = os.path.join(work2, "petcrm.db")
    conn = sqlite3.connect(db2)
    for name in ("001_initial.sql", "002_resumen.sql"):
        conn.executescript(
            (BASE_DIR / "migrations" / name).read_text(encoding="utf-8"))
    conn.execute("INSERT INTO client (name, phone) VALUES ('Marta','+50761234567')")
    conn.commit()
    conn.close()

    class Broken(DevelopmentConfig):
        DB_PATH = db2
        MIGRATIONS_DIR = migs
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    logging.disable(logging.CRITICAL)
    app = create_app(Broken)
    logging.disable(logging.NOTSET)

    conn = sqlite3.connect(db2)
    check("la base vuelve a la version que tenia",
          conn.execute("PRAGMA user_version").fetchone()[0] == 2)
    check("los datos siguen intactos",
          conn.execute("SELECT name FROM client").fetchone()[0] == "Marta")
    check("no queda nada a medio crear",
          conn.execute("SELECT COUNT(*) FROM sqlite_master "
                       "WHERE name='prueba'").fetchone()[0] == 0)
    conn.close()

    body = app.test_client().get("/").get_data(as_text=True)
    check("la pantalla explica que no se pudo",
          "No se pudo actualizar la base sola" in body)
    check("nombra la migracion que fallo", "004_rota.sql" in body)
    check("y dice que los datos quedaron como estaban", "como estaban" in body)

    for folder in (work, work2, migs):
        shutil.rmtree(folder, ignore_errors=True)


def run_seed(_unused):
    """scripts/seed.py: datos para ver el sistema andando, sin hacer danio."""
    import subprocess

    work = tempfile.mkdtemp()
    db = os.path.join(work, "petcrm.db")
    entorno = dict(os.environ, DB_PATH=db, AUTO_BACKUP="0")

    def sembrar(*extra):
        return subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "seed.py"), *extra],
            cwd=str(BASE_DIR), env=entorno, capture_output=True, text=True)

    subprocess.run([sys.executable, str(BASE_DIR / "scripts" / "init_db.py")],
                   cwd=str(BASE_DIR), env=entorno, capture_output=True)

    print("\nSembrar datos de prueba")
    r = sembrar("--telefono", "6123-4567")
    check("corre sin errores", r.returncode == 0, r.stderr[-400:])
    check("deja lista la cuenta para entrar",
          "prueba@petcrm.local" in r.stdout and "clave" in r.stdout)
    check("y dice como llegar al boton de WhatsApp",
          "Escribirle" in r.stdout and "6123-4567" in r.stdout)

    class Cfg(DevelopmentConfig):
        DB_PATH = db
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = app.test_client()
    r = client.post("/entrar", data={"email": "prueba@petcrm.local",
                                     "password": "prueba-de-desarrollo"})
    check("se puede entrar con esa cuenta, sin registrarse a mano",
          r.status_code == 302 and client.get("/").status_code == 200)

    body = client.get("/resumen/atrasados").get_data(as_text=True)
    check("hay tres atrasados", body.count("btn-wa") == 3, body.count("btn-wa"))
    check("Ana Vega va de primera, la mas atrasada",
          body.index("Ana Vega") < body.index("Beto Lima"))
    check("Cira Paz NO sale: vino hace 4 dias", "Cira Paz" not in body)
    check("el enlace de WhatsApp lleva el numero internacional",
          "wa.me/50761234567" in body)

    body = client.get("/").get_data(as_text=True)
    check("y hay una visita pendiente de cobro, para ver ese flujo",
          "Pendientes de cobro" in body and "Elsa Mora" in body, body[-1200:])
    check("el inicio la lista con la hora en que se recibio",
          re.search(r"Elsa Mora.{0,600}?\d\d:\d\d", body, re.S) is not None)

    print("\nY no hace danio donde no debe")
    r = sembrar()
    salida = r.stdout + r.stderr
    check("se niega a sembrar sobre una base con clientes",
          r.returncode != 0 and "ya tiene" in salida)
    check("y explica que --force NO borra lo ajeno, que es lo que asusta",
          "sin tocar los tuyos" in salida and "quedan como estan" in salida)

    with app.app_context():
        from werkzeug.security import generate_password_hash
        from app.database import get_db
        from app.repos import users
        users.create("real@ejemplo.com", generate_password_hash("clave-real"),
                     "Duenio real")
        get_db().commit()

    r = sembrar("--force")
    check("con --force vuelve a sembrar sin reventar", r.returncode == 0,
          r.stderr[-400:])
    check("reemplaza lo suyo en vez de duplicarlo",
          "se reemplazaron 5" in r.stdout)

    with create_app(Cfg).app_context():
        from werkzeug.security import check_password_hash
        from app.repos import clients as repo_clients, users as repo_users
        check("no quedaron clientes duplicados",
              repo_clients.count_active() == 5, repo_clients.count_active())
        real = repo_users.get_by_email("real@ejemplo.com")
        check("y NO toca una cuenta que ya existia",
              real is not None
              and check_password_hash(real["password_hash"], "clave-real"))

    print("\nSi un telefono de prueba ya es de alguien")
    work2 = tempfile.mkdtemp()
    db2 = os.path.join(work2, "petcrm.db")
    entorno2 = dict(os.environ, DB_PATH=db2, AUTO_BACKUP="0")
    subprocess.run([sys.executable, str(BASE_DIR / "scripts" / "init_db.py")],
                   cwd=str(BASE_DIR), env=entorno2, capture_output=True)

    class Otra(DevelopmentConfig):
        DB_PATH = db2
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    with create_app(Otra).app_context():
        from app.database import get_db
        from app.repos import clients as rc
        rc.create({"name": "Donia Marta", "phone": "+50760334455",
                   "phone_display": "6033-4455", "document": None,
                   "email": None, "address": None, "notes": None})
        get_db().commit()

    r = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "seed.py"), "--force"],
        cwd=str(BASE_DIR), env=entorno2, capture_output=True, text=True)
    check("no revienta contra el indice unico", r.returncode == 0,
          r.stderr[-300:])
    check("dice cual se salto y de quien es ese numero",
          "se omite Beto Lima" in r.stdout and "Donia Marta" in r.stdout,
          r.stdout)
    check("y siembra los demas igual: mejor incompleto que nada",
          "Ana Vega" in r.stdout and "Elsa Mora" in r.stdout)

    with create_app(Otra).app_context():
        from app.repos import clients as rc2
        check("queda el real mas los cuatro que si entraron",
              rc2.count_active() == 5, rc2.count_active())

    shutil.rmtree(work, ignore_errors=True)
    shutil.rmtree(work2, ignore_errors=True)


def run_schema_guard(_unused):
    """Codigo y base desalineados: tiene que verse, no reventar.

    Arma sus propias bases a proposito, cada una en una version distinta.
    """
    def app_on(path):
        class Cfg(DevelopmentConfig):
            DB_PATH = path
            TESTING = True
            WTF_CSRF_ENABLED = False
            AUTO_MIGRATE = False        # se prueba la guardia, no el arreglo
            AUTO_BACKUP = False
        return create_app(Cfg).test_client()

    print("\nBase sin crear")
    empty = tempfile.mktemp(suffix=".db")
    sqlite3.connect(empty).close()
    client = app_on(empty)
    body = client.get("/").get_data(as_text=True)
    check("no deja entrar", client.get("/").status_code == 503)
    check("dice que la base no esta creada", "no est\u00e1 creada" in body)
    check("y da el comando exacto", "scripts/init_db.py" in body)

    print("\nBase atrasada respecto al codigo")
    old = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(old)
    for name in ("001_initial.sql", "002_resumen.sql"):
        conn.executescript(
            (BASE_DIR / "migrations" / name).read_text(encoding="utf-8"))
    conn.commit()
    conn.close()

    client = app_on(old)
    r = client.get("/visitas/nueva")
    body = r.get_data(as_text=True)
    check("corta el paso con 503", r.status_code == 503)
    check("dice que la base esta desactualizada", "desactualizada" in body)
    check("nombra las dos versiones", "3" in body and "2" in body)
    check("da el comando exacto", "scripts/migrate.py" in body)
    check("y promete que los datos no se tocan", "no se tocan" in body)

    # Lo que antes reventaba con sqlite3.IntegrityError a media faena.
    r = client.post("/visitas/nueva/1",
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "20"})
    check("registrar una visita ya no revienta con un error de SQLite",
          r.status_code == 503)

    r = client.get("/health")
    check("health avisa del desajuste en vez de decir ok",
          r.status_code == 503 and r.get_json()["status"] == "schema_mismatch",
          r.get_json())
    check("los estilos siguen sirviendose, para que el aviso se lea",
          client.get("/static/css/app.css").status_code == 200)

    print("\nSe arregla sola al migrar")
    with contextlib.redirect_stdout(io.StringIO()):
        apply_all(old, str(BASE_DIR / "migrations"))
    # Ya no es 503: ahora lo unico que falta es entrar, que es el
    # siguiente paso correcto en una base recien puesta al dia.
    r = client.get("/visitas/nueva")
    check("deja de bloquear sin reiniciar el servidor",
          r.status_code != 503, r.status_code)
    check("y lo que pide ahora es crear la cuenta",
          r.status_code == 302 and "/crear-cuenta" in r.headers["Location"],
          r.headers.get("Location"))
    check("y health vuelve a ok", client.get("/health").get_json()["status"] == "ok")

    print("\nBase mas nueva que el codigo")
    future = fresh_db()
    conn = sqlite3.connect(future)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    conn.close()
    body = app_on(future).get("/").get_data(as_text=True)
    check("tambien corta el paso", "m\u00e1s nueva que el programa" in body)
    check("y ahi el comando es actualizar el programa", "git pull" in body)

    for path in (empty, old, future):
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)


def run_csrf(db_path):
    print("\nProteccion CSRF")

    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True          # CSRF activo a proposito
        AUTO_BACKUP = False

    # No se abre sesion: el CSRF se revisa antes que el control de acceso,
    # que es el orden correcto. Un POST forjado se rechaza de entrada, sin
    # llegar siquiera a mirar quien lo manda.
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
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())

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
                    data={"pet": ["1", "2"], "pick": ["1:1", "1:2", "2:1"],
                          "price_1_1": "20", "price_1_2": "70",
                          "price_2_1": "20", "charge": "1"})
    check("visita de hoy registrada y cobrada de una", r.status_code == 302)
    r = client.post("/visitas/nueva/2",
                    data={"pet": ["3"], "pick": ["3:1"], "price_3_1": "20",
                          "visit_date": lunes, "charge": "1"})
    check("visita del lunes registrada y cobrada", r.status_code == 302)

    print("\nCifras del periodo")
    body = client.get("/resumen/?p=semana").get_data(as_text=True)
    check("suma lo facturado en la semana", "$130.00" in body, body[:200])
    check("cuenta 3 perros atendidos en 2 visitas",
          ">3<" in body and ">2<" in body)
    # Se mira solo la seccion de servicios: arriba hay mensajes flash
    # acumulados que tambien nombran los servicios.
    barras = body[body.index("Demanda de servicio"):]
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
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "999"})
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


CUADERNO = """\
Fecha,Cliente,Tel\u00e9fono,Mascota,Tama\u00f1o,Raza,Servicio,Precio,Notas
2026-07-03,Ana Vega,6123-4567,Rocky,mediano,Schnauzer,Ba\u00f1o,18.00,
14/07/2026,Marta R\u00edos,6555-1122,Toby,peque\u00f1o,,Ba\u00f1o,15.00,
2026-07-21,ana vega,61234567,Rocky,,,Ba\u00f1o,18.00,vino nerviosa
2026-08-02,Don Pedro,,Coco,,Poodle,Ba\u00f1o,15.00,el del kiosko
2026-08-11,Marta Rios,6555-1122,Luna,grande,Labrador,Ba\u00f1o,25.00,
2026-08-15,Sra. Lidia,999,Pelusa,enorme,,Ba\u00f1o,15,
,Nadie,6111-2222,Fantasma,peque\u00f1o,,Ba\u00f1o,15.00,sin fecha
2099-01-01,Del Futuro,6111-3333,Cronos,peque\u00f1o,,Ba\u00f1o,15.00,
2026-08-30,Precio Malo,6111-4444,Roto,peque\u00f1o,,Ba\u00f1o,quince d\u00f3lares,
"""


def run_import(_unused):
    """scripts/import_csv.py: pasar el cuaderno de papel al sistema."""
    import subprocess

    work = tempfile.mkdtemp()
    db = os.path.join(work, "petcrm.db")
    csv_path = os.path.join(work, "cuaderno.csv")
    pathlib.Path(csv_path).write_text(CUADERNO, encoding="utf-8")
    entorno = dict(os.environ, DB_PATH=db, AUTO_BACKUP="0")

    def importar(*extra):
        return subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "import_csv.py"),
             csv_path, *extra],
            cwd=str(BASE_DIR), env=entorno, capture_output=True, text=True)

    subprocess.run([sys.executable, str(BASE_DIR / "scripts" / "init_db.py")],
                   cwd=str(BASE_DIR), env=entorno, capture_output=True)

    print("\nMigrar el cuaderno de papel")

    r = importar()
    check("por defecto solo informa, no escribe",
          r.returncode == 0 and "No se escribio nada" in r.stdout, r.stderr[-400:])
    conn = sqlite3.connect(db)
    check("y la base sigue vacia de verdad",
          conn.execute("SELECT COUNT(*) FROM client").fetchone()[0] == 0)
    conn.close()

    check("cuenta lo que entra y lo que no",
          "se pueden importar: 6" in r.stdout and "no se pueden leer:  3" in r.stdout,
          r.stdout[:600])
    check("dice cual renglon no se pudo leer y por que",
          "falta fecha" in r.stdout and "futuro" in r.stdout
          and "quince d" in r.stdout, r.stdout[-900:])
    check("y deja los ilegibles en un CSV para corregirlos",
          os.path.exists(os.path.join(work, "cuaderno-rechazados.csv")))

    # El precio de lista se deduce por talla, que es como cobra una
    # peluqueria: el mismo bano vale distinto segun el perro.
    check("propone el precio de lista que dice el papel, por talla",
          "$15.00" in r.stdout and "$18.00" in r.stdout and "$25.00" in r.stdout,
          r.stdout[:900])

    r = importar("--commit")
    check("con --commit si escribe", r.returncode == 0, r.stderr[-400:])
    check("y saca un respaldo antes de tocar nada",
          "antes-de-importar" in r.stdout)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cuenta = lambda t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    # 'Ana Vega' y 'ana vega' son la misma persona: el telefono manda.
    # 'Ana Vega' + 'ana vega' y 'Marta Rios' + 'Marta Rios' se juntan
    # por telefono; Don Pedro y Sra. Lidia entran por nombre.
    check("el mismo cliente escrito de dos formas entra una sola vez",
          cuenta("client") == 4, cuenta("client"))
    check("las mascotas quedan colgadas de su duenio",
          cuenta("pet") == 5, cuenta("pet"))
    check("y cada dia del cuaderno es una visita",
          cuenta("visit") == 6, cuenta("visit"))

    # Lo que el cuaderno no traia entra vacio, no inventado.
    check("un cliente sin telefono entra sin telefono",
          conn.execute("SELECT COUNT(*) FROM client WHERE phone IS NULL")
              .fetchone()[0] == 2)
    check("un telefono ilegible no se guarda a medias",
          conn.execute("SELECT phone FROM client WHERE name = 'Sra. Lidia'")
              .fetchone()[0] is None)
    check("una mascota sin talla entra sin talla",
          conn.execute("SELECT COUNT(*) FROM pet WHERE size IS NULL")
              .fetchone()[0] == 2)
    check("pero una talla que si venia se conserva",
          conn.execute("SELECT size FROM pet WHERE name = 'Rocky'")
              .fetchone()[0] == "medium")

    # El precio del papel se congela en la linea, como cualquier visita.
    check("cada linea guarda el precio que decia el papel",
          sorted(r[0] for r in conn.execute(
              "SELECT price_cents FROM visit_service")) ==
          [1500, 1500, 1500, 1800, 1800, 2500])
    # 'any' junto a las de talla no puede quedar: la pantalla de
    # servicios decide el modo por su ausencia, y al guardar borraria
    # las de talla sin avisar.
    check("y el catalogo queda con una fila por talla, sin un 'any' encima",
          sorted((r["size"], r["price_cents"]) for r in conn.execute(
              "SELECT size, price_cents FROM service_price")) ==
          [("large", 2500), ("medium", 1800), ("small", 1500)],
          [tuple(r) for r in conn.execute(
              "SELECT size, price_cents FROM service_price")])

    # Esto es lo que hace util el import: el panel de 'a quien escribirle'
    # funciona desde el primer dia, sin esperar un mes de visitas nuevas.
    check("el marcador de ultima visita queda sembrado",
          conn.execute("SELECT COUNT(*) FROM v_pet_last_visit "
                       "WHERE last_visit_date IS NOT NULL").fetchone()[0] == 5)

    # Historia, no trabajo del sistema: no puede contarse como tal.
    check("las visitas importadas quedan marcadas como historia",
          conn.execute("SELECT COUNT(*) FROM visit WHERE source = 'import'")
              .fetchone()[0] == 6)
    conn.close()

    print("\nVolver a pasar el mismo cuaderno")
    r = importar("--commit")
    conn = sqlite3.connect(db)
    check("no duplica ni un cliente", cuenta("client") == 4)
    check("ni una visita", cuenta("visit") == 6)
    check("ni una linea", cuenta("visit_service") == 6)
    conn.close()
    check("y lo dice", "0 clientes" in r.stdout and "0 visitas" in r.stdout)

    class Cfg(DevelopmentConfig):
        DB_PATH = db
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())

    print("\nEl catalogo importado se puede seguir editando")

    body = client.get("/servicios/").get_data(as_text=True)
    check("la lista muestra los tres precios, no uno solo",
          "$15.00" in body and "$18.00" in body and "$25.00" in body, body[-900:])

    body = client.get("/servicios/1/editar").get_data(as_text=True)
    # 'Por tamanio' se elige por la AUSENCIA de un precio 'any'. Si el
    # import hubiera dejado los dos, esta pantalla abriria en 'Uno solo'
    # y el primer guardado borraria la tabla por talla.
    check("el formulario abre en 'por tamanio', que es como entro",
          'data-price-block="size" hidden' not in body
          and 'data-price-block="any" hidden' in body,
          body[body.find("data-price-block"):][:300])
    check("y trae los tres precios listos para corregir",
          'value="15.00"' in body and 'value="18.00"' in body
          and 'value="25.00"' in body)

    print("\nCobrarle a un perro que entro sin talla")

    conn = sqlite3.connect(db)
    coco = conn.execute(
        "SELECT id, client_id FROM pet WHERE size IS NULL LIMIT 1").fetchone()
    conn.close()

    # Lo que decia el papel la ultima vez es mejor referencia que
    # cualquier precio de lista: es lo que se le cobro a ESE perro.
    body = client.get(f"/visitas/nueva/{coco[1]}").get_data(as_text=True)
    check("el precio que decia el cuaderno queda de referencia",
          "\u00faltimo cobro" in body and 'value="15.00"' in body, body[:400])

    # Una mascota nueva sin talla no tiene ni historia ni precio de
    # lista al cual caer: la pantalla lo dice en vez de poner un numero.
    client.post(f"/clientes/{coco[1]}/mascotas/nueva", data={"name": "Nuevo"})
    body = client.get(f"/visitas/nueva/{coco[1]}").get_data(as_text=True)
    check("y sin historia ni talla, no se inventa ninguno",
          "sin precio de lista" in body, body[-1500:])

    r = client.post(f"/visitas/nueva/{coco[1]}",
                    data={"pet": [str(coco[0])], "pick": [f"{coco[0]}:1"],
                          f"price_{coco[0]}_1": "15"})
    check("se le cobra igual, escribiendo el monto a mano",
          r.status_code == 302, r.get_data(as_text=True)[:300])

    print("\nEl hueco se ve en la aplicacion")

    body = client.get("/clientes/").get_data(as_text=True)
    check("el panel dice quien no tiene telefono", "sin tel" in body.lower())
    check("y ofrece filtrar lo que quedo incompleto",
          "Datos incompletos" in body, body[:900])

    body = client.get("/clientes/?f=incompletos").get_data(as_text=True)
    check("el filtro deja solo a los que les falta algo",
          "Don Pedro" in body and "Sra. Lidia" in body
          and "Ana Vega" not in body, body[-1200:])

    conn = sqlite3.connect(db)
    sin_tel = conn.execute(
        "SELECT id FROM client WHERE phone IS NULL LIMIT 1").fetchone()[0]
    conn.close()
    body = client.get(f"/clientes/{sin_tel}").get_data(as_text=True)
    check("la ficha sin telefono no ofrece un WhatsApp roto",
          "wa.me/None" not in body and "wa.me/" not in body, body[:700])
    check("dice cual es el hueco y lleva a taparlo",
          "Falta el tel" in body)

    # Y taparlo tiene que funcionar: es el flujo de despues de importar.
    r = client.post(f"/clientes/{sin_tel}/editar",
                    data={"name": "Don Pedro", "phone": "6777-8899"})
    check("se le puede agregar el telefono que faltaba", r.status_code == 302,
          r.get_data(as_text=True)[:300])
    body = client.get(f"/clientes/{sin_tel}").get_data(as_text=True)
    check("y entonces si aparece el boton de WhatsApp",
          "wa.me/50767778899" in body)


def run_outreach(db_path):
    """Escribirle el mismo mensaje a varios, uno por uno."""
    import re
    from urllib.parse import unquote

    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())

    client.post("/servicios/nuevo",
                data={"name": "Bano", "price_mode": "any", "price_any": "20"})
    gente = [("Ana Vega", "6123-4567", "Rocky", "small", 62),
             ("Don Pedro", "6111-2222", "Kira", "small", 40),
             ("Cira Paz", "6333-4444", "Nina", "large", 30),
             ("Dora Saez", "6555-6666", "Toby", "small", 2)]
    for n, (nombre, tel, mascota, talla, _) in enumerate(gente, start=1):
        client.post("/clientes/nuevo", data={"name": nombre, "phone": tel})
        client.post(f"/clientes/{n}/mascotas/nueva",
                    data={"name": mascota, "size": talla})
    # Alguien sin telefono: no puede entrar a un envio.
    client.post("/clientes/nuevo", data={"name": "Sin Numero"})

    with app.app_context():
        from app.clock import shift, today
        from app.database import get_db
        from app.repos import visits
        for n, (_, _, _, _, dias) in enumerate(gente, start=1):
            visits.create(n, shift(today(), -dias), None, [(n, 1, 2000)],
                          status="completed")
        get_db().commit()

    print("\nElegir a quienes")

    body = client.get("/clientes/").get_data(as_text=True)
    check("desde el panel se llega a los envios siempre",
          "Escribirle a varios" in body)

    body = client.get("/escribir/nuevo?g=escribir").get_data(as_text=True)
    check("los atrasados son tres", "<strong>3</strong>" in body, body[:900])
    check("y Dora, que vino hace dos dias, no esta",
          "Dora" not in body)
    check("quien no tiene telefono tampoco entra: no hay a donde escribirle",
          "Sin Numero" not in body)

    # Lo que hace util esto: cruzar dos preguntas. 'Atrasados' Y
    # 'perro pequenio' es justo la promo de talla chica.
    body = client.get("/escribir/nuevo?g=escribir&g=pequenos").get_data(as_text=True)
    check("los filtros se combinan entre si", "<strong>2</strong>" in body)
    check("Ana y Don Pedro si", "Ana Vega" in body and "Don Pedro" in body)
    check("Cira Paz no: su perro es grande", "Cira Paz" not in body)

    def cuenta_chip(html, etiqueta):
        """El numero que la pantalla pone al lado de una pestania."""
        m = re.search(etiqueta + r"\s*<span class=\"chip-n\">(\d+)</span>",
                      html, re.S)
        return int(m.group(1)) if m else None

    panel = client.get("/clientes/").get_data(as_text=True)
    envios = client.get("/escribir/nuevo").get_data(as_text=True)

    # Es la razon de que los criterios vivan en app/segments.py: si cada
    # pantalla contara por su cuenta, el dia que cambie el criterio los
    # dos numeros dejarian de cuadrar y nadie sabria cual creer.
    check("'Por escribir' da el mismo numero en las dos pantallas",
          cuenta_chip(panel, "Por escribir") ==
          cuenta_chip(envios, "Por escribir") == 3,
          (cuenta_chip(panel, "Por escribir"), cuenta_chip(envios, "Por escribir")))

    # Y donde NO cuadran, es a proposito: Sin Numero no tiene telefono,
    # asi que el panel lo cuenta y los envios no.
    check("pero los envios no cuentan a quien no se le puede escribir",
          cuenta_chip(panel, "Sin visitas") == 1
          and cuenta_chip(envios, "Sin visitas") == 0,
          (cuenta_chip(panel, "Sin visitas"), cuenta_chip(envios, "Sin visitas")))

    print("\nEscribir el mensaje una sola vez")

    check("se ve como le llega a una persona de verdad, ya resuelto",
          "Hola Ana, \u00bfc\u00f3mo est\u00e1 Rocky?" in body, body[:600])
    check("y con el nombre de pila, no el completo",
          "Hola Ana Vega" not in body)

    r = client.post("/escribir/nuevo",
                    data={"g": ["escribir"], "message": "  "})
    check("un mensaje vacio se rechaza",
          r.status_code == 400 and "Escribe el mensaje" in r.get_data(as_text=True))

    r = client.post("/escribir/nuevo",
                    data={"g": ["sin-visitas"], "message": "Hola"})
    check("y un envio sin destinatarios tambien",
          r.status_code == 400 and "nadie" in r.get_data(as_text=True).lower())

    MENSAJE = "Hola {cliente}, \u00bftraes a {mascota}? 50% & m\u00e1s"
    r = client.post("/escribir/nuevo",
                    data={"g": ["escribir"], "message": MENSAJE,
                          "name": "Promo de prueba"})
    check("con destinatarios y mensaje, arranca", r.status_code == 302,
          r.get_data(as_text=True)[:300])
    envio = r.headers["Location"]

    print("\nUno por uno, sin perder la cuenta")

    orden = []
    for paso in range(5):
        body = client.get(envio).get_data(as_text=True)
        if "Terminaste" in body:
            break
        quien = re.search(r'envio-quien">([^<]+)', body).group(1)
        orden.append(quien)
        if paso == 0:
            enlace = re.search(r'href="(https://wa\.me/[^"]+)"', body).group(1)
            check("el enlace lleva el numero internacional",
                  enlace.startswith("https://wa.me/50761234567?text="), enlace[:60])
            # Un & sin escapar partiria la URL y el mensaje llegaria
            # cortado a la mitad.
            texto = unquote(enlace.split("?text=", 1)[1])
            check("y el mensaje ya escrito, personalizado",
                  texto == "Hola Ana, \u00bftraes a Rocky? 50% & m\u00e1s", texto)
            check("la cuenta dice por cual va", "1 de 3" in body, body[:900])

        cid = re.search(r'name="client_id" value="(\d+)"', body).group(1)
        # Al segundo se le saltea, para separar 'escrito' de 'salteado'.
        extra = {"skip": "1"} if paso == 1 else {}
        client.post(envio + "/marcar", data={"client_id": cid, **extra})

    check("van saliendo del mas atrasado al menos",
          orden == ["Ana Vega", "Don Pedro", "Cira Paz"], orden)

    body = client.get(envio).get_data(as_text=True)
    check("al final dice cuantos se escribieron", "Terminaste: 2 de 3" in body,
          body[:600])
    check("y cuantos se saltearon", "1 salteado" in body)

    print("\nNo se le escribe dos veces a la misma persona")

    with app.app_context():
        from app.repos import outreach
        antes = outreach.targets(1)
        marcas = [(r["name"], r["sent_at"]) for r in antes if r["sent_at"]]
    # Un doble toque, o el boton de atras, no puede reescribir la hora
    # ni convertir un salteado en escrito.
    client.post(envio + "/marcar", data={"client_id": "2"})
    with app.app_context():
        from app.repos import outreach
        despues = outreach.targets(1)
        check("volver a marcar a un salteado no lo convierte en escrito",
              [r["skipped_at"] is not None for r in despues if r["client_id"] == 2] == [True])
        check("ni cambia la hora de quien ya estaba escrito",
              [(r["name"], r["sent_at"]) for r in despues if r["sent_at"]] == marcas)

    print("\nUn toque errado se puede deshacer")

    # Es la otra mitad de "no pierdas la cuenta": sin rehacer, un dedo
    # que toca el boton de al lado deja a alguien fuera para siempre.
    client.post(envio + "/rehacer", data={"client_id": "1"})
    body = client.get(envio).get_data(as_text=True)
    check("quien se marco por error vuelve a la cola",
          "Ana Vega" in body and "Terminaste" not in body, body[:600])
    check("y la cuenta lo refleja", "3 de 3" in body, body[:900])

    cid = re.search(r'name="client_id" value="(\d+)"', body).group(1)
    client.post(envio + "/marcar", data={"client_id": cid})

    print("\nEl envio queda registrado")

    body = client.get("/escribir/").get_data(as_text=True)
    check("aparece en la lista de envios", "Promo de prueba" in body)
    check("con cuantos de cuantos", "2/3" in body, body[:900])
    # Un salteado ya se decidio. Marcarlo como pendiente pondria
    # "faltan 1" en un envio que si termino.
    check("y sin marcarlo como pendiente: nadie quedo sin tocar",
          "faltan" not in body, body[:900])

    r = client.post(envio + "/cerrar", follow_redirects=True)
    check("se puede cerrar", "cerrado" in r.get_data(as_text=True))

    r = client.post(envio + "/eliminar", follow_redirects=True)
    check("y eliminar", "eliminado" in r.get_data(as_text=True))
    check("y entonces ya no esta",
          "Promo de prueba" not in client.get("/escribir/").get_data(as_text=True))

    print("\nY no se le escribe a quien pidio que no")

    with app.app_context():
        from app.database import get_db
        get_db().execute(
            "UPDATE client SET preferred_channel = 'none' WHERE name = 'Ana Vega'")
        get_db().commit()
    body = client.get("/escribir/nuevo?g=escribir").get_data(as_text=True)
    check("queda fuera de los envios", "Ana Vega" not in body, body[:600])
    check("pero los demas siguen", "Don Pedro" in body)


def run_paging(db_path):
    """El panel de clientes va de a diez, no se trae la base entera."""
    import re

    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())
    client.post("/servicios/nuevo",
                data={"name": "Bano", "price_mode": "any", "price_any": "20"})

    tallas = ["small", "medium", "large"]
    for i in range(1, 24):
        client.post("/clientes/nuevo",
                    data={"name": f"Cliente {i:02d}", "phone": f"6{i:03d}0000"})
        client.post(f"/clientes/{i}/mascotas/nueva",
                    data={"name": f"Perro{i}", "size": tallas[i % 3]})
    with app.app_context():
        from app.clock import shift, today
        from app.database import get_db
        from app.repos import visits
        for i in range(1, 24):
            visits.create(i, shift(today(), -(i * 3)), None, [(i, 1, 2000)],
                          status="completed")
        get_db().commit()

    def filas(url):
        body = client.get(url).get_data(as_text=True)
        return re.findall(r'list-title">([^<]+)</span>', body), body

    def pie(url):
        """El texto del paginador, con los saltos de linea aplanados."""
        body = client.get(url).get_data(as_text=True)
        m = re.search(r'pager-txt">(.*?)</span>', body, re.S)
        return " ".join(m.group(1).split()) if m else ""

    print("\nEl panel no se trae la base entera")

    nombres, body = filas("/clientes/")
    check("la primera pagina trae diez, no veintitres", len(nombres) == 10,
          len(nombres))
    check("y son los diez primeros por nombre",
          nombres[0] == "Cliente 01" and nombres[-1] == "Cliente 10", nombres)
    check("dice por cual va y cuantos hay",
          pie("/clientes/") == "1 de 3 · 23 clientes", pie("/clientes/"))

    nombres, _ = filas("/clientes/?p=2")
    check("la segunda sigue donde termino la primera",
          nombres[0] == "Cliente 11" and len(nombres) == 10, nombres)
    nombres, _ = filas("/clientes/?p=3")
    check("la ultima trae solo los que quedan", len(nombres) == 3, nombres)

    # 'p' llega de la URL: no puede dejar la pantalla en blanco.
    nombres, _ = filas("/clientes/?p=99")
    check("una pagina que no existe cae en la ultima",
          nombres == ["Cliente 21", "Cliente 22", "Cliente 23"], nombres)
    nombres, _ = filas("/clientes/?p=abc")
    check("y una que no es un numero, en la primera",
          nombres[0] == "Cliente 01", nombres[:2])
    nombres, _ = filas("/clientes/?p=-5")
    check("tampoco se puede pedir una pagina negativa",
          nombres[0] == "Cliente 01", nombres[:2])

    print("\nBuscando se ve todo lo que coincide")

    nombres, body = filas("/clientes/?q=Cliente 1")
    check("quien escribio un nombre ya acoto solo", len(nombres) == 12,
          len(nombres))
    check("asi que ahi no hay paginador", "pager-txt" not in body)

    print("\nLos filtros tambien paginan, y siguen contando bien")

    nombres, body = filas("/clientes/?f=escribir")
    check("el grupo trae su propia cuenta",
          pie("/clientes/?f=escribir") == "1 de 2 · 18 clientes",
          pie("/clientes/?f=escribir"))
    check("y su pagina es de diez", len(nombres) == 10, len(nombres))
    check("ordenado por quien lleva mas esperando",
          nombres[0] == "Cliente 23", nombres[:3])

    _nombres, body = filas("/clientes/")
    for etiqueta, esperado in (("Todos", 23), ("Por escribir", 18),
                               ("Perros peque", 7)):
        m = re.search(etiqueta + r'[^<]*<span class="chip-n">(\d+)</span>', body)
        check(f"la pestania '{etiqueta}' cuenta sobre TODA la base, no sobre la pagina",
              m is not None and int(m.group(1)) == esperado,
              m.group(1) if m else "(no esta)")

    # El boton de envio manda al grupo entero, no a los diez de pantalla.
    check("el boton de escribirles nombra al grupo completo",
          "Escribirle a los 18" in body.replace("\n", " ")
          or "Escribirle a los 18" in client.get(
              "/clientes/?f=escribir").get_data(as_text=True).replace("\n", " "))


def run_backdate(db_path):
    """Registrar a mano una visita de otro dia."""
    class Cfg(DevelopmentConfig):
        DB_PATH = db_path
        TESTING = True
        WTF_CSRF_ENABLED = False
        AUTO_BACKUP = False

    app = create_app(Cfg)
    client = sign_in(app.test_client())
    client.post("/servicios/nuevo",
                data={"name": "Bano", "price_mode": "any", "price_any": "20"})
    client.post("/clientes/nuevo", data={"name": "Ana Vega", "phone": "61234567"})
    client.post("/clientes/1/mascotas/nueva", data={"name": "Rocky", "size": "small"})

    with app.app_context():
        from app.clock import shift, today
        hoy = today()
        ayer = shift(hoy, -1)
        manana = shift(hoy, 1)

    print("\nRegistrar visita, desde cualquier dia")

    body = client.get("/visitas/").get_data(as_text=True)
    check("el boton vive en la pantalla, no solo flotando",
          "btn-cta" in body and "Registrar visita" in body, body[:600])
    # Debajo del dia y encima de lo cobrado: es lo primero que se hace
    # al abrir, antes que leer.
    check("va entre el dia y lo cobrado",
          body.index("daynav") < body.index("btn-cta") < body.index("tiles"))

    body = client.get(f"/visitas/?dia={ayer}").get_data(as_text=True)
    check("tambien esta en un dia pasado", "btn-cta" in body)
    check("y dice de que dia va a ser", f"dia={ayer}" in body, body[:900])

    body = client.get(f"/visitas/nueva?dia={ayer}").get_data(as_text=True)
    check("el selector avisa con que fecha se va a guardar",
          "Se registrar" in body and "fecha" in body, body[:900])

    body = client.get(f"/visitas/nueva/1?dia={ayer}").get_data(as_text=True)
    check("y el formulario abre con ESA fecha, no con hoy",
          f'value="{ayer}"' in body, body[body.find("visit_date") - 80:][:200])

    r = client.post(f"/visitas/nueva/1?dia={ayer}",
                    data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "20",
                          "visit_date": ayer, "charge": "1"})
    check("la visita se guarda en el dia de ayer", r.status_code == 302)
    body = client.get(f"/visitas/?dia={ayer}").get_data(as_text=True)
    check("y aparece ahi", "Ana Vega" in body and "$20.00" in body)
    check("no en hoy", "Ana Vega" not in client.get("/visitas/").get_data(as_text=True))

    # 'dia' llega de la URL: una fecha futura no puede colarse.
    body = client.get(f"/visitas/nueva/1?dia={manana}").get_data(as_text=True)
    check("un dia futuro se ignora y queda hoy",
          f'value="{hoy}"' in body, body[body.find("visit_date") - 80:][:200])
    body = client.get("/visitas/nueva/1?dia=no-es-fecha").get_data(as_text=True)
    check("y una fecha ilegible tambien", f'value="{hoy}"' in body)


def short_date_of(app, iso, weekday=False):
    with app.app_context():
        from app.labels import short_date
        return short_date(iso, weekday)


def shift_of(app, iso, days):
    with app.app_context():
        from app.clock import shift
        return shift(iso, days)


if __name__ == "__main__":
    for runner in (run_flow, run_csrf, run_stats, run_interface,
                   run_schema_guard, run_auto_migrate, run_auth,
                   run_backups, run_seed, run_import, run_outreach,
                   run_paging, run_backdate):
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
