"""Fase 7: pasar el cuaderno de papel al sistema.

El cuaderno es un registro de trabajo: un renglon por servicio hecho.
Este script lee ese mismo formato y arma con el los clientes, las
mascotas, el catalogo y el historico de visitas.

    fecha,cliente,telefono,mascota,tamano,raza,servicio,precio,notas
    2026-08-14,Ana Vega,6123-4567,Rocky,mediano,Schnauzer,Bano,18.00,

Por defecto NO escribe nada: lee, valida y dice exactamente que iba a
pasar. Recien con --commit toca la base, y antes de tocarla saca un
respaldo aparte.

    python scripts/import_csv.py cuaderno.csv
    python scripts/import_csv.py cuaderno.csv --commit

Los renglones que no se pueden leer no detienen la corrida: salen en un
CSV aparte con el motivo escrito al lado, para corregirlos y volver a
pasar ese archivo. Volver a correr el mismo cuaderno no duplica nada.
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from app import backups                          # noqa: E402
from app.config import Config                    # noqa: E402
from app.money import MoneyError, parse_money    # noqa: E402
from app.phone import PhoneError, normalize_phone  # noqa: E402

# Lo que se espera encontrar arriba del archivo. Se aceptan variantes
# porque quien exporta el cuaderno escribe 'Tamaño' o 'TAMANO' segun
# el programa que use.
COLUMNS = {
    "fecha": ("fecha", "dia", "date"),
    "cliente": ("cliente", "duenio", "dueno", "nombre", "client"),
    "telefono": ("telefono", "tel", "celular", "phone"),
    "mascota": ("mascota", "perro", "paciente", "pet"),
    "tamano": ("tamano", "talla", "size"),
    "raza": ("raza", "breed"),
    "servicio": ("servicio", "trabajo", "service"),
    "precio": ("precio", "monto", "valor", "price", "total"),
    "notas": ("notas", "nota", "observaciones", "comentario"),
}
REQUIRED = ("fecha", "cliente", "mascota", "servicio")

SIZES = {
    "pequeno": "small", "pequenio": "small", "chico": "small",
    "small": "small", "s": "small", "p": "small",
    "mediano": "medium", "medio": "medium", "medium": "medium", "m": "medium",
    "grande": "large", "large": "large", "g": "large", "l": "large",
}

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d")


def fold(text):
    """'Tamaño ' -> 'tamano'. Para comparar sin pelear con tildes."""
    raw = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", raw)


def key(text):
    """Clave para reconocer al mismo cliente escrito de dos formas."""
    raw = unicodedata.normalize("NFKD", str(text or "").strip().lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", raw).strip()


class Fila:
    """Un renglon del cuaderno, ya leido y con sus quejas anotadas."""

    def __init__(self, numero, crudo):
        self.numero = numero
        self.crudo = crudo
        self.error = None      # no se pudo leer: no entra
        self.avisos = []       # entra, pero con un hueco a la vista


def leer(path):
    """Devuelve (filas, columnas_encontradas). No toca la base."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        muestra = fh.read(4096)
        fh.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=",;\t")
        except csv.Error:
            dialecto = csv.excel
        lector = csv.DictReader(fh, dialect=dialecto)
        if not lector.fieldnames:
            raise SystemExit("El archivo esta vacio.")

        # Cada columna del archivo se mapea a su nombre interno.
        mapa = {}
        for nombre in lector.fieldnames:
            plegado = fold(nombre)
            for interno, variantes in COLUMNS.items():
                if plegado in variantes:
                    mapa[nombre] = interno
                    break

        faltan = [c for c in REQUIRED if c not in mapa.values()]
        if faltan:
            raise SystemExit(
                "Al archivo le faltan columnas obligatorias: "
                + ", ".join(faltan)
                + f".\nEncontradas: {', '.join(lector.fieldnames)}"
            )

        filas = []
        for numero, crudo in enumerate(lector, start=2):   # 1 es el encabezado
            limpio = {}
            for nombre, valor in crudo.items():
                interno = mapa.get(nombre)
                if interno:
                    limpio[interno] = (valor or "").strip()
            filas.append(Fila(numero, limpio))
    return filas, set(mapa.values())


def parse_fecha(texto, hoy):
    for formato in DATE_FORMATS:
        try:
            d = datetime.strptime(texto, formato).date()
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"fecha ilegible: «{texto}»")
    if d > hoy:
        raise ValueError(f"fecha en el futuro: {d.isoformat()}")
    if d.year < 2000:
        raise ValueError(f"fecha demasiado vieja: {d.isoformat()}")
    return d.isoformat()


