-- =============================================================
--  migrations/004_cuaderno.sql   (user_version 3 -> 4)
--
--  Migrar el cuaderno de papel obliga a aceptar lo que el cuaderno
--  tiene: renglones a los que les falta algo. Hay clientes anotados
--  sin telefono y perros anotados sin talla, y son la mitad del
--  valor del cuaderno.
--
--  La alternativa era rechazar ese renglon y devolverlo en un CSV
--  para que alguien lo complete a mano. Rechazar significa que el
--  cuaderno no entra hasta que alguien se siente a llamar a treinta
--  personas, y mientras tanto el sistema arranca vacio. Entra
--  incompleto y se ve que esta incompleto: en la ficha se lee
--  'Falta el telefono' y la pantalla de clientes lo puede filtrar.
--
--  Un dato ausente es informacion. Uno inventado es una mentira que
--  despues cobra mal: si a un perro sin talla se le pone 'mediano'
--  por rellenar, el precio de su proximo bano sale del renglon
--  equivocado y nadie se entera.
--
--  SQLite no permite soltar un NOT NULL: hay que reconstruir la
--  tabla. Las vistas se sueltan primero y se recrean identicas al
--  final, porque ALTER TABLE ... RENAME vuelve a analizar todo el
--  esquema y una vista que apunte a la tabla recien botada aborta
--  la migracion.
-- =============================================================


DROP VIEW v_visit_total;
DROP VIEW v_pet_last_visit;


-- -------------------------------------------------------------
--  client.phone deja de ser obligatorio
-- -------------------------------------------------------------

CREATE TABLE client_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    phone          TEXT,                 -- E.164, o NULL si el cuaderno no lo traia
    phone_display  TEXT,
    document       TEXT,
    email          TEXT,
    address        TEXT,
    notes          TEXT,

    marketing_consent INTEGER NOT NULL DEFAULT 0,
    consent_at        TEXT,
    preferred_channel TEXT DEFAULT 'whatsapp'
                      CHECK (preferred_channel IN ('whatsapp','sms','email','none')),

    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at     TEXT
);

INSERT INTO client_new (id, name, phone, phone_display, document, email,
                        address, notes, marketing_consent, consent_at,
                        preferred_channel, created_at, updated_at, deleted_at)
SELECT id, name, phone, phone_display, document, email,
       address, notes, marketing_consent, consent_at,
       preferred_channel, created_at, updated_at, deleted_at
FROM client;

DROP TABLE client;
ALTER TABLE client_new RENAME TO client;

-- 'AND phone IS NOT NULL' es explicito a proposito: SQLite ya trata
-- cada NULL como distinto en un indice unico, pero de esta forma la
-- intencion queda escrita y no depende de recordar esa regla.
CREATE UNIQUE INDEX idx_client_phone
    ON client(phone) WHERE deleted_at IS NULL AND phone IS NOT NULL;
CREATE UNIQUE INDEX idx_client_document
    ON client(document) WHERE deleted_at IS NULL AND document IS NOT NULL AND document <> '';
CREATE UNIQUE INDEX idx_client_email
    ON client(email) WHERE deleted_at IS NULL AND email IS NOT NULL AND email <> '';
CREATE INDEX idx_client_name ON client(name);


-- -------------------------------------------------------------
--  pet.size deja de ser obligatorio
-- -------------------------------------------------------------

CREATE TABLE pet_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER NOT NULL REFERENCES client(id),
    name       TEXT NOT NULL,
    species    TEXT NOT NULL DEFAULT 'dog' CHECK (species IN ('dog','cat')),
    breed      TEXT,
    -- NULL = no se sabe. El CHECK sigue cerrando el resto de valores:
    -- lo que no se permite es una talla inventada, no una vacia.
    size       TEXT CHECK (size IS NULL OR size IN ('small','medium','large')),
    sex        TEXT CHECK (sex IN ('male','female')),

    birthdate      TEXT,
    weight_kg      REAL,
    temperament    TEXT,
    medical_notes  TEXT,

    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

INSERT INTO pet_new (id, client_id, name, species, breed, size, sex,
                     birthdate, weight_kg, temperament, medical_notes,
                     is_active, created_at, updated_at, deleted_at)
SELECT id, client_id, name, species, breed, size, sex,
       birthdate, weight_kg, temperament, medical_notes,
       is_active, created_at, updated_at, deleted_at
FROM pet;

DROP TABLE pet;
ALTER TABLE pet_new RENAME TO pet;

CREATE INDEX idx_pet_client ON pet(client_id);
CREATE INDEX idx_pet_size   ON pet(size);


-- -------------------------------------------------------------
--  De donde salio cada visita
-- -------------------------------------------------------------
--
--  Una visita tecleada en el local es trabajo que hizo el sistema.
--  Una visita que venia escrita en el cuaderno es historia: sirve
--  para saber a quien hay que escribirle, pero no es trabajo del
--  sistema y no debe contarse como tal.
--
--  Va como ADD COLUMN y sin CHECK: agregar un CHECK obligaria a
--  reconstruir visit por tercera vez en esta migracion, y la unica
--  que escribe esta columna es la aplicacion, con dos valores.

ALTER TABLE visit ADD COLUMN source TEXT NOT NULL DEFAULT 'app';

CREATE INDEX idx_visit_source ON visit(source, visit_date);


-- -------------------------------------------------------------
--  Vistas, identicas a como estaban en 003
-- -------------------------------------------------------------

CREATE VIEW v_visit_total AS
SELECT v.id  AS visit_id,
       v.client_id,
       v.visit_date,
       COALESCE(SUM(vs.price_cents), 0) AS total_cents
FROM visit v
LEFT JOIN visit_service vs ON vs.visit_id = v.id
WHERE v.deleted_at IS NULL
GROUP BY v.id;

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


PRAGMA user_version = 4;
