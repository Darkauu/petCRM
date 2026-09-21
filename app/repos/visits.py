"""Visitas: la cabecera y sus lineas de servicio.

El precio se congela en visit_service al momento de guardar. Cambiar el
catalogo manana no reescribe lo que ya se cobro.
"""
from app.clock import SQL_TODAY
from app.database import execute, query_all, query_one, transaction

_LIST_SQL = """
    SELECT v.id, v.visit_date, v.notes,
           c.id   AS client_id,
           c.name AS client_name,
           c.phone,
           COALESCE(t.total_cents, 0) AS total_cents,
           (SELECT REPLACE(GROUP_CONCAT(DISTINCT p.name), ',', ', ')
              FROM visit_service vs
              JOIN pet p ON p.id = vs.pet_id
             WHERE vs.visit_id = v.id) AS pet_names
    FROM visit v
    JOIN client c ON c.id = v.client_id
    LEFT JOIN v_visit_total t ON t.visit_id = v.id
    WHERE v.deleted_at IS NULL
      {extra}
    ORDER BY v.visit_date DESC, v.id DESC
    LIMIT ?
"""


def list_for_date(day, limit=100):
    return query_all(_LIST_SQL.format(extra="AND v.visit_date = ?"), (day, limit))


def list_for_client(client_id, limit=20):
    return query_all(
        _LIST_SQL.format(extra="AND v.client_id = ?"), (client_id, limit)
    )


def day_total(day):
    row = query_one(
        """
        SELECT COUNT(*) AS visits, COALESCE(SUM(t.total_cents), 0) AS cents
        FROM visit v
        LEFT JOIN v_visit_total t ON t.visit_id = v.id
        WHERE v.deleted_at IS NULL AND v.visit_date = ?
        """,
        (day,),
    )
    return (row["visits"], row["cents"]) if row else (0, 0)


def get(visit_id):
    return query_one(
        """
        SELECT v.*, c.name AS client_name
        FROM visit v
        JOIN client c ON c.id = v.client_id
        WHERE v.id = ? AND v.deleted_at IS NULL
        """,
        (visit_id,),
    )


def lines_for(visit_id):
    return query_all(
        """
        SELECT vs.pet_id, vs.service_id, vs.price_cents,
               p.name AS pet_name, s.name AS service_name
        FROM visit_service vs
        JOIN pet p     ON p.id = vs.pet_id
        JOIN service s ON s.id = vs.service_id
        WHERE vs.visit_id = ?
        ORDER BY p.name COLLATE NOCASE, s.name COLLATE NOCASE
        """,
        (visit_id,),
    )


def last_prices(client_id):
    """{(pet_id, service_id): centavos} del ultimo cobro a cada mascota.

    Es lo que hace rapido el caso repetido: el precio que sale precargado
    no es el de lista, es el que se le cobro a ESE perro la ultima vez.
    Requiere SQLite 3.25+ por la funcion de ventana.
    """
    rows = query_all(
        """
        SELECT pet_id, service_id, price_cents FROM (
            SELECT vs.pet_id, vs.service_id, vs.price_cents,
                   ROW_NUMBER() OVER (
                       PARTITION BY vs.pet_id, vs.service_id
                       ORDER BY v.visit_date DESC, vs.id DESC
                   ) AS rn
            FROM visit_service vs
            JOIN visit v ON v.id = vs.visit_id AND v.deleted_at IS NULL
            JOIN pet p   ON p.id = vs.pet_id
            WHERE p.client_id = ?
        ) WHERE rn = 1
        """,
        (client_id,),
    )
    return {(r["pet_id"], r["service_id"]): r["price_cents"] for r in rows}


def recent_clients(limit=8):
    """Los ultimos atendidos: el caso repetido se resuelve con un toque."""
    return query_all(
        """
        SELECT c.id, c.name, c.phone, c.phone_display,
               MAX(v.visit_date) AS last_visit_date,
               (SELECT REPLACE(GROUP_CONCAT(DISTINCT p.name), ',', ', ')
                  FROM pet p
                 WHERE p.client_id = c.id AND p.deleted_at IS NULL) AS pet_names
        FROM client c
        JOIN visit v ON v.client_id = c.id AND v.deleted_at IS NULL
        WHERE c.deleted_at IS NULL
        GROUP BY c.id
        ORDER BY last_visit_date DESC, v.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def create(client_id, visit_date, notes, lines):
    with transaction():
        cur = execute(
            """
            INSERT INTO visit (client_id, visit_date, notes, status)
            VALUES (?, ?, ?, 'completed')
            """,
            (client_id, visit_date, notes),
        )
        visit_id = cur.lastrowid
        _write_lines(visit_id, lines)
    return visit_id


def update(visit_id, visit_date, notes, lines):
    with transaction():
        execute(
            """
            UPDATE visit
               SET visit_date = ?, notes = ?, updated_at = datetime('now')
             WHERE id = ? AND deleted_at IS NULL
            """,
            (visit_date, notes, visit_id),
        )
        execute("DELETE FROM visit_service WHERE visit_id = ?", (visit_id,))
        _write_lines(visit_id, lines)


def _write_lines(visit_id, lines):
    for pet_id, service_id, price_cents in lines:
        execute(
            """
            INSERT INTO visit_service (visit_id, pet_id, service_id, price_cents)
            VALUES (?, ?, ?, ?)
            """,
            (visit_id, pet_id, service_id, price_cents),
        )


def archive(visit_id):
    execute(
        "UPDATE visit SET deleted_at = datetime('now') WHERE id = ?", (visit_id,)
    )


def count_today():
    row = query_one(
        f"SELECT COUNT(*) AS n FROM visit "
        f"WHERE deleted_at IS NULL AND visit_date = {SQL_TODAY}"
    )
    return row["n"] if row else 0
