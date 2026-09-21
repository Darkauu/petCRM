"""Consultas de mascotas. SQL crudo, sin ORM."""
from app.clock import SQL_TODAY
from app.database import execute, query_all, query_one

# v_pet_last_visit viene de la migracion 001 e incluye a las mascotas que
# nunca han venido (last_visit_date NULL). Ese NULL es informacion, no un
# hueco que haya que esconder.
_WITH_LAST_VISIT = f"""
    SELECT p.*,
           lv.last_visit_date,
           COALESCE(lv.visit_count, 0) AS visit_count,
           CAST(julianday({SQL_TODAY}) - julianday(lv.last_visit_date)
                AS INTEGER) AS days_since_visit
    FROM pet p
    LEFT JOIN v_pet_last_visit lv ON lv.pet_id = p.id
    WHERE p.deleted_at IS NULL
      {{extra}}
    ORDER BY p.name COLLATE NOCASE
"""


def list_for_client(client_id):
    return query_all(
        _WITH_LAST_VISIT.format(extra="AND p.client_id = ?"), (client_id,)
    )


def get(pet_id):
    return query_one(
        "SELECT * FROM pet WHERE id = ? AND deleted_at IS NULL", (pet_id,)
    )


def get_with_client(pet_id):
    return query_one(
        """
        SELECT p.*, c.name AS client_name, c.id AS client_id
        FROM pet p
        JOIN client c ON c.id = p.client_id
        WHERE p.id = ? AND p.deleted_at IS NULL AND c.deleted_at IS NULL
        """,
        (pet_id,),
    )


def create(data):
    cur = execute(
        """
        INSERT INTO pet (client_id, name, species, breed, size, sex,
                         birthdate, weight_kg, temperament, medical_notes,
                         is_active)
        VALUES (:client_id, :name, :species, :breed, :size, :sex,
                :birthdate, :weight_kg, :temperament, :medical_notes,
                :is_active)
        """,
        data,
    )
    return cur.lastrowid


def update(pet_id, data):
    params = dict(data, id=pet_id)
    execute(
        """
        UPDATE pet
           SET name = :name, species = :species, breed = :breed,
               size = :size, sex = :sex, birthdate = :birthdate,
               weight_kg = :weight_kg, temperament = :temperament,
               medical_notes = :medical_notes, is_active = :is_active,
               updated_at = datetime('now')
         WHERE id = :id AND deleted_at IS NULL
        """,
        params,
    )


def archive(pet_id):
    execute("UPDATE pet SET deleted_at = datetime('now') WHERE id = ?", (pet_id,))


def count_active():
    row = query_one(
        "SELECT COUNT(*) AS n FROM pet WHERE deleted_at IS NULL AND is_active = 1"
    )
    return row["n"] if row else 0
