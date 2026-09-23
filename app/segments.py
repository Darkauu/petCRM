"""Los grupos de clientes, definidos una sola vez.

El panel de clientes y la pantalla de envios hacen la misma pregunta
("¿quienes llevan mas de N dias?", "¿quienes tienen perro pequenio?").
Si cada uno la respondiera por su cuenta, el dia que cambie el criterio
los dos numeros dejarian de cuadrar y nadie sabria cual creer.

Cada grupo es (clave, etiqueta, condicion). La condicion es un pedazo
de SQL sobre las columnas que ya calcula la consulta de estado, no una
funcion de Python: asi el filtro, el conteo y la paginacion se resuelven
en la base y el panel deja de traerse la tabla entera para descartarla
en memoria. El '?' que llevan algunas es el plazo de atraso.

La clave es lo unico que viaja por la URL. Se usa para ELEGIR una de
estas condiciones, nunca para armarla: nada de lo que escribe el usuario
llega a una consulta.
"""

# Los que se pueden combinar entre si y valen en las dos pantallas.
COMUNES = [
    ("escribir", "Por escribir",
     "last_visit_date IS NOT NULL AND days > ?"),
    ("sin-visitas", "Sin visitas",
     "last_visit_date IS NULL"),
    # Sobre 'sizes', que es el GROUP_CONCAT de las tallas de sus perros
    # activos. Las tres claves son distintas entre si, asi que un LIKE
    # no puede confundir una con otra.
    ("pequenos", "Perros pequeños", "sizes LIKE '%small%'"),
    ("medianos", "Perros medianos", "sizes LIKE '%medium%'"),
    ("grandes", "Perros grandes", "sizes LIKE '%large%'"),
]

# Solo en el panel: es una lista de tareas de la migracion del cuaderno,
# no un grupo al que se le escriba (justamente, no tienen telefono).
INCOMPLETOS = (
    "incompletos", "Datos incompletos",
    "phone IS NULL OR pets_sin_talla > 0",
)

PANEL = COMUNES + [INCOMPLETOS]

CLAVES_COMUNES = {clave for clave, _, _ in COMUNES}
CLAVES_PANEL = {clave for clave, _, _ in PANEL}

_POR_CLAVE = {clave: cond for clave, _etiqueta, cond in PANEL}


def condicion(claves, plazo):
    """(sql, params) para las filas que cumplen TODAS las claves dadas.

    Combinar es la gracia: "por escribir" Y "perros pequenios" son los
    atrasados de talla chica. Cada condicion va entre parentesis porque
    alguna lleva un OR adentro y sin agrupar colaria filas de mas.

    Una clave que no existe se ignora en vez de reventar: llega de la
    URL, y una direccion vieja o mal tecleada no es un error del
    sistema.
    """
    partes, params = [], []
    for clave in claves:
        if clave not in _POR_CLAVE:
            continue
        cond = _POR_CLAVE[clave]
        partes.append(f"({cond})")
        params.extend([plazo] * cond.count("?"))
    return " AND ".join(partes), params
