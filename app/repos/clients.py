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
"""

# Cuantos clientes se traen de una. Con trescientos en la base, pintar
# la lista entera es medio megabyte de HTML en un celular que ya venia
# lento; lo que se busca casi siempre esta en la primera pagina o se
# encuentra escribiendo el nombre.
PAGINA = 10


def _busqueda(term):
    """(sql, params) del termino de busqueda. Vacio si no hay termino."""
    term = (term or "").strip()
    if not term:
        return "", []

    like = f"%{term}%"
    digits = re.sub(r"\D", "", term)
    phone_like = f"%{digits}%" if digits else None
    extra = """
      AND (c.name LIKE ? COLLATE NOCASE
           OR (? IS NOT NULL AND c.phone LIKE ?)
           OR EXISTS (SELECT 1 FROM pet p5
                      WHERE p5.client_id = c.id
                        AND p5.deleted_at IS NULL
                        AND p5.name LIKE ? COLLATE NOCASE))
    """
    return extra, [like, phone_like, phone_like, like]


def _envoltura(term):
    """La consulta de estado lista para filtrarse por sus columnas.

    El filtro por grupo mira 'days' y 'sizes', que son columnas
    calculadas: no existen todavia en el WHERE de adentro. Por eso la
    consulta se envuelve, y el filtro va afuera.
    """
    extra, params = _busqueda(term)
    return f"SELECT * FROM ({_STATUS_SQL.format(extra=extra)})", params


def list_with_status(term=None, claves=(), plazo=15, pagina=1, por_pagina=PAGINA):
    """Una pagina de clientes con su estado, ya filtrada en la base.

    'claves' son grupos de app/segments.py, y el usuario solo elige
    cuales: la condicion la pone el servidor.

    por_pagina=None trae todo, para cuando de verdad hace falta la
    lista completa (los envios, por ejemplo, que necesitan a todos los
    destinatarios, no a los diez primeros).
    """
    from app import segments

    base, params = _envoltura(term)
    cond, cond_params = segments.condicion(claves, plazo)
    if cond:
        base += f" WHERE {cond}"
        params = params + cond_params

    # Quien busca a quien escribirle quiere primero al que mas lleva
    # esperando; quien solo mira la lista, el orden alfabetico.
    if "escribir" in claves:
        base += " ORDER BY days DESC, name COLLATE NOCASE"
    else:
        base += " ORDER BY name COLLATE NOCASE"

    if por_pagina is None:
        return query_all(base, tuple(params))

    pagina = max(1, int(pagina or 1))
    return query_all(base + " LIMIT ? OFFSET ?",
                     tuple(params) + (por_pagina, (pagina - 1) * por_pagina))


def count_with_status(term=None, claves=(), plazo=15):
    """Cuantos hay en total con ese termino y esos grupos."""
    from app import segments

    base, params = _envoltura(term)
    cond, cond_params = segments.condicion(claves, plazo)
    if cond:
        base += f" WHERE {cond}"
        params = params + cond_params
    row = query_one(f"SELECT COUNT(*) AS n FROM ({base})", tuple(params))
    return row["n"] if row else 0


def group_counts(term, grupos, plazo):
    """El numero de cada pestania, en UNA sola consulta.

    Es la razon de que los criterios sean SQL y no funciones de Python:
    asi el panel no tiene que traerse la tabla entera para contar.
    """
    from app import segments

    base, params = _envoltura(term)
    piezas, todos_params = ["COUNT(*) AS total"], []
    for i, (clave, _etiqueta, _cond) in enumerate(grupos):
        cond, cond_params = segments.condicion([clave], plazo)
        piezas.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS g{i}")
        todos_params.extend(cond_params)

    row = query_one(f"SELECT {', '.join(piezas)} FROM ({base})",
                    tuple(todos_params) + tuple(params))
    if row is None:
        return {"": 0}
    out = {"": row["total"] or 0}
    for i, (clave, _etiqueta, _cond) in enumerate(grupos):
        out[clave] = row[f"g{i}"] or 0
    return out


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
