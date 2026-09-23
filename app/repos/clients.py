"""Consultas de clientes. SQL crudo, sin ORM."""
import re

from app.clock import SQL_TODAY
from app.database import execute, query_all, query_one

# Se listan con las mascotas al lado porque el dueno no busca "Marta":
# busca "la duena de Toby".
_LIST_SQL = """
    SELECT c.id, c.name, c.phone, c.phone_display,
           COUNT(p.id)              AS pet_count,
           GROUP_CONCAT(p.name, ', ') AS pet_names
    FROM client c
    LEFT JOIN pet p ON p.client_id = c.id AND p.deleted_at IS NULL
    WHERE c.deleted_at IS NULL
      {extra}
    GROUP BY c.id
    ORDER BY c.name COLLATE NOCASE
    LIMIT ?
"""


def search(term=None, limit=60):
    """Busca por nombre de cliente, telefono o nombre de mascota."""
    term = (term or "").strip()
    if not term:
        return query_all(_LIST_SQL.format(extra=""), (limit,))

    like = f"%{term}%"
    digits = re.sub(r"\D", "", term)
    phone_like = f"%{digits}%" if digits else None

    extra = """
      AND (c.name LIKE ? COLLATE NOCASE
           OR (? IS NOT NULL AND c.phone LIKE ?)
           OR EXISTS (SELECT 1 FROM pet p2
                      WHERE p2.client_id = c.id
                        AND p2.deleted_at IS NULL
                        AND p2.name LIKE ? COLLATE NOCASE))
    """
    params = (like, phone_like, phone_like, like, limit)
    return query_all(_LIST_SQL.format(extra=extra), params)


# El panel de clientes tiene que responder "a quien le escribo hoy" sin
# entrar a cada ficha, asi que cada fila trae ya su estado: cuando vino
# por ultima vez, cuantos dias van, y de que tamanio son sus perros.
_STATUS_SQL = f"""
    SELECT c.id, c.name, c.phone, c.phone_display,
           (SELECT REPLACE(GROUP_CONCAT(DISTINCT p2.name), ',', ', ')
              FROM pet p2
             WHERE p2.client_id = c.id AND p2.deleted_at IS NULL) AS pet_names,
           (SELECT GROUP_CONCAT(DISTINCT p3.size)
              FROM pet p3
             WHERE p3.client_id = c.id AND p3.deleted_at IS NULL
               AND p3.is_active = 1) AS sizes,
           -- Lo que el cuaderno no traia. Se cuenta aqui para poder
           -- filtrarlo sin abrir ficha por ficha.
           (SELECT COUNT(*)
              FROM pet p4
             WHERE p4.client_id = c.id AND p4.deleted_at IS NULL
               AND p4.is_active = 1 AND p4.size IS NULL) AS pets_sin_talla,
           MAX(lv.last_visit_date) AS last_visit_date,
           CAST(julianday({SQL_TODAY})
                - julianday(MAX(lv.last_visit_date)) AS INTEGER) AS days
    FROM client c
    LEFT JOIN pet p ON p.client_id = c.id
                   AND p.deleted_at IS NULL AND p.is_active = 1
    LEFT JOIN v_pet_last_visit lv ON lv.pet_id = p.id
    WHERE c.deleted_at IS NULL
      {{extra}}
    GROUP BY c.id
    ORDER BY c.name COLLATE NOCASE
"""


def list_with_status(term=None):
    """Todos los clientes con su estado. El filtro se aplica despues.

    El termino de busqueda si va en SQL; el filtro por estado no, porque
    depende de un plazo que el duenio cambia y porque asi se pueden
    contar todos los grupos de una sola pasada, sin una consulta por
    cada pestania.
    """
    term = (term or "").strip()
    if not term:
        return query_all(_STATUS_SQL.format(extra=""))

    like = f"%{term}%"
    digits = re.sub(r"\D", "", term)
    phone_like = f"%{digits}%" if digits else None
    extra = """
      AND (c.name LIKE ? COLLATE NOCASE
           OR (? IS NOT NULL AND c.phone LIKE ?)
           OR EXISTS (SELECT 1 FROM pet p4
                      WHERE p4.client_id = c.id
                        AND p4.deleted_at IS NULL
                        AND p4.name LIKE ? COLLATE NOCASE))
    """
    return query_all(_STATUS_SQL.format(extra=extra),
                     (like, phone_like, phone_like, like))


def lifetime(client_id):
    """Cuanto ha dejado este cliente desde que llega. Solo cuenta lo
    cobrado: una visita pendiente todavia no es plata."""
    row = query_one(
        """
        SELECT COUNT(DISTINCT v.id) AS visits,
               COALESCE(SUM(vs.price_cents), 0) AS cents,
               MIN(v.visit_date) AS first_visit,
               MAX(v.visit_date) AS last_visit
        FROM visit v
        LEFT JOIN visit_service vs ON vs.visit_id = v.id
        WHERE v.client_id = ? AND v.deleted_at IS NULL
          AND v.status = 'completed'
        """,
        (client_id,),
    )
    return dict(row) if row else {"visits": 0, "cents": 0,
                                  "first_visit": None, "last_visit": None}


def get(client_id):
    return query_one(
        "SELECT * FROM client WHERE id = ? AND deleted_at IS NULL",
        (client_id,),
    )


def find_by_phone(e164):
    """Para avisar del duplicado antes de que reviente el indice unico."""
    return query_one(
        "SELECT id, name FROM client WHERE phone = ? AND deleted_at IS NULL",
        (e164,),
    )


def create(data):
    cur = execute(
        """
        INSERT INTO client (name, phone, phone_display, document, email,
                            address, notes)
        VALUES (:name, :phone, :phone_display, :document, :email,
                :address, :notes)
        """,
        data,
    )
    return cur.lastrowid


def update(client_id, data):
    params = dict(data, id=client_id)
    execute(
        """
        UPDATE client
           SET name = :name, phone = :phone, phone_display = :phone_display,
               document = :document, email = :email, address = :address,
               notes = :notes, updated_at = datetime('now')
         WHERE id = :id AND deleted_at IS NULL
        """,
        params,
    )


def archive(client_id):
    """Borrado logico. Nunca DELETE fisico: el historico de visitas cuelga de aqui."""
    execute(
        "UPDATE client SET deleted_at = datetime('now') WHERE id = ?",
        (client_id,),
    )


def count_active():
    row = query_one("SELECT COUNT(*) AS n FROM client WHERE deleted_at IS NULL")
    return row["n"] if row else 0
