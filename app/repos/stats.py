"""Agregados para el resumen.

Pocas cifras, ciertas y accionables. Todo lo que cuenta plata filtra
por status='completed' y deleted_at IS NULL: una visita eliminada o no
concretada no puede inflar el total.
"""
from app.clock import SQL_TODAY, days_between, today, weekday_of
from app.database import query_all, query_one

# Condicion comun: la visita existe, cuenta y cae en el rango.
_REAL_VISIT = """
    v.deleted_at IS NULL
    AND v.status = 'completed'
    AND v.visit_date BETWEEN ? AND ?
"""


def period_summary(desde, hasta):
    """Cuanto trabajo y cuanto facturo en el rango."""
    row = query_one(
        f"""
        SELECT COUNT(DISTINCT v.id)        AS visits,
               COUNT(DISTINCT vs.pet_id)   AS pets,
               COUNT(DISTINCT v.client_id) AS clients,
               COALESCE(SUM(vs.price_cents), 0) AS cents
        FROM visit v
        LEFT JOIN visit_service vs ON vs.visit_id = v.id
        WHERE {_REAL_VISIT}
        """,
        (desde, hasta),
    )
    return {
        "visits": row["visits"] or 0,
        "pets": row["pets"] or 0,
        "clients": row["clients"] or 0,
        "cents": row["cents"] or 0,
    }


def services_breakdown(desde, hasta):
    """Que servicios pesan mas, por plata y no solo por conteo."""
    return query_all(
        f"""
        SELECT s.id, s.name,
               COUNT(*)              AS times,
               SUM(vs.price_cents)   AS cents
        FROM visit_service vs
        JOIN visit v   ON v.id = vs.visit_id
        JOIN service s ON s.id = vs.service_id
        WHERE {_REAL_VISIT}
        GROUP BY s.id
        ORDER BY cents DESC, times DESC
        """,
        (desde, hasta),
    )


def client_split(desde, hasta):
    """Cuantos vinieron por primera vez y cuantos ya venian."""
    row = query_one(
        f"""
        SELECT COUNT(DISTINCT v.client_id) AS served,
               COUNT(DISTINCT CASE WHEN f.first_date BETWEEN ? AND ?
                                   THEN v.client_id END) AS nuevos
        FROM visit v
        JOIN (
            SELECT client_id, MIN(visit_date) AS first_date
            FROM visit
            WHERE deleted_at IS NULL AND status = 'completed'
            GROUP BY client_id
        ) f ON f.client_id = v.client_id
        WHERE {_REAL_VISIT}
        """,
        (desde, hasta, desde, hasta),
    )
    served = row["served"] or 0
    nuevos = row["nuevos"] or 0
    return {"served": served, "nuevos": nuevos, "recurrentes": served - nuevos}


def overdue_clients(after_days, limit=20):
    """Los que ya deberian haber vuelto, del mas atrasado al menos.

    Se mide por cliente y no por mascota: a quien se le escribe es a la
    persona. Si alguno de sus perros vino hace poco, el cliente no esta
    atrasado. Quien nunca ha venido no aparece: no dejo de venir.
    """
    return query_all(
        f"""
        SELECT c.id, c.name, c.phone, c.phone_display,
               MAX(lv.last_visit_date) AS last_visit_date,
               CAST(julianday({SQL_TODAY})
                    - julianday(MAX(lv.last_visit_date)) AS INTEGER) AS days,
               (SELECT REPLACE(GROUP_CONCAT(DISTINCT p2.name), ',', ', ')
                  FROM pet p2
                 WHERE p2.client_id = c.id
                   AND p2.deleted_at IS NULL AND p2.is_active = 1) AS pet_names
        FROM client c
        JOIN pet p ON p.client_id = c.id
                  AND p.deleted_at IS NULL AND p.is_active = 1
        JOIN v_pet_last_visit lv ON lv.pet_id = p.id
        WHERE c.deleted_at IS NULL AND lv.last_visit_date IS NOT NULL
        GROUP BY c.id
        HAVING CAST(julianday({SQL_TODAY})
                    - julianday(MAX(lv.last_visit_date)) AS INTEGER) > ?
        ORDER BY days DESC
        LIMIT ?
        """,
        (after_days, limit),
    )


def overdue_count(after_days):
    row = query_one(
        f"""
        SELECT COUNT(*) AS n FROM (
            SELECT c.id
            FROM client c
            JOIN pet p ON p.client_id = c.id
                      AND p.deleted_at IS NULL AND p.is_active = 1
            JOIN v_pet_last_visit lv ON lv.pet_id = p.id
            WHERE c.deleted_at IS NULL AND lv.last_visit_date IS NOT NULL
            GROUP BY c.id
            HAVING CAST(julianday({SQL_TODAY})
                        - julianday(MAX(lv.last_visit_date)) AS INTEGER) > ?
        )
        """,
        (after_days,),
    )
    return row["n"] if row else 0


# ---- Huecos en la data ---------------------------------------------------
# Una cifra construida sobre registros incompletos miente mejor que un
# numero ausente. Estas dos consultas existen para que el hueco se vea.

def days_without_records(desde, hasta, working_days):
    """Dias del rango, de los que abre, sin una sola visita registrada.

    No afirma que trabajo ese dia: afirma que no hay registro. El
    calendario de apertura lo pone el duenio en Ajustes.

    El rango se corta en hoy: los dias que todavia no han pasado no son
    un hueco, y en la semana en curso serian casi todos.
    """
    end = min(hasta, today())
    if end < desde:
        return []

    rows = query_all(
        """
        SELECT DISTINCT visit_date FROM visit
        WHERE deleted_at IS NULL AND visit_date BETWEEN ? AND ?
        """,
        (desde, end),
    )
    recorded = {row["visit_date"] for row in rows}
    return [
        day for day in days_between(desde, end)
        if day not in recorded and weekday_of(day) in working_days
    ]


def visits_without_services(desde, hasta):
    """Visitas sin una sola linea: el total del dia las cuenta en cero."""
    return query_all(
        f"""
        SELECT v.id, v.visit_date, c.name AS client_name
        FROM visit v
        JOIN client c ON c.id = v.client_id
        LEFT JOIN visit_service vs ON vs.visit_id = v.id
        WHERE {_REAL_VISIT}
        GROUP BY v.id
        HAVING COUNT(vs.id) = 0
        ORDER BY v.visit_date DESC
        """,
        (desde, hasta),
    )
