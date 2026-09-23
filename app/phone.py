"""Normalizacion de telefonos a E.164 (Panama por defecto).

Sin esto el mismo cliente entra tres veces como 6123-4567,
61234567 y +507 6123 4567, y la segmentacion se vuelve basura.
"""
import re

COUNTRY_CODE = "507"


class PhoneError(ValueError):
    pass


def format_phone(e164, country_code=COUNTRY_CODE):
    """'+50761234567' -> '6123-4567'"""
    if not e164:
        return ""
    digits = e164.lstrip("+")
    if digits.startswith(country_code):
        digits = digits[len(country_code):]
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:]}"
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return digits


def normalize_phone(text, country_code=COUNTRY_CODE):
    """Devuelve (e164, display) ya en formato de la casa.

    '61234567', '+507 6123 4567' y '6123-4567' son el mismo numero y
    se guardan y se ven igual: 6123-4567. Antes se conservaba lo que
    cada quien habia tecleado, y la misma lista mostraba tres formas
    distintas del mismo tipo de numero.
    """
    if text is None or not str(text).strip():
        raise PhoneError("El telefono es obligatorio.")

    display = str(text).strip()
    digits = re.sub(r"\D", "", display)

    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith(country_code) and len(digits) > 8:
        digits = digits[len(country_code):]

    if len(digits) == 8 and digits[0] == "6":       # movil
        pass
    elif len(digits) == 7:                          # fijo
        pass
    else:
        raise PhoneError(
            f"Numero invalido: {display}. "
            "Se espera 8 digitos para movil (6XXXXXXX) o 7 para fijo."
        )

    e164 = f"+{country_code}{digits}"
    return e164, format_phone(e164, country_code)


def init_app(app):
    app.jinja_env.filters["phone"] = format_phone