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
    client.post("/visitas/nueva/1",
                data={"pick": ["1:1"], "price_1_1": "20", "charge": "1"})
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

    contenido = caja(page, ".wrap")
    check("el contenido arranca justo despues de la barra, sin hueco",
          abs(contenido["x"] - nav["w"]) < 2, (contenido, nav))
    check("y no se estira hasta ser ilegible", contenido["w"] <= 1100, contenido)

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
