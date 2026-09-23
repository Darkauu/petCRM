"""Envios: el mismo mensaje a varios clientes, uno por uno.

WhatsApp no deja mandar en lote desde un programa, y ninguna vuelta
cambia eso: cada chat se abre por separado. Lo que si se puede quitar
es lo que de verdad cansa, que no son los toques sino redactar el mismo
mensaje seis veces y perder la cuenta de por quien se iba.

El sistema no manda nada. Arma el enlace con el mensaje ya escrito y lo
abre en WhatsApp; lo que sale del telefono lo manda la duenia, desde su
propio numero.
"""
from urllib.parse import quote

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from app import segments
from app.labels import first_name
from app.repos import outreach, settings

bp = Blueprint("outreach", __name__, url_prefix="/escribir")

# Los mismos criterios que las pestanias del panel de clientes: "los 4
# atrasados con perro pequenio" tiene que significar lo mismo en los dos
# lados. 'Datos incompletos' no esta a proposito: justamente son los que
# no tienen telefono.
GRUPOS = segments.COMUNES

MAX_MENSAJE = 900

EJEMPLO = ("Hola {cliente}, ¿cómo está {mascota}? Ya pasó un tiempo "
           "desde su último baño. Si quieres traerlo esta semana, "
           "tengo espacio. ¡Saludos!")


def personalizar(mensaje, row):
    """Reemplaza las marcas por los datos de esa persona.

    Son dos y nada mas. Un idioma de plantillas completo aqui seria
    poder escribir cualquier cosa y que reviente delante del cliente.

    {cliente} sale como nombre de pila: "Hola Ana" suena a la peluquera
    del barrio y "Hola Ana Vega" a una factura.
    """
    mascotas = row["pet_names"] or "tu mascota"
    return (mensaje
            .replace("{cliente}", first_name(row["name"]))
            .replace("{mascota}", mascotas))


def enlace(row, mensaje):
    """El wa.me con el texto ya puesto. quote() sobre el texto completo:
    un mensaje con & o # partiria la URL a la mitad."""
    texto = quote(personalizar(mensaje, row))
    return f"https://wa.me/{row['phone'][1:]}?text={texto}"


@bp.get("/")
def index():
    return render_template("outreach/list.html", rows=outreach.list_all())


@bp.route("/nuevo", methods=["GET", "POST"])
def create():
    plazo = settings.followup_days()

    # Se pueden combinar: "atrasados" Y "perros pequenios" es justo la
    # pregunta que se hace quien quiere mandar una promo de talla chica.
    elegidos = [g for g in request.values.getlist("g")
                if g in segments.CLAVES_COMUNES]

    rows = outreach.candidates(elegidos, plazo)
    cuentas = outreach.candidate_counts(GRUPOS, plazo)
    grupos = [{"key": clave, "label": label, "on": clave in elegidos,
               "count": cuentas.get(clave, 0)}
              for clave, label, _cond in GRUPOS]

    mensaje = (request.form.get("message") or "").strip()
    nombre = (request.form.get("name") or "").strip()

    if request.method == "GET" or request.form.get("refiltrar"):
        return render_template(
            "outreach/new.html", rows=rows, grupos=grupos, elegidos=elegidos,
            message=mensaje or EJEMPLO, name=nombre, errors={},
            ejemplo=rows[0] if rows else None, personalizar=personalizar,
        )

    errors = {}
    if not mensaje:
        errors["message"] = "Escribe el mensaje."
    elif len(mensaje) > MAX_MENSAJE:
        errors["message"] = f"Máximo {MAX_MENSAJE} caracteres."
    if not rows:
        errors["rows"] = "No hay nadie a quien escribirle con esos filtros."

    if errors:
        return render_template(
            "outreach/new.html", rows=rows, grupos=grupos, elegidos=elegidos,
            message=mensaje, name=nombre, errors=errors,
            ejemplo=rows[0] if rows else None, personalizar=personalizar,
        ), 400

    campaign_id = outreach.create(
        nombre or f"Envío del {_hoy()}",
        mensaje, [r["id"] for r in rows],
    )
    return redirect(url_for("outreach.send", campaign_id=campaign_id))


def _hoy():
    from app.clock import today
    from app.labels import short_date
    return short_date(today())


@bp.get("/<int:campaign_id>")
def send(campaign_id):
    campaign = outreach.get(campaign_id)
    if campaign is None:
        return render_template("errors/404.html"), 404

    row = outreach.next_target(campaign_id)
    avance = outreach.progress(campaign_id)

    if row is None:
        return render_template(
            "outreach/done.html", campaign=campaign, avance=avance,
            rows=outreach.targets(campaign_id),
        )

    return render_template(
        "outreach/send.html", campaign=campaign, row=row, avance=avance,
        texto=personalizar(campaign["message"], row),
        enlace=enlace(row, campaign["message"]),
    )


@bp.post("/<int:campaign_id>/marcar")
def mark(campaign_id):
    if outreach.get(campaign_id) is None:
        return render_template("errors/404.html"), 404

    raw = request.form.get("client_id") or ""
    if raw.isdigit():
        outreach.mark(campaign_id, int(raw),
                      skipped=bool(request.form.get("skip")))
    return redirect(url_for("outreach.send", campaign_id=campaign_id))


@bp.post("/<int:campaign_id>/rehacer")
def unmark(campaign_id):
    if outreach.get(campaign_id) is None:
        return render_template("errors/404.html"), 404

    raw = request.form.get("client_id") or ""
    if raw.isdigit():
        # Vuelve a la cola: si el envio ya estaba cerrado, se reabre,
        # porque si no el que vuelve no le tocaria nunca.
        outreach.unmark(campaign_id, int(raw))
        outreach.reopen(campaign_id)
    return redirect(url_for("outreach.send", campaign_id=campaign_id))


@bp.post("/<int:campaign_id>/cerrar")
def close(campaign_id):
    if outreach.get(campaign_id) is None:
        return render_template("errors/404.html"), 404
    outreach.close(campaign_id)
    flash("Envío cerrado.", "ok")
    return redirect(url_for("outreach.index"))


@bp.post("/<int:campaign_id>/eliminar")
def archive(campaign_id):
    if outreach.get(campaign_id) is None:
        return render_template("errors/404.html"), 404
    outreach.archive(campaign_id)
    flash("Envío eliminado.", "ok")
    return redirect(url_for("outreach.index"))
