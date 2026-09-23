"""Envios: escribirle el mismo mensaje a varios clientes, uno por uno.

El sistema no manda nada. Guarda el texto una sola vez, arma el enlace
de WhatsApp con el mensaje ya escrito y lleva la cuenta de por quien iba
la duenia. Lo que sale del telefono lo manda ella, desde su numero.
"""
from app.clock import SQL_TODAY
from app.database import execute, query_all, query_one, transaction

# Quien entra en un envio: con telefono, porque sin numero no hay a
# donde escribir, y sin haber pedido que no le escriban.
_CANDIDATOS_SQL = f"""
    SELECT c.id, c.name, c.phone, c.phone_display,
           (SELECT REPLACE(GROUP_CONCAT(DISTINCT p2.name), ',', ', ')
              FROM pet p2
             WHERE p2.client_id = c.id AND p2.deleted_at IS NULL
               AND p2.is_active = 1) AS pet_names,
           (SELECT GROUP_CONCAT(DISTINCT p3.size)
              FROM pet p3
             WHERE p3.client_id = c.id AND p3.deleted_at IS NULL
               AND p3.is_active = 1) AS sizes,
           MAX(lv.last_visit_date) AS last_visit_date,
           CAST(julianday({SQL_TODAY})
                - julianday(MAX(lv.last_visit_date)) AS INTEGER) AS days
    FROM client c
    LEFT JOIN pet p ON p.client_id = c.id
                   AND p.deleted_at IS NULL AND p.is_active = 1
    LEFT JOIN v_pet_last_visit lv ON lv.pet_id = p.id
    WHERE c.deleted_at IS NULL
      AND c.phone IS NOT NULL
      AND COALESCE(c.preferred_channel, 'whatsapp') <> 'none'
    GROUP BY c.id
"""


def candidates(claves=(), plazo=15):
    """Los que se pueden contactar, del mas atrasado al menos.

    Aqui SI se traen todos los que cumplen: son los destinatarios del
    envio, y mandarle a diez de cuarenta porque la pantalla pagina
    seria un error silencioso.
    """
    from app import segments

    base = f"SELECT * FROM ({_CANDIDATOS_SQL})"
    cond, params = segments.condicion(claves, plazo)
    if cond:
        base += f" WHERE {cond}"
    return query_all(base + " ORDER BY days DESC, name COLLATE NOCASE",
                     tuple(params))


def candidate_counts(grupos, plazo):
    """El numero de cada pestania, en una sola consulta."""
    from app import segments

    piezas, params = ["COUNT(*) AS total"], []
    for i, (clave, _etiqueta, _cond) in enumerate(grupos):
        cond, cond_params = segments.condicion([clave], plazo)
        piezas.append(f"SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS g{i}")
        params.extend(cond_params)

    row = query_one(
        f"SELECT {', '.join(piezas)} FROM ({_CANDIDATOS_SQL})", tuple(params))
    if row is None:
        return {}
    return {clave: (row[f"g{i}"] or 0)
            for i, (clave, _e, _c) in enumerate(grupos)}


def create(name, message, client_ids):
    with transaction():
        cur = execute(
            "INSERT INTO campaign (name, message) VALUES (?, ?)",
            (name, message),
        )
        campaign_id = cur.lastrowid
        for client_id in client_ids:
            execute(
                "INSERT OR IGNORE INTO campaign_target (campaign_id, client_id)"
                " VALUES (?, ?)",
                (campaign_id, client_id),
            )
    return campaign_id


def get(campaign_id):
    return query_one("SELECT * FROM campaign WHERE id = ?", (campaign_id,))


_TARGET_SQL = f"""
    SELECT t.id, t.client_id, t.sent_at, t.skipped_at,
           c.name, c.phone, c.phone_display,
           (SELECT REPLACE(GROUP_CONCAT(DISTINCT p.name), ',', ', ')
              FROM pet p
             WHERE p.client_id = c.id AND p.deleted_at IS NULL
               AND p.is_active = 1) AS pet_names,
           MAX(lv.last_visit_date) AS last_visit_date,
           CAST(julianday({SQL_TODAY})
                - julianday(MAX(lv.last_visit_date)) AS INTEGER) AS days
    FROM campaign_target t
    JOIN client c ON c.id = t.client_id
    LEFT JOIN pet p2 ON p2.client_id = c.id
                    AND p2.deleted_at IS NULL AND p2.is_active = 1
    LEFT JOIN v_pet_last_visit lv ON lv.pet_id = p2.id
    WHERE t.campaign_id = ?
      {{extra}}
    GROUP BY t.id
    ORDER BY days DESC, c.name COLLATE NOCASE
"""