def validar(filas, hoy):
    """Marca cada fila como legible o no, y le anota los huecos."""
    for fila in filas:
        d = fila.crudo

        for campo in REQUIRED:
            if not d.get(campo):
                fila.error = f"falta {campo}"
                break
        if fila.error:
            continue

        try:
            d["fecha"] = parse_fecha(d["fecha"], hoy)
        except ValueError as exc:
            fila.error = str(exc)
            continue

        if d.get("precio"):
            try:
                d["precio_cents"] = parse_money(d["precio"])
            except MoneyError as exc:
                fila.error = f"precio ilegible: {exc}"
                continue
        else:
            d["precio_cents"] = 0
            fila.avisos.append("sin precio: entra en 0")

        # Del telefono para abajo, nada tumba el renglon: son huecos,
        # y un hueco visible vale mas que un renglon rechazado.
        d["phone"] = d["phone_display"] = None
        if d.get("telefono"):
            try:
                d["phone"], d["phone_display"] = normalize_phone(d["telefono"])
            except PhoneError:
                fila.avisos.append(f"telefono ilegible «{d['telefono']}»: entra sin telefono")
        else:
            fila.avisos.append("sin telefono")

        d["size"] = SIZES.get(fold(d.get("tamano")))
        if d.get("tamano") and not d["size"]:
            fila.avisos.append(f"tamano desconocido «{d['tamano']}»: entra sin tamano")
        elif not d.get("tamano"):
            fila.avisos.append("sin tamano")


def planear(filas):
    """Arma, en memoria, lo que habria que crear. Sigue sin tocar la base."""
    buenas = [f for f in filas if not f.error]

    clientes = {}       # clave -> {name, phone, phone_display, mascotas}
    servicios = defaultdict(Counter)
    visitas = defaultdict(list)

    for fila in buenas:
        d = fila.crudo
        # Si el telefono esta, manda: es lo unico que distingue de
        # verdad a dos personas que se llaman igual.
        ident = d["phone"] or f"nombre:{key(d['cliente'])}"
        cliente = clientes.setdefault(ident, {
            "name": d["cliente"].strip(),
            "phone": d["phone"],
            "phone_display": d["phone_display"],
            "mascotas": {},
            "renglones": 0,
        })
        cliente["renglones"] += 1
        # Un renglon posterior puede traer el telefono que faltaba antes.
        if not cliente["phone"] and d["phone"]:
            cliente["phone"] = d["phone"]
            cliente["phone_display"] = d["phone_display"]

        mascota = cliente["mascotas"].setdefault(key(d["mascota"]), {
            "name": d["mascota"].strip(), "size": None, "breed": None,
        })
        if d["size"] and not mascota["size"]:
            mascota["size"] = d["size"]
        if d.get("raza") and not mascota["breed"]:
            mascota["breed"] = d["raza"].strip()

        # Agrupado por talla: un cuaderno de peluqueria cobra el bano
        # a 15, 18 y 25 segun el perro, y esos tres numeros son la
        # tabla de precios, no ruido alrededor de un promedio.
        servicios[key(d["servicio"])][(d["size"] or "any", d["precio_cents"])] += 1
        visitas[(ident, d["fecha"])].append((
            key(d["mascota"]), key(d["servicio"]), d["precio_cents"],
            d.get("notas") or "",
        ))

    # El precio de lista sale del mas repetido en el cuaderno para cada
    # talla: no es un invento, es lo que dice el papel treinta veces.
    # Se reporta igual, para que el duenio lo confirme antes de cobrar.
    catalogo = {}
    for clave, cuenta in servicios.items():
        por_talla = defaultdict(Counter)
        for (talla, cents), veces in cuenta.items():
            por_talla[talla][cents] += veces

        precios = {}
        for talla, montos in por_talla.items():
            cents, veces = montos.most_common(1)[0]
            precios[talla] = {"cents": cents, "veces": veces,
                              "total": sum(montos.values())}

        # El catalogo es 'un precio unico' O 'un precio por talla',
        # nunca los dos: la pantalla de servicios decide cual mostrar
        # por la ausencia de 'any', y guardar una que tenga las dos
        # borraria las de talla sin avisar.
        montos = {p["cents"] for p in precios.values()}
        if len(montos) == 1:
            # Todas las tallas cobran igual: una sola linea lo dice.
            precios = {"any": {
                "cents": montos.pop(),
                "veces": sum(p["veces"] for p in precios.values()),
                "total": sum(p["total"] for p in precios.values())}}
        elif len(precios) > 1:
            # Hay tabla por talla. Los renglones sin talla no pueden
            # dictar un precio de reserva: taparia con un numero lo que
            # en realidad es 'falta saber de que tamanio es el perro'.
            precios.pop("any", None)

        catalogo[clave] = {"name": clave, "precios": precios,
                           "total": sum(cuenta.values())}

    return clientes, catalogo, visitas


def nombre_original(filas, campo, clave):
    for fila in filas:
        if not fila.error and key(fila.crudo.get(campo, "")) == clave:
            return fila.crudo[campo].strip()
    return clave


