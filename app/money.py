"""Dinero: internamente centavos (int), de cara al usuario dolares.

Nunca float. 15.10 * 100 en float da 1509.9999999999998.
"""
import re
from decimal import Decimal, InvalidOperation

_CLEAN = re.compile(r"[^\d.,-]")


class MoneyError(ValueError):
    pass


def parse_money(text):
    """'$15,50' -> 1550. Rechaza mas de dos decimales en vez de redondear."""
    if text is None:
        raise MoneyError("Monto vacio.")
    raw = _CLEAN.sub("", str(text).strip())
    if not raw:
        # Con el texto original: 'Monto vacio' a secas es desconcertante
        # cuando lo que se escribio fue 'quince dolares'.
        limpio = str(text).strip()
        raise MoneyError(f"Monto invalido: {limpio}" if limpio else "Monto vacio.")

    # Formato local: coma como decimal si no hay punto.
    if "," in raw and "." not in raw:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")

    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise MoneyError(f"Monto invalido: {text}")

    if value < 0:
        raise MoneyError("El monto no puede ser negativo.")
    if -value.as_tuple().exponent > 2:
        raise MoneyError("Maximo dos decimales.")

    return int(value * 100)


def format_money(cents, symbol=True):
    """1550 -> '$15.50'"""
    if cents is None:
        cents = 0
    value = Decimal(cents) / 100
    out = f"{value:,.2f}"
    return f"${out}" if symbol else out


def init_app(app):
    app.jinja_env.filters["money"] = format_money