def targets(campaign_id):
    return query_all(_TARGET_SQL.format(extra=""), (campaign_id,))


def next_target(campaign_id):
    """El siguiente al que le toca. None cuando no queda ninguno."""
    rows = query_all(
        _TARGET_SQL.format(
            extra="AND t.sent_at IS NULL AND t.skipped_at IS NULL"
        ) + " LIMIT 1",
        (campaign_id,),
    )
    return rows[0] if rows else None


def progress(campaign_id):
    row = query_one(
        """
        SELECT COUNT(*) AS total,
               SUM(sent_at IS NOT NULL)    AS enviados,
               SUM(skipped_at IS NOT NULL) AS saltados
        FROM campaign_target WHERE campaign_id = ?
        """,
        (campaign_id,),
    )
    total = row["total"] if row else 0
    enviados = (row["enviados"] or 0) if row else 0
    saltados = (row["saltados"] or 0) if row else 0
    return {
        "total": total,
        "enviados": enviados,
        "saltados": saltados,
        "hechos": enviados + saltados,
        "faltan": total - enviados - saltados,
    }


def mark(campaign_id, client_id, skipped=False):
    """Marca a uno como escrito o salteado. Volver a marcarlo no lo mueve.

    'AND sent_at IS NULL AND skipped_at IS NULL' es lo que hace que un
    doble toque, o un boton de atras, no reescriba la hora ni cambie
    una decision que ya se tomo.
    """
    campo = "skipped_at" if skipped else "sent_at"
    cur = execute(
        f"""
        UPDATE campaign_target
           SET {campo} = datetime('now')
         WHERE campaign_id = ? AND client_id = ?
           AND sent_at IS NULL AND skipped_at IS NULL
        """,
        (campaign_id, client_id),
    )
    return cur.rowcount > 0


def unmark(campaign_id, client_id):
    """Lo devuelve a la cola. Para el dedo que toca el boton de al lado.

    Sin esto, un toque errado deja a alguien fuera del envio para
    siempre, que es justo lo que este flujo prometia no hacer.
    """
    cur = execute(
        """
        UPDATE campaign_target SET sent_at = NULL, skipped_at = NULL
         WHERE campaign_id = ? AND client_id = ?
        """,
        (campaign_id, client_id),
    )
    return cur.rowcount > 0


def close(campaign_id):
    execute(
        "UPDATE campaign SET closed_at = datetime('now')"
        " WHERE id = ? AND closed_at IS NULL",
        (campaign_id,),
    )


def reopen(campaign_id):
    execute("UPDATE campaign SET closed_at = NULL WHERE id = ?", (campaign_id,))


def list_all(limit=30):
    """Los envios hechos, del mas nuevo al mas viejo."""
    return query_all(
        """
        SELECT c.*,
               COUNT(t.id) AS total,
               SUM(t.sent_at IS NOT NULL) AS enviados,
               -- 'Faltan' son los que no se han tocado. Un salteado ya
               -- se decidio: contarlo como pendiente pondria 'sin
               -- terminar' en un envio que si termino.
               SUM(t.sent_at IS NULL AND t.skipped_at IS NULL) AS faltan
        FROM campaign c
        LEFT JOIN campaign_target t ON t.campaign_id = c.id
        GROUP BY c.id
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ?
        """,
        (limit,),
    )


def archive(campaign_id):
    """Un envio si se borra de verdad: no es historia del negocio,
    es una lista de trabajo que ya se hizo."""
    with transaction():
        execute("DELETE FROM campaign_target WHERE campaign_id = ?", (campaign_id,))
        execute("DELETE FROM campaign WHERE id = ?", (campaign_id,))
