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
            "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)",
            "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS servicio_id BIGINT REFERENCES cliente_servicios(id) ON DELETE SET NULL",
        ]
        for s in stmts:
            conn.execute(text(s))
        conn.commit()
    # Enum values must be added outside a transaction in PG < 12; use autocommit
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for val in ("rut", "certificado_bancario", "camara_comercio"):
            try:
                conn.execute(text(f"ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS '{val}'"))
            except Exception:
                pass
    print("Columns migrated.")


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    add_columns()
    seed()


if __name__ == "__main__":
    init()
