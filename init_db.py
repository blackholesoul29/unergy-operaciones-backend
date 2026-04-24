"""Run once to create all tables and seed initial data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def add_columns():
    with engine.connect() as conn:
        stmts = [
            "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cantidad_total_paneles INTEGER",
            "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
        ]
        for s in stmts:
            conn.execute(text(s))
        conn.commit()
    print("Columns migrated.")


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    add_columns()
    seed()


if __name__ == "__main__":
    init()
