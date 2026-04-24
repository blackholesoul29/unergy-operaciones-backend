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
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='rut' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='tipo_documento_cliente_enum')) THEN ALTER TYPE tipo_documento_cliente_enum ADD VALUE 'rut'; END IF; END $$",
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='certificado_bancario' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='tipo_documento_cliente_enum')) THEN ALTER TYPE tipo_documento_cliente_enum ADD VALUE 'certificado_bancario'; END IF; END $$",
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel='camara_comercio' AND enumtypid=(SELECT oid FROM pg_type WHERE typname='tipo_documento_cliente_enum')) THEN ALTER TYPE tipo_documento_cliente_enum ADD VALUE 'camara_comercio'; END IF; END $$",
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
