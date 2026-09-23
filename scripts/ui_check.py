"""Verificacion en un navegador real.

Lo que se prueba aqui no se puede probar desde el servidor: que el
dialogo de confirmacion sea el de la aplicacion y no el del navegador,
y que el buscador responda mientras se escribe.

No entra al CI porque necesita un navegador instalado. Se corre a mano:

    pip install playwright && playwright install chromium
    python scripts/ui_check.py

Si hay un Chromium en otra ruta, se le pasa:

    python scripts/ui_check.py --chromium /ruta/al/chrome
"""
import argparse
import contextlib
import io
import logging
import re
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import create_app                    # noqa: E402
from app.config import DevelopmentConfig      # noqa: E402
from scripts.migrate import apply_all         # noqa: E402

FAILURES = []
PORT = 5099
EMAIL = "duenio@ejemplo.com"
PASSWORD = "clave-de-prueba"


def check(label, condition, detail=""):
    print(("  ok    " if condition else "  FALLA ") + label
          + (f"   {detail}" if not condition and detail else ""))
    if not condition:
        FAILURES.append(label)


def seeded_app():
    path = tempfile.mktemp(suffix=".db")
    sqlite3.connect(path).close()
    with contextlib.redirect_stdout(io.StringIO()):
        apply_all(path, str(BASE_DIR / "migrations"))

    class Cfg(DevelopmentConfig):
        DB_PATH = path
        TESTING = True
        WTF_CSRF_ENABLED = False

    app = create_app(Cfg)
    client = app.test_client()
    client.post("/crear-cuenta", data={
        "display_name": "Duenio", "email": EMAIL,
        "password": PASSWORD, "password2": PASSWORD,
    })
    client.post("/clientes/nuevo", data={"name": "Marta Rios", "phone": "61234567"})
    client.post("/clientes/1/mascotas/nueva", data={"name": "Toby", "size": "small"})
    client.post("/clientes/1/mascotas/nueva", data={"name": "Luna", "size": "large"})
    client.post("/clientes/nuevo", data={"name": "Beto Lima", "phone": "60099887"})
    client.post("/clientes/2/mascotas/nueva", data={"name": "Kira", "size": "medium"})
    client.post("/servicios/nuevo",
                data={"name": "Bano", "price_mode": "any", "price_any": "20"})
    client.post("/servicios/nuevo",
                data={"name": "Corte", "price_mode": "any", "price_any": "15"})
    client.post("/visitas/nueva/1",
                data={"pet": ["1"], "pick": ["1:1"], "price_1_1": "20",
                      "charge": "1"})
    # Una sin cobrar, para ver la lista del inicio.
    client.post("/visitas/nueva/2",
                data={"pet": ["3"], "pick": ["3:1"], "price_3_1": "20"})

    # Alguien atrasado, para poder ver el boton de WhatsApp en la lista.
    with app.app_context():
        from app.clock import shift, today
        from app.database import get_db
        from app.repos import clients, pets, visits
        cira = clients.create({
            "name": "Cira Paz", "phone": "+50760055566",
            "phone_display": "6005-5566", "document": None, "email": None,
            "address": None, "notes": None})
        nina = pets.create({
            "client_id": cira, "name": "Nina", "species": "dog",
            "breed": None, "size": "large", "sex": None, "birthdate": None,
            "weight_kg": None, "temperament": None, "medical_notes": None,
            "is_active": 1})
        visits.create(cira, shift(today(), -40), None,
                      [(nina, 1, 2000)], status="completed")

        # Dos mas atrasados: un envio de uno solo no probaria que la
        # pantalla avanza al siguiente.
        for nombre, tel, mascota, dias in (
                ("Elsa Mora", "+50760077788", "Pelusa", 35),
                ("Fabio Ruiz", "+50760099900", "Bruno", 22)):
            cid = clients.create({
                "name": nombre, "phone": tel, "phone_display": None,
                "document": None, "email": None, "address": None,
                "notes": None})
            pid = pets.create({
                "client_id": cid, "name": mascota, "species": "dog",
                "breed": None, "size": "medium", "sex": None,
                "birthdate": None, "weight_kg": None, "temperament": None,
                "medical_notes": None, "is_active": 1})
            visits.create(cid, shift(today(), -dias), None,
                          [(pid, 1, 2000)], status="completed")
        get_db().commit()
    return app


