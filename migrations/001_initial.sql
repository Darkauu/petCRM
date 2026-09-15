-- =============================================================
--  Peluquería canina — Micro SaaS
--  migrations/001_initial.sql   (user_version 0 -> 1)
--
--  Base ÚNICA por negocio. No hay base maestra en el MVP;
--  se agrega en F9 solo como tabla de ruteo (slug -> archivo).
--
--  Convenciones:
--    * Dinero en centavos (INTEGER). SQLite no tiene DECIMAL real.
--      La conversión dólares<->centavos usa Decimal, nunca float.
--    * Timestamps en TEXT ISO-8601 UTC ('YYYY-MM-DD HH:MM:SS').
--      Fechas de calendario en 'YYYY-MM-DD', hora local Panamá.
--    * Borrado lógico vía deleted_at. Nunca DELETE físico de negocio.
--    * Enums guardados en clave (inglés); la traducción vive en Jinja.
--
--  OJO: PRAGMA foreign_keys es POR CONEXIÓN y no va en este archivo;
--  se activa en get_db(). journal_mode=WAL es persistente y se aplica
--  una sola vez al crear la base, desde el script de provisión.
-- =============================================================


-- -------------------------------------------------------------
--  Configuración del negocio (clave/valor)
--  Evita que el nombre del negocio viva en el HTML.
-- -------------------------------------------------------------
CREATE TABLE setting (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO setting (key, value) VALUES
    ('business_name', ''),
    ('business_phone', ''),
    ('business_address', ''),
    ('logo_path', ''),
    ('currency', 'USD'),
    ('timezone', 'America/Panama'),
    ('require_document', '0');   -- si '1', la cédula es obligatoria


-- -------------------------------------------------------------
--  Usuarios (dentro del tenant: aislamiento físico)
-- -------------------------------------------------------------
CREATE TABLE app_user (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT,
    role          TEXT NOT NULL DEFAULT 'owner'
                  CHECK (role IN ('owner','staff')), -- Check this
    is_active     INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE login_event (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES app_user(id),
    email_tried TEXT,
    ip         TEXT,
    success    INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_login_event_time ON login_event(created_at);


-- -------------------------------------------------------------
--  Clientes
--  Identidad interna = client.id.
--  document: llave natural estable
--  phone:    llave operativa
-- -------------------------------------------------------------
CREATE TABLE client (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    phone          TEXT NOT NULL,        -- E.164: +5076XXXXXXX
    phone_display  TEXT,                 -- como lo escribió la usuaria
    document       TEXT,                 -- cédula / pasaporte / RUC
    email          TEXT,
    address        TEXT,
    notes          TEXT,

    -- [FASE 2] segmentación y envíos
    marketing_consent INTEGER NOT NULL DEFAULT 0,
    consent_at        TEXT,
    preferred_channel TEXT DEFAULT 'whatsapp'
                      CHECK (preferred_channel IN ('whatsapp','sms','email','none')),

    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at     TEXT
);

-- Índices únicos parciales: un cliente borrado no debe bloquear
-- el alta de otro con el mismo número o documento.
CREATE UNIQUE INDEX idx_client_phone
    ON client(phone) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX idx_client_document
    ON client(document) WHERE deleted_at IS NULL AND document IS NOT NULL AND document <> '';
CREATE UNIQUE INDEX idx_client_email
    ON client(email) WHERE deleted_at IS NULL AND email IS NOT NULL AND email <> '';
CREATE INDEX idx_client_name ON client(name);


-- -------------------------------------------------------------
--  Mascotas
-- -------------------------------------------------------------
CREATE TABLE pet (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id  INTEGER NOT NULL REFERENCES client(id),
    name       TEXT NOT NULL,
    species    TEXT NOT NULL DEFAULT 'dog' CHECK (species IN ('dog','cat')),
    breed      TEXT,
    size       TEXT NOT NULL CHECK (size IN ('small','medium','large')),
    sex        TEXT CHECK (sex IN ('male','female')),

    -- [FASE 2] cumpleaños, recordatorios, ficha de manejo
    birthdate      TEXT,
    weight_kg      REAL,
    temperament    TEXT,   -- 'muerde al secar', 'nervioso con la máquina'
    medical_notes  TEXT,   -- alergias, condiciones de piel

    is_active  INTEGER NOT NULL DEFAULT 1,   -- ya no asiste / falleció
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);

CREATE INDEX idx_pet_client ON pet(client_id);
CREATE INDEX idx_pet_size   ON pet(size);


-- -------------------------------------------------------------
--  Catálogo de servicios y precios
-- -------------------------------------------------------------
CREATE TABLE service (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_service_name ON service(name);

-- Precio vigente. 'any' = mismo precio para cualquier tamaño.
-- La app busca primero el tamaño exacto, luego 'any'.
CREATE TABLE service_price (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id  INTEGER NOT NULL REFERENCES service(id),
    size        TEXT NOT NULL DEFAULT 'any'
                CHECK (size IN ('any','small','medium','large')),
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (service_id, size)
);


-- -------------------------------------------------------------
--  Visitas (cabecera por cliente) y líneas de servicio
-- -------------------------------------------------------------
CREATE TABLE visit (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER NOT NULL REFERENCES client(id),
    visit_date   TEXT NOT NULL,                  -- 'YYYY-MM-DD'
    status       TEXT NOT NULL DEFAULT 'completed'
                 CHECK (status IN ('scheduled','completed','no_show','cancelled')),
    scheduled_at TEXT,                           -- [FASE 3] hora de la cita
    groomer      TEXT,
    notes        TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at   TEXT
);

CREATE INDEX idx_visit_client ON visit(client_id);
CREATE INDEX idx_visit_date   ON visit(visit_date);
CREATE INDEX idx_visit_status ON visit(status, visit_date);

-- El precio se CONGELA aquí al momento del cobro. Cambiar el catálogo
-- nunca debe reescribir el histórico.
CREATE TABLE visit_service (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id     INTEGER NOT NULL REFERENCES visit(id) ON DELETE CASCADE,
    pet_id       INTEGER NOT NULL REFERENCES pet(id),
    service_id   INTEGER NOT NULL REFERENCES service(id),
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (visit_id, pet_id, service_id)
);

CREATE INDEX idx_visit_service_visit ON visit_service(visit_id);
CREATE INDEX idx_visit_service_pet   ON visit_service(pet_id);


-- -------------------------------------------------------------
--  Vistas de conveniencia (datos derivados, NUNCA almacenados)
-- -------------------------------------------------------------

-- Total cobrado por visita
CREATE VIEW v_visit_total AS
SELECT v.id  AS visit_id,
       v.client_id,
       v.visit_date,
       COALESCE(SUM(vs.price_cents), 0) AS total_cents
FROM visit v
LEFT JOIN visit_service vs ON vs.visit_id = v.id
WHERE v.deleted_at IS NULL
GROUP BY v.id;

-- Última visita por mascota — base de la segmentación por inactividad
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


PRAGMA user_version = 1;