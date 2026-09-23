"""Los grupos de clientes, definidos una sola vez.

El panel de clientes y la pantalla de envios hacen la misma pregunta
("¿quienes llevan mas de N dias?", "¿quienes tienen perro pequenio?").
Si cada uno la respondiera por su cuenta, el dia que cambie el criterio
los dos numeros dejarian de cuadrar y nadie sabria cual creer.

Cada grupo es (clave, etiqueta, funcion). La clave es lo unico que
viaja por la URL: se usa para elegir una de estas funciones, nunca para
armar SQL.
"""

# Los que se pueden combinar entre si y valen en las dos pantallas.
COMUNES = [
    ("escribir", "Por escribir",
     lambda r, plazo: r["last_visit_date"] is not None and r["days"] > plazo),
    ("sin-visitas", "Sin visitas",
     lambda r, plazo: r["last_visit_date"] is None),
    ("pequenos", "Perros pequeños",
     lambda r, plazo: "small" in (r["sizes"] or "")),
    ("medianos", "Perros medianos",
     lambda r, plazo: "medium" in (r["sizes"] or "")),
    ("grandes", "Perros grandes",
     lambda r, plazo: "large" in (r["sizes"] or "")),
]

# Solo en el panel: es una lista de tareas de la migracion del cuaderno,
# no un grupo al que se le escriba (justamente, no tienen telefono).
INCOMPLETOS = (
    "incompletos", "Datos incompletos",
    lambda r, plazo: not r["phone"] or r["pets_sin_talla"] > 0,
)

PANEL = COMUNES + [INCOMPLETOS]

CLAVES_COMUNES = {clave for clave, _, _ in COMUNES}
