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
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_liquidacion VARCHAR(255)",
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_monitoreo VARCHAR(255)",
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_soporte VARCHAR(255)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS alias_monitoreo TEXT",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sub_project VARCHAR(50)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_bitacora VARCHAR(255)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_clientes VARCHAR(255)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS srv_operacion BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cantidad_total_paneles INTEGER",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS servicio_id BIGINT REFERENCES cliente_servicios(id) ON DELETE SET NULL",
        "ALTER TABLE proyectos ALTER COLUMN cliente_id DROP NOT NULL",
        # liquidaciones detalle
        "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS estado_resultados_url VARCHAR(1000)",
        "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS informe_html TEXT",
        "ALTER TABLE liquidaciones ADD COLUMN IF NOT EXISTS informe_actualizado_en TIMESTAMPTZ",
        "ALTER TABLE liquidacion_mandatos ADD COLUMN IF NOT EXISTS inversionista_id BIGINT REFERENCES proyecto_inversionistas(id) ON DELETE SET NULL",
        "ALTER TABLE liquidacion_costos ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
        "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS nro_soporte VARCHAR(100)",
        "ALTER TABLE liquidacion_facturas ADD COLUMN IF NOT EXISTS soporte_url VARCHAR(1000)",
        # ppa_contratos: FK a clientes (comprador/vendedor)
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS comprador_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS vendedor_id BIGINT REFERENCES clientes(id) ON DELETE SET NULL",
        # ppa_contratos: tipo_contrato y carpeta_link (migración 009)
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(20) DEFAULT 'venta'",
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS carpeta_link VARCHAR(1000)",
        # ppa_compromisos_energia: plantas esperadas por mes (denominador del indicador de cumplimiento de plantas)
        "ALTER TABLE ppa_compromisos_energia ADD COLUMN IF NOT EXISTS cantidad_proyectos INTEGER",
    ]
    for s in stmts:
        try:
            with engine.connect() as conn:
                conn.execute(text(s))
                conn.commit()
        except Exception as e:
            print(f"  WARN column migration skipped: {e}")

    enum_vals_cliente = ("rut", "certificado_bancario", "camara_comercio")
    for val in enum_vals_cliente:
        try:
            with engine.connect() as conn:
                conn.execute(text("COMMIT"))
                conn.execute(text(f"ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS '{val}'"))
                conn.execute(text("COMMIT"))
        except Exception as e:
            print(f"  WARN enum migration skipped: {e}")

    enum_linea_vals = (
        "despacho", "ventas_en_bolsa", "compras_en_bolsa",
        "redistribucion_ingresos", "cambio_equipos_medida",
    )
    for val in enum_linea_vals:
        try:
            with engine.connect() as conn:
                conn.execute(text("COMMIT"))
                conn.execute(text(f"ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS '{val}'"))
                conn.execute(text("COMMIT"))
        except Exception as e:
            print(f"  WARN enum tipo_linea_mandato_enum skipped: {e}")

    try:
        with engine.connect() as conn:
            conn.execute(text("COMMIT"))
            conn.execute(text("ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'"))
            conn.execute(text("COMMIT"))
    except Exception as e:
        print(f"  WARN enum tipo_costo_enum skipped: {e}")

    try:
        with engine.connect() as conn:
            conn.execute(text("COMMIT"))
            conn.execute(text("ALTER TYPE tipo_venta_liq_enum ADD VALUE IF NOT EXISTS 'autoconsumo'"))
            conn.execute(text("COMMIT"))
    except Exception as e:
        print(f"  WARN enum tipo_venta_liq_enum skipped: {e}")

    print("Columns migrated.")


def init():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created.")
    add_columns()
    seed()


if __name__ == "__main__":
    init()
