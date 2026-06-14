"""Crea el esquema base y siembra los datos iniciales.

La evolución del esquema (ALTER TABLE / ADD COLUMN / CREATE TYPE / índices, etc.)
la gestiona exclusivamente Alembic. ``Base.metadata.create_all`` solo se usa para
crear las tablas base que aún no existan (p. ej. en un entorno vacío de dev/test
antes de correr las migraciones); es un no-op para las tablas ya presentes.
Las migraciones de Alembic deben ejecutarse aparte con ``alembic upgrade head``
(ver ``start.sh``).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def init():
    print("Creating base tables (Alembic manages all schema evolution)...")
    Base.metadata.create_all(bind=engine)
    print("Tables ensured.")
    seed()


if __name__ == "__main__":
    init()
