"""Run once to create all tables and seed initial data.

Solo crea el esquema base (`Base.metadata.create_all`) y siembra datos
iniciales (`seed`). La evolución del esquema (ALTER/CREATE incrementales, enums,
backfills) vive ahora exclusivamente en migraciones de Alembic
(`alembic upgrade head`, ejecutado por start.sh). Este archivo ya NO altera el
esquema directamente: el antiguo `add_columns()` se migró a
alembic/versions/027_consolidar_ddl_init_db.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    seed()


if __name__ == "__main__":
    init()
