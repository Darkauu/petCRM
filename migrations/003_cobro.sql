-- =============================================================
--  migrations/003_cobro.sql   (user_version 2 -> 3)
--
--  La visita se registra cuando el cliente DEJA la mascota, y se
--  cobra cuando la RETIRA. Entre esos dos momentos la visita existe
--  pero todavia no es plata: no puede sumar en ningun total.
--
--  Hasta ahora toda visita nacia 'completed', que era mentira
--  durante todo el rato que el perro estaba en el local. Se agrega
--  'pending' al CHECK y pasa a ser el estado por defecto.
--
--  SQLite no permite alterar un CHECK: hay que reconstruir la tabla.
--  El runner de migraciones ya corre con foreign_keys=OFF, asi que
--  el DROP no dispara el ON DELETE CASCADE de visit_service.
--
--  Las vistas se sueltan primero y se recrean identicas al final:
--  ALTER TABLE ... RENAME vuelve a analizar todo el esquema, y una
--  vista que apunte a la tabla recien botada aborta la migracion.
-- =============================================================


DROP VIEW v_visit_total;
DROP VIEW v_pet_last_visit;


CREATE TABLE visit_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER NOT NULL REFERENCES client(id),
    visit_date   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','scheduled','completed',
                                   'no_show','cancelled')),
    scheduled_at TEXT,
    groomer      TEXT,
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at   TEXT
);

-- Lo ya registrado se cobro: conserva su estado tal cual.
INSERT INTO visit_new (id, client_id, visit_date, status, scheduled_at,
                       groomer, notes, created_at, updated_at, deleted_at)
SELECT id, client_id, visit_date, status, scheduled_at,
       groomer, notes, created_at, updated_at, deleted_at
FROM visit;

DROP TABLE visit;
ALTER TABLE visit_new RENAME TO visit;

CREATE INDEX idx_visit_client ON visit(client_id);
CREATE INDEX idx_visit_date   ON visit(visit_date);
CREATE INDEX idx_visit_status ON visit(status, visit_date);


-- Identicas a como estaban en 001.
--
-- v_visit_total suma las lineas sin mirar el estado, a proposito: una
-- visita pendiente necesita su total para poder mostrar cuanto se va a
-- cobrar. Quien cuenta plata filtra por estado en su propia consulta.
CREATE VIEW v_visit_total AS
SELECT v.id  AS visit_id,
       v.client_id,
       v.visit_date,
       COALESCE(SUM(vs.price_cents), 0) AS total_cents
FROM visit v
LEFT JOIN visit_service vs ON vs.visit_id = v.id
WHERE v.deleted_at IS NULL
GROUP BY v.id;

-- Una visita pendiente NO es la ultima visita de la mascota: el perro
-- todavia esta en el local. Por eso sigue filtrando por 'completed'.
CREATE VIEW v_pet_last_visit AS
SELECT p.id AS pet_id,
       p.client_id,
       MAX(v.visit_date) AS last_visit_date,
       COUNT(DISTINCT v.id) AS visit_count
FROM pet p
LEFT JOIN visit_service vs ON vs.pet_id = p.id
LEFT JOIN visit v ON v.id = vs.visit_id
                 AND v.status = 'completed'
                 AND v.deleted_at IS NULL
WHERE p.deleted_at IS NULL
GROUP BY p.id;


PRAGMA user_version = 3;
