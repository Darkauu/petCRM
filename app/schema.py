"""Version del esquema que este codigo necesita.

No hay constante que mantener al dia: la version esperada es el numero
de la migracion mas alta en migrations/. Quien agregue 004_loquesea.sql
hace que el codigo espere la 4 sin tocar nada mas.

Existe para que un desajuste entre el codigo y la base se vea al entrar
a la pantalla, con instrucciones, y no como un error de SQLite a mitad
de registrar una visita con el cliente esperando.
"""
import re
from pathlib import Path

_NAME_RE = re.compile(r"^(\d{3})_.+\.sql$")


def expected_version(migrations_dir):
    numbers = []
    for path in Path(migrations_dir).glob("*.sql"):
        match = _NAME_RE.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers) if numbers else 0


def current_version(db):
    return db.execute("PRAGMA user_version").fetchone()[0]


def is_empty(db):
    """Una base recien creada (o inexistente) no tiene ni la tabla client."""
    row = db.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master "
        "WHERE type = 'table' AND name = 'client'"
    ).fetchone()
    return row["n"] == 0
