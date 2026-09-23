-- =============================================================
--  migrations/005_envios.sql   (user_version 4 -> 5)
--
--  Escribirle al mismo mensaje a varios clientes, uno por uno.
--
--  WhatsApp no deja mandar en lote desde un programa: cada chat se
--  abre por separado. Lo que si se puede quitar es lo que de verdad
--  cansa, que no son los toques sino redactar el mismo mensaje seis
--  veces y perder la cuenta de por quien iba. Eso es lo que guardan
--  estas dos tablas.
--
--  El sistema NO envia nada. Arma el enlace con el mensaje ya escrito
--  y lo abre en WhatsApp; el mensaje sale del telefono de la duenia,
--  de su propio numero, como si lo hubiera tecleado ella.
-- =============================================================


CREATE TABLE campaign (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Como se llamo el envio, para reconocerlo en la lista despues.
    name        TEXT NOT NULL,
    -- El mensaje con sus marcas sin reemplazar ({cliente}, {mascota}):
    -- guardarlo ya resuelto por persona seria guardar seis copias de
    -- lo mismo y perder el texto que de verdad se escribio.
    message     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at   TEXT
);

CREATE INDEX idx_campaign_created ON campaign(created_at);


CREATE TABLE campaign_target (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    client_id   INTEGER NOT NULL REFERENCES client(id),

    -- NULL en los dos = todavia no le toca. Se separan porque no es lo
    -- mismo haberle escrito que haberlo salteado a proposito: lo
    -- segundo hay que poder verlo al cerrar el envio.
    sent_at     TEXT,
    skipped_at  TEXT,

    created_at  TEXT NOT NULL DEFAULT (datetime('now')),

    -- Nadie entra dos veces al mismo envio.
    UNIQUE (campaign_id, client_id)
);

CREATE INDEX idx_target_campaign ON campaign_target(campaign_id, sent_at, skipped_at);


PRAGMA user_version = 5;