def run(page, url):
    # Si el navegador llegara a abrir SU dialogo, cae aqui.
    native = []
    page.on("dialog", lambda d: (native.append(d.type), d.dismiss()))

    print("\nEntrar")
    page.goto(f"{url}/clientes/")
    check("sin sesion no se ve nada", "/entrar" in page.url, page.url)
    page.fill("input[name=email]", EMAIL)
    page.fill("input[name=password]", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/entrar" not in u, timeout=5000)
    check("con la cuenta correcta se entra", "/entrar" not in page.url, page.url)

    print("\nBuscador con resultados mientras se escribe")
    page.goto(f"{url}/visitas/nueva")
    results = page.locator("#search-results")
    check("el desplegable arranca oculto", results.is_hidden())

    page.fill("input[type=search]", "tob")          # nombre de MASCOTA
    page.wait_for_selector("#search-results li", timeout=5000)
    check("aparece al escribir, sin tocar Buscar", results.is_visible())
    check("encuentra al duenio por el nombre de su perro",
          "Marta Rios" in results.inner_text(), results.inner_text())
    check("muestra las mascotas debajo del nombre", "Toby" in results.inner_text())
    check("no cuela a quien no coincide", "Beto" not in results.inner_text())

    page.fill("input[type=search]", "6009")         # por TELEFONO
    page.wait_for_function(
        "() => document.querySelector('#search-results')"
        ".innerText.includes('Beto')", timeout=5000)
    check("tambien busca por telefono", "Beto Lima" in results.inner_text())

    page.keyboard.press("ArrowDown")
    check("la flecha resalta un resultado", results.locator("a.on").count() == 1)
    page.keyboard.press("Enter")
    page.wait_for_url("**/visitas/nueva/2", timeout=5000)
    check("Enter entra al cliente resaltado", "/visitas/nueva/2" in page.url)

    page.goto(f"{url}/visitas/nueva")
    page.fill("input[type=search]", "marta")
    page.wait_for_selector("#search-results li", timeout=5000)
    page.click("#search-results a")
    page.wait_for_url("**/visitas/nueva/1", timeout=5000)
    check("tocar un resultado abre su visita", "/visitas/nueva/1" in page.url)

    page.goto(f"{url}/visitas/nueva")
    page.fill("input[type=search]", "zzzz")
    page.wait_for_timeout(600)
    check("sin coincidencias no queda el desplegable abierto", results.is_hidden())

    print("\nEl mismo buscador en la lista de clientes")
    page.goto(f"{url}/clientes/")
    page.fill("input[type=search]", "kira")         # mascota de Beto
    page.wait_for_selector("#search-results li", timeout=5000)
    check("responde igual al escribir",
          "Beto Lima" in results.inner_text(), results.inner_text())
    page.click("#search-results a")
    page.wait_for_url("**/clientes/2", timeout=5000)
    check("pero aqui lleva a la ficha, no a registrar visita",
          page.url.rstrip("/").endswith("/clientes/2"), page.url)

    print("\nLa fila del cliente no se aprieta")
    page.goto(f"{url}/clientes/")
    caja = page.evaluate("""() => {
      const li = [...document.querySelectorAll('.list li')]
        .find(e => e.querySelector('.btn-wa'));
      if (!li) return null;
      const btn = li.querySelector('.btn-wa');
      const cs = getComputedStyle(btn);
      const b = btn.getBoundingClientRect();
      return {alto: Math.round(b.height), ancho: Math.round(b.width),
              desborda: btn.scrollWidth > btn.offsetWidth + 1,
              direccion: cs.flexDirection,
              lineas: Math.round(b.height / parseFloat(cs.lineHeight || 20))};
    }""")
    check("hay una fila con boton de WhatsApp", caja is not None, caja)
    if caja:
        # El boton es un <a> hermano dentro del <li>: sin excluirlo del
        # selector del enlace se llevaba flex-direction: column y perdia
        # el relleno, con la etiqueta saliendose de la caja.
        check("el boton pone icono y texto en la misma linea",
              caja["direccion"] == "row", caja)
        check("y la etiqueta no se sale de su caja",
              not caja["desborda"], caja)
        check("sigue siendo tocable con el pulgar", caja["alto"] >= 44, caja)

    print("\nPrimero la mascota, despues sus servicios")
    page.goto(f"{url}/visitas/nueva/1")     # Marta Rios: Toby y Luna
    servicios = page.locator(".pet-services").first
    check("con dos mascotas, los servicios arrancan escondidos",
          not servicios.is_visible())
    check("y se ven las dos mascotas para elegir",
          page.locator(".pet-face").count() == 2)
    page.click(".pet-face >> nth=0")
    page.wait_for_timeout(200)
    check("al elegir una, aparecen SUS servicios", servicios.is_visible())
    check("los de la otra siguen escondidos",
          not page.locator(".pet-services").nth(1).is_visible())
    check("y se abre sin una sola linea de JS",
          page.evaluate("document.querySelector('.pet-check').checked") is True)

    # El total en vivo tiene que decir lo mismo que va a guardar el
    # servidor: los servicios de una mascota cerrada no cuentan.
    abierta = page.locator(".pet-card").first
    abierta.locator(".line-face").first.click()
    abierta.locator("[data-amount]").first.fill("30")
    page.wait_for_timeout(150)
    check("el total suma lo marcado de la mascota abierta",
          page.inner_text("[data-total]") == "$30.00",
          page.inner_text("[data-total]"))
    page.click(".pet-face >> nth=0")        # se cierra sin desmarcar
    page.wait_for_timeout(150)
    check("al cerrarla, su servicio deja de contar",
          page.inner_text("[data-total]") == "$0.00",
          page.inner_text("[data-total]"))
    check("pero no se pierde lo escrito: vuelve al reabrirla",
          abierta.locator(".line-check").first.is_checked())

    page.goto(f"{url}/visitas/nueva/2")     # Beto Lima: solo Kira
    check("con una sola mascota ya viene abierta",
          page.locator(".pet-services").first.is_visible())

    # Al corregir una visita ya guardada se abre la mascota que si
    # vino, no las dos: si no, la correccion arranca mintiendo.
    page.goto(f"{url}/visitas/1/editar")    # Marta: se atendio a Toby
    abiertas = page.evaluate(
        "() => [...document.querySelectorAll('.pet-card')]"
        "  .filter(c => c.querySelector('.pet-check').checked)"
        "  .map(c => c.querySelector('.pet-name').innerText.split('\\n')[0].trim())")
    check("al corregir, se abre la mascota que si se atendio",
          abiertas == ["Toby"], abiertas)

    print("\nEl inicio abre con lo que falta cobrar")
    page.goto(f"{url}/")
    texto = page.inner_text("body")
    check("hay una raya que separa las acciones de la deuda",
          page.locator("main hr").count() == 1)
    check("y debajo la lista de pendientes", "Pendientes de cobro" in texto)
    fila = page.locator(".list li.is-pending").first
    check("con el nombre de quien falta por cobrar",
          "Beto Lima" in fila.inner_text(), fila.inner_text())
    import re as _re
    check("y la hora a la que se recibio la mascota",
          _re.search(r"\d\d:\d\d", fila.inner_text()) is not None,
          fila.inner_text())
    orden = page.evaluate(
        "() => { const hr = document.querySelector('main hr');"
        "  const nuevo = [...document.querySelectorAll('.stack .btn')]"
        "    .find(e => e.innerText.includes('Nuevo cliente'));"
        "  return nuevo && (hr.compareDocumentPosition(nuevo) & 2) > 0; }")
    check("la raya va debajo de 'Nuevo cliente'", orden is True)

    print("\nNada pegado al borde de una lista")
    page.goto(f"{url}/clientes/1")
    hueco = page.evaluate(
        "() => { const b = [...document.querySelectorAll('.btn')]"
        "   .find(e => e.innerText.includes('Agregar mascota'));"
        "  const ul = b.previousElementSibling;"
        "  return Math.round(b.getBoundingClientRect().top"
        "                    - ul.getBoundingClientRect().bottom); }")
    check("'Agregar mascota' no toca la lista de mascotas", hueco >= 8, hueco)

    print("\nLos datos del cliente se leen en la ficha")
    page.goto(f"{url}/clientes/3")          # Cira Paz, sin datos extra
    check("si no hay datos extra, no hay caja vacia",
          page.locator(".datos").count() == 0)
    page.goto(f"{url}/clientes/1/editar")
    page.evaluate("document.querySelector('details.more').open = true")
    page.fill("input[name=document]", "8-123-456")
    page.fill("input[name=address]", "Via Espania, casa 4")
    page.click("button[type=submit]")
    page.wait_for_url("**/clientes/1", timeout=5000)
    datos = page.locator(".datos").inner_text()
    check("la cedula se ve al entrar, sin abrir el editor",
          "8-123-456" in datos, datos)
    check("y la direccion tambien", "Via Espania" in datos, datos)

    print("\nEscribirle a varios: la vista previa en vivo")
    page.goto(f"{url}/escribir/nuevo?g=escribir")
    campo = page.locator("[data-plantilla]")
    vista = page.locator("[data-vista]")
    check("hay alguien a quien escribirle", vista.count() == 1)
    campo.fill("Hola {cliente}, traele a {mascota} el jueves")
    page.wait_for_timeout(200)
    texto = vista.inner_text()
    check("el mensaje se resuelve mientras se escribe",
          "{cliente}" not in texto and "{mascota}" not in texto, texto)
    check("con el nombre de pila de una persona de verdad",
          texto.startswith("Hola Cira,"), texto)

    # Tocar un filtro no puede costar el mensaje ya escrito: se manda el
    # formulario entero, no una URL nueva.
    page.click(".chip-check:has-text('Perros grandes') span")
    page.wait_for_load_state("networkidle")
    check("cambiar un filtro no borra lo que ya se escribio",
          "el jueves" in page.locator("[data-plantilla]").input_value(),
          page.locator("[data-plantilla]").input_value())

    print("\nEscribirle a varios: un toque en vez de dos")
    page.goto(f"{url}/escribir/nuevo?g=escribir")
    page.fill("[data-plantilla]", "Hola {cliente}")
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/escribir/\d+$"), timeout=5000)

    primero = page.locator(".envio-quien").inner_text()
    enlace = page.locator("[data-abrir]")
    check("el chat se abre en otra pestania, no encima del sistema",
          enlace.get_attribute("target") == "_blank"
          and "noopener" in (enlace.get_attribute("rel") or ""))
    check("y el enlace ya lleva el mensaje escrito",
          "?text=Hola%20" in enlace.get_attribute("href"),
          enlace.get_attribute("href"))

    # Al tocar el enlace: se abre WhatsApp en otra pestania Y esta
    # avanza sola al siguiente. Sin JS haria falta el segundo boton.
    with page.context.expect_page() as nueva:
        enlace.click()
    chat = nueva.value
    # Solo que la pestania se abrio: si de verdad carga wa.me depende
    # de que haya internet, y eso no es lo que se esta probando aqui.
    check("tocar abre de verdad una pestania nueva", chat is not None)
    chat.close()
    page.wait_for_url(re.compile(r"/escribir/\d+$"), timeout=5000)
    page.wait_for_timeout(600)
    segundo = page.locator(".envio-quien").inner_text()
    check("y la pantalla ya paso sola al siguiente",
          segundo != primero, f"{primero} -> {segundo}")
    check("la cuenta lo refleja", "2 de 3" in page.inner_text(".avance-txt"),
          page.inner_text(".avance-txt"))

    print("\nDia y noche")
    page.goto(f"{url}/resumen/")
    fondo = lambda: page.evaluate(
        "getComputedStyle(document.body).backgroundColor")
    claro = fondo()
    page.click("[data-tema]")
    page.wait_for_timeout(200)
    oscuro = fondo()
    check("el interruptor cambia el fondo de verdad", claro != oscuro,
          f"{claro} -> {oscuro}")
    check("y deja marcado el tema elegido",
          page.evaluate("document.documentElement.dataset.theme") == "dark")

    page.goto(f"{url}/clientes/")
    check("la eleccion sobrevive al cambiar de pantalla",
          page.evaluate("document.documentElement.dataset.theme") == "dark"
          and fondo() == oscuro)

    page.reload()
    check("y a recargar: queda guardada en el navegador",
          page.evaluate("document.documentElement.dataset.theme") == "dark")

    page.click("[data-tema]")
    page.wait_for_timeout(200)
    check("volver a tocarlo regresa al modo dia", fondo() == claro, fondo())

    print("\nLa flecha de volver")
    page.goto(f"{url}/clientes/1")
    volver = page.locator(".back-icon")
    check("existe y se ve", volver.is_visible())
    check("tiene nombre accesible aunque sea un icono",
          volver.get_attribute("aria-label") == "Volver")
    propio = page.evaluate(
        "getComputedStyle(document.querySelector('.back-icon')).backgroundColor")
    cabecera = page.evaluate(
        "getComputedStyle(document.querySelector('.topbar')).backgroundColor")
    check("con fondo propio: no se confunde con la cabecera",
          propio != cabecera and propio != "rgba(0, 0, 0, 0)",
          f"{propio} vs {cabecera}")
    caja = page.evaluate(
        "() => { const b = document.querySelector('.back-icon')"
        ".getBoundingClientRect(); return {w: b.width, h: b.height}; }")
    check("y sigue siendo tocable con el pulgar",
          caja["w"] >= 44 and caja["h"] >= 44, caja)
    volver.click()
    page.wait_for_url("**/clientes/", timeout=5000)
    check("y lleva de vuelta", page.url.endswith("/clientes/"))

    print("\nConfirmacion propia de la aplicacion")
    page.goto(f"{url}/visitas/1/editar")
    dialog = page.locator("#confirm-dialog")
    check("el dialogo arranca cerrado", dialog.is_hidden())

    page.click("button:has-text('Eliminar visita')")
    page.wait_for_timeout(300)
    check("al eliminar se abre el dialogo de la app", dialog.is_visible())
    check("y NO el del navegador", not native, f"se abrio: {native}")
    check("el mensaje es el nuestro",
          "Deja de contar en los totales" in dialog.inner_text())
    check("el boton nombra la accion en vez de decir 'Aceptar'",
          "Eliminar" in dialog.locator("[data-confirm-accept]").inner_text())

    page.click("#confirm-dialog button[value=cancel]")
    page.wait_for_timeout(300)
    check("Cancelar cierra sin hacer nada",
          dialog.is_hidden() and "/visitas/1/editar" in page.url)

    page.click("button:has-text('Eliminar visita')")
    page.wait_for_timeout(200)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("Escape tambien cancela",
          dialog.is_hidden() and "/visitas/1/editar" in page.url)

    page.click("button:has-text('Eliminar visita')")
    page.wait_for_timeout(200)
    page.click("#confirm-dialog button[value=ok]")
    page.wait_for_url("**/visitas/**", timeout=5000)
    page.wait_for_timeout(300)
    check("Confirmar si elimina", "Visita eliminada" in page.content())
    check("en ningun momento aparecio un dialogo del navegador", not native)


def run_responsive(browser, url):
    """La misma aplicacion en las dos formas: celular y computadora."""
    def entrar(width, height):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.goto(f"{url}/entrar")
        page.fill("input[name=email]", EMAIL)
        page.fill("input[name=password]", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(lambda u: "/entrar" not in u, timeout=5000)
        return ctx, page

    def caja(page, selector):
        return page.evaluate(
            "s => { const e = document.querySelector(s);"
            "       if (!e) return null;"
            "       const b = e.getBoundingClientRect();"
            "       return {x: b.x, y: b.y, w: b.width, h: b.height,"
            "               visible: b.width > 0 && b.height > 0}; }", selector)

    print("\nEn el celular (390px)")
    ctx, page = entrar(390, 760)
    for ruta in ("/", "/clientes/", "/resumen/", "/visitas/", "/ajustes/"):
        page.goto(url + ruta)
        ancho = page.evaluate("document.documentElement.scrollWidth")
        if ancho > 390:
            check(f"{ruta} no se desborda a lo ancho", False, f"scrollWidth={ancho}")
            break
    else:
        check("ninguna pantalla se desborda a lo ancho", True)

    page.goto(f"{url}/clientes/")
    nav = caja(page, ".tabbar")
    check("la barra de secciones va abajo, como en una app",
          nav["y"] > 500, nav)
    check("ocupa todo el ancho", nav["w"] == 390, nav)
    check("el boton flotante esta a mano", caja(page, ".fab")["visible"])
    tabs = page.evaluate("""() => [...document.querySelectorAll('.tabbar a')]
      .map(a => { const s = a.querySelector('span');
        return {texto: s.innerText,
                desborda: s.scrollWidth > a.clientWidth + 1}; })""")
    check("las seis pestanias caben sin partir su etiqueta",
          len(tabs) == 6 and not any(t["desborda"] for t in tabs), tabs)
    check("y la accion de arriba se esconde",
          not caja(page, ".topaction")["visible"])

    # Objetivo tactil: lo que se toca tiene que caber bajo un pulgar.
    chico = page.evaluate("""() => {
      const sel = '.tabbar a, .btn, .fab, .list li > a';
      return [...document.querySelectorAll(sel)]
        .map(e => ({t: e.textContent.trim().slice(0, 24),
                    h: e.getBoundingClientRect().height}))
        .filter(x => x.h > 0 && x.h < 44);
    }""")
    check("todo lo tocable mide al menos 44px de alto", not chico, chico)
    ctx.close()

    print("\nEn la computadora (1280px)")
    ctx, page = entrar(1280, 800)
    for ruta in ("/", "/clientes/", "/resumen/", "/visitas/", "/ajustes/"):
        page.goto(url + ruta)
        ancho = page.evaluate("document.documentElement.scrollWidth")
        if ancho > 1280:
            check(f"{ruta} no se desborda a lo ancho", False, f"scrollWidth={ancho}")
            break
    else:
        check("ninguna pantalla se desborda a lo ancho", True)

    page.goto(f"{url}/clientes/")
    nav = caja(page, ".tabbar")
    check("la misma barra pasa a la izquierda, como en una web",
          nav["x"] == 0 and nav["y"] < 50 and nav["h"] > 600, nav)
    check("y deja de ocupar todo el ancho", nav["w"] < 300, nav)
    check("el boton flotante desaparece", not caja(page, ".fab")["visible"])
    check("la accion sube junto al titulo",
          caja(page, ".topaction")["visible"])

    ajustes = caja(page, ".tabbar .tab-end")
    ultima = page.evaluate(
        "() => { const a = [...document.querySelectorAll('.tabbar a')];"
        "  return a[a.length - 1].classList.contains('tab-end'); }")
    check("Ajustes queda en la esquina de abajo a la izquierda",
          ultima and ajustes["x"] < 40 and ajustes["y"] + ajustes["h"] > 740,
          ajustes)
    check("con su engranaje y su nombre escrito",
          page.locator(".tabbar .tab-end svg").count() == 1
          and "Ajustes" in page.inner_text(".tabbar .tab-end"))
    check("y esta separada del ultimo apartado del dia a dia",
          ajustes["y"] - (caja(page, ".tabbar a:nth-of-type(5)")["y"] + 44) > 100,
          ajustes)

    contenido = caja(page, ".wrap")
    izquierda = contenido["x"] - nav["w"]
    derecha = 1280 - (contenido["x"] + contenido["w"])
    check("el contenido va centrado en el espacio que deja la barra",
          abs(izquierda - derecha) < 2, (izquierda, derecha))
    check("y no se estira hasta ser ilegible", contenido["w"] <= 950, contenido)

    # Dentro de esa columna, todo arranca en el mismo borde: si cada
    # bloque se centrara por su cuenta, el texto no cuadraria con su
    # propio encabezado. Se mide en el resumen, que es la pantalla con
    # mas variedad de bloques.
    page.goto(f"{url}/resumen/")
    bordes = page.evaluate("""() => {
      // ':not([hidden])' hace falta porque la lista del buscador
      // comparte la clase .list y esta oculta: daria x = 0.
      const sel = ['.chips', '.tiles', '.section', '.headline',
                   '.list:not([hidden])'];
      return sel.map(s => { const e = document.querySelector(s);
        return e ? Math.round(e.getBoundingClientRect().x) : null; })
        .filter(x => x !== null);
    }""")
    check("y dentro todo arranca en el mismo borde",
          len(set(bordes)) == 1, bordes)
    page.goto(f"{url}/clientes/")

    page.goto(f"{url}/clientes/nuevo")
    form = caja(page, ".form")
    check("un formulario no se estira a todo lo ancho",
          form["w"] <= 560, form)

    # Mismo HTML, distinta colocacion: nada se duplico para el escritorio.
    check("la barra de secciones es una sola en el HTML",
          page.evaluate("document.querySelectorAll('.tabbar').length") == 1)
    ctx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--chromium", default=None,
                        help="ruta a un Chromium ya instalado")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Falta playwright. Instalalo con:\n"
            "    pip install playwright && playwright install chromium"
        )

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", PORT, seeded_app(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    launch = {"executable_path": args.chromium} if args.chromium else {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 390, "height": 780})
            run(page, f"http://127.0.0.1:{PORT}")
            run_responsive(browser, f"http://127.0.0.1:{PORT}")
            browser.close()
    finally:
        server.shutdown()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} fallas: {FAILURES}")
        raise SystemExit(1)
    print("Todo verde.")