def escribir(conn, filas, clientes, catalogo, visitas):
    """El unico lugar que toca la base. Todo en una transaccion."""
    cur = conn.cursor()
    hechos = Counter()

    # --- Servicios ---
    ids_servicio = {}
    for clave, datos in catalogo.items():
        nombre = nombre_original(filas, "servicio", clave)
        row = cur.execute(
            "SELECT id FROM service WHERE name = ? COLLATE NOCASE", (nombre,)
        ).fetchone()
        if row:
            ids_servicio[clave] = row[0]
            continue
        cur.execute("INSERT INTO service (name) VALUES (?)", (nombre,))
        ids_servicio[clave] = cur.lastrowid
        for talla, precio in datos["precios"].items():
            cur.execute(
                "INSERT INTO service_price (service_id, size, price_cents) "
                "VALUES (?, ?, ?)",
                (ids_servicio[clave], talla, precio["cents"]),
            )
        hechos["servicios"] += 1

    # --- Clientes y mascotas ---
    ids_cliente, ids_mascota = {}, {}
    for ident, datos in clientes.items():
        row = None
        if datos["phone"]:
            row = cur.execute(
                "SELECT id FROM client WHERE phone = ? AND deleted_at IS NULL",
                (datos["phone"],),
            ).fetchone()
        if row is None:
            row = cur.execute(
                "SELECT id FROM client "
                " WHERE name = ? COLLATE NOCASE AND deleted_at IS NULL"
                "   AND (phone IS NULL OR ? IS NULL OR phone = ?)",
                (datos["name"], datos["phone"], datos["phone"]),
            ).fetchone()

        if row:
            ids_cliente[ident] = row[0]
            # Completar un hueco nunca pisa un dato que ya estaba.
            if datos["phone"]:
                cur.execute(
                    "UPDATE client SET phone = ?, phone_display = ?,"
                    "       updated_at = datetime('now')"
                    " WHERE id = ? AND phone IS NULL",
                    (datos["phone"], datos["phone_display"], row[0]),
                )
        else:
            cur.execute(
                "INSERT INTO client (name, phone, phone_display) VALUES (?, ?, ?)",
                (datos["name"], datos["phone"], datos["phone_display"]),
            )
            ids_cliente[ident] = cur.lastrowid
            hechos["clientes"] += 1

        for clave, mascota in datos["mascotas"].items():
            row = cur.execute(
                "SELECT id, size FROM pet"
                " WHERE client_id = ? AND name = ? COLLATE NOCASE"
                "   AND deleted_at IS NULL",
                (ids_cliente[ident], mascota["name"]),
            ).fetchone()
            if row:
                ids_mascota[(ident, clave)] = row[0]
                if mascota["size"] and row[1] is None:
                    cur.execute(
                        "UPDATE pet SET size = ?, updated_at = datetime('now')"
                        " WHERE id = ?", (mascota["size"], row[0]))
                continue
            cur.execute(
                "INSERT INTO pet (client_id, name, size, breed) VALUES (?, ?, ?, ?)",
                (ids_cliente[ident], mascota["name"], mascota["size"],
                 mascota["breed"]),
            )
            ids_mascota[(ident, clave)] = cur.lastrowid
            hechos["mascotas"] += 1

    # --- Visitas ---
    for (ident, fecha), lineas in sorted(visitas.items()):
        client_id = ids_cliente[ident]
        # Volver a pasar el mismo cuaderno reusa la visita que ya se
        # creo para ese cliente ese dia, en vez de duplicarla.
        row = cur.execute(
            "SELECT id FROM visit"
            " WHERE client_id = ? AND visit_date = ? AND source = 'import'"
            "   AND deleted_at IS NULL",
            (client_id, fecha),
        ).fetchone()
        if row:
            visit_id = row[0]
        else:
            notas = next((n for *_, n in lineas if n), None)
            cur.execute(
                "INSERT INTO visit (client_id, visit_date, status, notes, source)"
                " VALUES (?, ?, 'completed', ?, 'import')",
                (client_id, fecha, notas),
            )
            visit_id = cur.lastrowid
            hechos["visitas"] += 1

        for mascota, servicio, cents, _ in lineas:
            antes = conn.total_changes
            cur.execute(
                "INSERT OR IGNORE INTO visit_service"
                " (visit_id, pet_id, service_id, price_cents) VALUES (?, ?, ?, ?)",
                (visit_id, ids_mascota[(ident, mascota)],
                 ids_servicio[servicio], cents),
            )
            if conn.total_changes > antes:
                hechos["lineas"] += 1

    return hechos


