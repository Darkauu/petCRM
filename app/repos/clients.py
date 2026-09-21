"""Consultas de clientes. SQL crudo, sin ORM."""
import re

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
