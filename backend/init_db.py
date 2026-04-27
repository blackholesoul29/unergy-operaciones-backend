"""Run once to create all tables and seed initial data."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import text
from app.core.database import engine
from app.models import Base
from app.seeds.seed_data import seed


def add_columns():
    stmts = [
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS rut_url VARCHAR(1000)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cantidad_total_paneles INTEGER",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS servicio_id BIGINT REFERENCES cliente_servicios(id) ON DELETE SET NULL",
    ]
    for s in stmts:
        try:
            with engine.connect() as conn:
                conn.execute(text(s))
                conn.commit()
        except Exception as e:
            print(f"  WARN column migration skipped: {e}")

    enum_vals = ("rut", "certificado_bancario", "camara_comercio")
    for val in enum_vals:
        try:
            with engine.connect() as conn:
                conn.execute(text("COMMIT"))
                conn.execute(text(f"ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS '{val}'"))
                conn.execute(text("COMMIT"))
        except Exception as e:
            print(f"  WARN enum migration skipped: {e}")
    print("Columns migrated.")


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    add_columns()
    seed()


if __name__ == "__main__":
    init()
