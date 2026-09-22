-- =============================================================
--  migrations/002_resumen.sql   (user_version 1 -> 2)
--
--  Fase 3: visibilidad. No cambia el modelo, solo lo que hace
--  falta para agregarlo sin escanear tablas completas, y dos
--  ajustes que son criterio del negocio y no del sistema.
-- =============================================================


-- El resumen agrupa por servicio ("que servicios pesan mas").
-- Sin este indice, cada consulta recorre visit_service entero.
CREATE INDEX idx_visit_service_service ON visit_service(service_id);


-- Los dias que abre y a partir de cuantos dias considera que un
-- cliente se atraso los decide el duenio, no el sistema.
--
--   working_days: dias ISO separados por coma, lunes = 0.
--                 Arranca con los siete: marcar un dia como cerrado
--                 es una decision suya, no una suposicion nuestra.
--   followup_days: dias sin venir a partir de los cuales aparece
--                  en la lista de atrasados.
INSERT OR IGNORE INTO setting (key, value) VALUES
    ('working_days',  '0,1,2,3,4,5,6'),
    ('followup_days', '15');


PRAGMA user_version = 2;