def informe(filas, clientes, catalogo, visitas, hechos=None):
    buenas = [f for f in filas if not f.error]
    malas = [f for f in filas if f.error]
    con_aviso = [f for f in buenas if f.avisos]

    print(f"\nRenglones leidos: {len(filas)}")
    print(f"  se pueden importar: {len(buenas)}")
    print(f"  no se pueden leer:  {len(malas)}")

    sin_tel = sum(1 for c in clientes.values() if not c["phone"])
    sin_talla = sum(1 for c in clientes.values()
                    for m in c["mascotas"].values() if not m["size"])
    mascotas = sum(len(c["mascotas"]) for c in clientes.values())

    print(f"\nSale de ahi:")
    print(f"  {len(clientes)} clientes ({sin_tel} sin telefono)")
    print(f"  {mascotas} mascotas ({sin_talla} sin tamano)")
    print(f"  {len(visitas)} visitas")
    print(f"  {len(catalogo)} servicios")

    if catalogo:
        from app.money import format_money
        etiquetas = {"small": "pequeno", "medium": "mediano",
                     "large": "grande", "any": "cualquier talla"}
        print("\nPrecio de lista que se propone, del mas repetido en el papel:")
        for datos in sorted(catalogo.values(), key=lambda d: -d["total"]):
            print(f"  {nombre_original(filas, 'servicio', datos['name'])}")
            for talla in ("any", "small", "medium", "large"):
                precio = datos["precios"].get(talla)
                if precio:
                    plural = "renglon" if precio["total"] == 1 else "renglones"
                    print(f"      {etiquetas[talla]:16}"
                          f" {format_money(precio['cents']):>9}"
                          f"   ({precio['veces']} de {precio['total']} {plural})")
        print("  Revisalo en Servicios antes de cobrar con el.")

    if con_aviso:
        print(f"\nEntran con un hueco a la vista ({len(con_aviso)} renglones):")
        for fila in con_aviso[:10]:
            print(f"  linea {fila.numero}: {'; '.join(fila.avisos)}")
        if len(con_aviso) > 10:
            print(f"  ... y {len(con_aviso) - 10} mas")

    if malas:
        print(f"\nNo entran ({len(malas)} renglones):")
        for fila in malas[:10]:
            print(f"  linea {fila.numero}: {fila.error}")
        if len(malas) > 10:
            print(f"  ... y {len(malas) - 10} mas")

    if hechos is not None:
        print("\nEscrito en la base:")
        for clave in ("clientes", "mascotas", "servicios", "visitas", "lineas"):
            print(f"  {hechos[clave]:5} {clave}")
        print("  (lo que ya existia se reuso, no se duplico)")


def guardar_rechazados(filas, destino):
    malas = [f for f in filas if f.error]
    if not malas:
        return None
    campos = list(COLUMNS) + ["motivo"]
    with open(destino, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=campos)
        w.writeheader()
        for fila in malas:
            w.writerow(dict({c: fila.crudo.get(c, "") for c in COLUMNS},
                            motivo=fila.error))
    return destino


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", help="el cuaderno exportado")
    ap.add_argument("--db", default=Config.DB_PATH)
    ap.add_argument("--commit", action="store_true",
                    help="escribir de verdad (por defecto solo informa)")
    ap.add_argument("--rechazados", default=None,
                    help="donde dejar los renglones ilegibles (por defecto, al lado del CSV)")
    args = ap.parse_args()

    origen = Path(args.csv)
    if not origen.exists():
        raise SystemExit(f"No existe el archivo: {origen}")

    filas, _ = leer(origen)
    validar(filas, date.today())
    clientes, catalogo, visitas = planear(filas)

    hechos = None
    if args.commit:
        import sqlite3
        if not Path(args.db).exists():
            raise SystemExit(f"No existe la base: {args.db}")

        # Un respaldo aparte del diario: si el cuaderno entra torcido,
        # el de antes de importar es el que se quiere de vuelta.
        carpeta = backups.folder_for(args.db)
        carpeta.mkdir(parents=True, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        respaldo = carpeta / f"{Path(args.db).stem}-antes-de-importar-{marca}.db"
        backups.make(args.db, respaldo)
        print(f"Respaldo antes de importar: {respaldo}")

        conn = sqlite3.connect(args.db)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                hechos = escribir(conn, filas, clientes, catalogo, visitas)
        finally:
            conn.close()

    informe(filas, clientes, catalogo, visitas, hechos)

    destino = Path(args.rechazados) if args.rechazados else \
        origen.with_name(origen.stem + "-rechazados.csv")
    salida = guardar_rechazados(filas, destino)
    if salida:
        print(f"\nRenglones a corregir: {salida}")
        print("Arreglalos ahi y pasa ESE archivo; lo ya importado no se duplica.")

    if not args.commit:
        print("\nNo se escribio nada. Para hacerlo de verdad:")
        print(f"    python scripts/import_csv.py {origen} --commit")


if __name__ == "__main__":
    main()
