"""Run once to create all tables, apply migrations and seed initial data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def run_migrations():
    """Lleva el esquema al head de Alembic.

    Reemplaza la antigua add_columns() (DDL crudo imperativo): todo ese DDL
    idempotente ahora vive en la migracion 20260618_baseline_pending_ddls.py.
    Usa la API de Python de Alembic con el mismo alembic.ini que el CLI, de modo
    que env.py resuelva DATABASE_URL desde el entorno igual que ``alembic upgrade
    head`` en start.sh.
    """
    from alembic import command
    from alembic.config import Config

    ini_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini")
    cfg = Config(ini_path)
    command.upgrade(cfg, "head")


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")

    print("Running Alembic migrations (upgrade head)...")
    try:
        run_migrations()
        print("Migrations applied.")
    except Exception as e:
        # No silenciar: un fallo de migracion deja el esquema inconsistente.
        print(f"ERROR: Alembic migration failed: {e}")
        raise

    seed()


if __name__ == "__main__":
    init()
