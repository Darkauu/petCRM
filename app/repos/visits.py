"""Visitas: la cabecera y sus lineas de servicio.

Dos momentos distintos, porque asi funciona el negocio:

  - Se RECIBE la mascota      -> la visita nace 'pending'.
  - Se ENTREGA y se cobra     -> pasa a 'completed'.
  - Se la llevan sin atender  -> 'cancelled'.

Mientras esta pendiente la visita existe pero no es plata: no suma en
ningun total. Solo 'completed' cuenta.

El precio se congela en visit_service al momento de guardar. Cambiar el
catalogo manana no reescribe lo que ya se cobro.
"""
from app.clock import SQL_SHIFT, SQL_TODAY
from app.database import execute, query_all, query_one, transaction

_LIST_SQL = f"""
    SELECT v.id, v.visit_date, v.notes, v.status,
           -- Hora en que se recibio, en hora de Panama.
           strftime('%H:%M', v.created_at, {SQL_SHIFT}) AS hora,
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
      {{extra}}
    ORDER BY v.visit_date DESC, v.id DESC
    LIMIT ?
"""


def list_for_date(day, limit=100):
    return query_all(_LIST_SQL.format(extra="AND v.visit_date = ?"), (day, limit))


def pending_all(limit=100):
    """Todas las pendientes de cobro, de la mas vieja a la mas nueva.

    Una pendiente de ayer es una senial de alarma: o se quedo sin
    cobrar, o se llevaron la mascota sin atender y nadie la cerro.
    """
    return query_all(
        _LIST_SQL.replace(
            "ORDER BY v.visit_date DESC, v.id DESC",
            "ORDER BY v.visit_date ASC, v.id ASC",
        ).format(extra="AND v.status = 'pending'"),
        (limit,),
    )


def pending_summary():
    """Cuantas pendientes hay y de cuando es la mas vieja."""
    row = query_one(
        """
        SELECT COUNT(*) AS n, MIN(visit_date) AS oldest
        FROM visit
        WHERE deleted_at IS NULL AND status = 'pending'
        """
    )
    return {"count": row["n"] or 0, "oldest": row["oldest"]} if row else {
        "count": 0, "oldest": None
    }


def list_for_client(client_id, limit=20):
    return query_all(
        _LIST_SQL.format(extra="AND v.client_id = ?"), (client_id, limit)
    )


def day_total(day):
    """Lo cobrado y lo que falta por cobrar, separados.

    Mezclarlos daria un numero mas grande y mas falso: el dinero de una
    visita pendiente todavia no entro a la caja.
    """
    row = query_one(
        """
        SELECT
          COUNT(CASE WHEN v.status = 'completed' THEN 1 END) AS done_n,
          COALESCE(SUM(CASE WHEN v.status = 'completed'
                            THEN t.total_cents END), 0)      AS done_cents,
          COUNT(CASE WHEN v.status = 'pending' THEN 1 END)   AS pend_n,
          COALESCE(SUM(CASE WHEN v.status = 'pending'
                            THEN t.total_cents END), 0)      AS pend_cents
        FROM visit v
        LEFT JOIN v_visit_total t ON t.visit_id = v.id
        WHERE v.deleted_at IS NULL AND v.visit_date = ?
        """,
        (day,),
    )
    if row is None:
        return {"done_n": 0, "done_cents": 0, "pend_n": 0, "pend_cents": 0}
    return dict(row)


def total_for(visit_id):
    row = query_one(
        "SELECT total_cents FROM v_visit_total WHERE visit_id = ?", (visit_id,)
    )
    return row["total_cents"] if row else 0


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
            JOIN visit v ON v.id = vs.visit_id
                        AND v.deleted_at IS NULL
                        AND v.status = 'completed'
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


def create(client_id, visit_date, notes, lines, status="pending"):
    with transaction():
        cur = execute(
            """
            INSERT INTO visit (client_id, visit_date, notes, status)
            VALUES (?, ?, ?, ?)
            """,
            (client_id, visit_date, notes, status),
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


def charge(visit_id):
    """Marca la visita como cobrada. Devuelve True si de verdad cambio.

    La condicion status='pending' hace el trabajo: si el boton se toca
    dos veces, o si dos pestanias hacen lo mismo, la segunda no vuelve
    a cobrar ni altera nada.
    """
    cur = execute(
        """
        UPDATE visit SET status = 'completed', updated_at = datetime('now')
         WHERE id = ? AND status = 'pending' AND deleted_at IS NULL
        """,
        (visit_id,),
    )
    return cur.rowcount > 0


def cancel(visit_id):
    """Se la llevaron sin atender: queda el registro, pero no cobra nada."""
    cur = execute(
        """
        UPDATE visit SET status = 'cancelled', updated_at = datetime('now')
         WHERE id = ? AND status = 'pending' AND deleted_at IS NULL
        """,
        (visit_id,),
    )
    return cur.rowcount > 0


def reopen(visit_id):
    """Vuelve a pendiente una visita cobrada o cancelada por error."""
    cur = execute(
        """
        UPDATE visit SET status = 'pending', updated_at = datetime('now')
         WHERE id = ? AND status IN ('completed', 'cancelled')
           AND deleted_at IS NULL
        """,
        (visit_id,),
    )
    return cur.rowcount > 0


def archive(visit_id):
    execute(
        "UPDATE visit SET deleted_at = datetime('now') WHERE id = ?", (visit_id,)
    )


def count_today():
    row = query_one(
        f"SELECT COUNT(*) AS n FROM visit "
        f"WHERE deleted_at IS NULL AND status = 'completed' "
        f"  AND visit_date = {SQL_TODAY}"
    )
    return row["n"] if row else 0
