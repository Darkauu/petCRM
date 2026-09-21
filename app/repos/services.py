"""Catalogo de servicios y su tabla de precios.

Un servicio tiene o bien un precio unico (size='any') o bien un precio
por talla. La app busca primero la talla exacta y cae a 'any'.
"""
from app.database import execute, query_all, query_one, transaction


def list_all(include_inactive=False):
    where = "" if include_inactive else "WHERE is_active = 1"
    return query_all(
        f"SELECT * FROM service {where} ORDER BY is_active DESC, name COLLATE NOCASE"
    )


def get(service_id):
    return query_one("SELECT * FROM service WHERE id = ?", (service_id,))


def prices_map(service_ids=None):
    """{service_id: {size: price_cents}} para pintar el catalogo de un tiro."""
    rows = query_all(
        "SELECT service_id, size, price_cents FROM service_price"
    )
    out = {}
    for row in rows:
        if service_ids is not None and row["service_id"] not in service_ids:
            continue
        out.setdefault(row["service_id"], {})[row["size"]] = row["price_cents"]
    return out


def prices_for(service_id):
    rows = query_all(
        "SELECT size, price_cents FROM service_price WHERE service_id = ?",
        (service_id,),
    )
    return {row["size"]: row["price_cents"] for row in rows}


def price_for(service_id, size):
    """Precio vigente: talla exacta, si no 'any', si no None.

    Es el precio de catalogo. Lo que se cobra en una visita se congela
    aparte, en visit_service.
    """
    row = query_one(
        """
        SELECT price_cents FROM service_price
         WHERE service_id = ? AND size IN (?, 'any')
         ORDER BY CASE size WHEN 'any' THEN 1 ELSE 0 END
         LIMIT 1
        """,
        (service_id, size),
    )
    return row["price_cents"] if row else None


def create(name, description, prices):
    with transaction():
        cur = execute(
            "INSERT INTO service (name, description) VALUES (?, ?)",
            (name, description),
        )
        service_id = cur.lastrowid
        _write_prices(service_id, prices)
    return service_id


def update(service_id, name, description, prices, is_active=1):
    with transaction():
        execute(
            """
            UPDATE service
               SET name = ?, description = ?, is_active = ?,
                   updated_at = datetime('now')
             WHERE id = ?
            """,
            (name, description, is_active, service_id),
        )
        execute("DELETE FROM service_price WHERE service_id = ?", (service_id,))
        _write_prices(service_id, prices)


def _write_prices(service_id, prices):
    for size, cents in prices.items():
        execute(
            """
            INSERT INTO service_price (service_id, size, price_cents)
            VALUES (?, ?, ?)
            """,
            (service_id, size, cents),
        )


def set_active(service_id, is_active):
    """Un servicio no se borra: se saca del catalogo. El historico lo referencia."""
    execute(
        "UPDATE service SET is_active = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if is_active else 0, service_id),
    )


def count_active():
    row = query_one("SELECT COUNT(*) AS n FROM service WHERE is_active = 1")
    return row["n"] if row else 0
