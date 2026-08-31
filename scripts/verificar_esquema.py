"""Falla si la base no tiene todo lo que los modelos declaran.

Reemplaza a `_PENDING_DDLS` (retirada el 2026-08-31). Aquella lista provisionaba
las columnas nuevas por las malas -- un ALTER tolerante en cada arranque -- y de
paso tapaba el error que aqui se hace explicito.

El agujero que cierra: si alguien agrega una columna al modelo y olvida la
revision de Alembic, `create_all()` se la crea en una base vacia y las pruebas
pasan, pero la base de produccion NO la tiene y el sintoma aparece semanas
despues como un 500 en la pantalla que la consulta. Esto lo convierte en un
deploy que falla en el momento.

Corre en el servicio `migrate` del docker-compose, DESPUES de
`alembic upgrade head`. Salida != 0 aborta el deploy y `operaciones` no arranca.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect  # noqa: E402

import app.models  # noqa: F401,E402  — registra todos los modelos en el metadata
from app.core.database import engine  # noqa: E402
from app.models.base import Base  # noqa: E402


def faltantes() -> list[str]:
    inspector = inspect(engine)
    en_db = set(inspector.get_table_names())
    problemas = []
    for nombre, tabla in Base.metadata.tables.items():
        if nombre not in en_db:
            problemas.append(f"{nombre}: la tabla no existe")
            continue
        columnas = {c["name"] for c in inspector.get_columns(nombre)}
        for col in tabla.columns:
            if col.name not in columnas:
                problemas.append(f"{nombre}.{col.name}: la columna no existe")
    return problemas


def main() -> int:
    problemas = faltantes()
    if not problemas:
        print(f"[esquema] OK — {len(Base.metadata.tables)} tablas del modelo presentes")
        return 0
    print("[esquema] La base NO tiene lo que el modelo declara:")
    for p in problemas:
        print(f"  - {p}")
    print("\nFalta la revision de Alembic que lo provisiona. El esquema se cambia")
    print("SOLO con Alembic desde que se retiro _PENDING_DDLS (2026-08-31).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
