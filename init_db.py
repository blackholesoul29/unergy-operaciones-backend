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
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sub_project VARCHAR(50)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS srv_operacion BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_inicio_comercializacion DATE",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_comercializacion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_reporte_generacion_id INTEGER",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_reporte_consumo_id INTEGER",
        "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS quoia_nodo_id INTEGER",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS archivo_nombre VARCHAR(500)",
        "ALTER TABLE cliente_documentos_comerciales ADD COLUMN IF NOT EXISTS servicio_id BIGINT REFERENCES cliente_servicios(id) ON DELETE SET NULL",
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
        # ppa_contratos: comunidad energética NO es otro tipo de contrato, es una
        # característica de este PPA (2026-08-18). NULL a propósito en los
        # contratos viejos que no salieron de una oferta: null = no sabemos,
        # distinto de False.
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS es_comunidad_energetica BOOLEAN",
        # oportunidad_ofertas: fin tentativo del suministro (2026-08-18). Con el
        # inicio que ya existía, es lo que permite que un PPA en borrador declare
        # su periodo antes de firmarse.
        "ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS fecha_fin_tentativa DATE",
        # oportunidad_gestiones: a cuál oferta se refiere la gestión (2026-08-19).
        # NULL = del cliente, cuenta para todas sus ofertas (comportamiento viejo,
        # que es el que conservan las filas existentes).
        "ALTER TABLE oportunidad_gestiones ADD COLUMN IF NOT EXISTS oferta_id BIGINT",
        "CREATE INDEX IF NOT EXISTS ix_oportunidad_gestiones_oferta_id "
        "ON oportunidad_gestiones (oferta_id)",
        # ppa_contratos: tipo_contrato y carpeta_link (migración 009)
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS tipo_contrato VARCHAR(20) DEFAULT 'venta'",
        "ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS carpeta_link VARCHAR(1000)",
        # ppa_compromisos_energia: plantas inscritas exigidas por mes (condición a cumplir; denominador del indicador de cumplimiento de plantas)
        "ALTER TABLE ppa_compromisos_energia ADD COLUMN IF NOT EXISTS cantidad_proyectos INTEGER",
        # Toda fila arranca en 0 (el equipo completa los valores reales luego); default 0 para filas futuras.
        "ALTER TABLE ppa_compromisos_energia ALTER COLUMN cantidad_proyectos SET DEFAULT 0",
        "UPDATE ppa_compromisos_energia SET cantidad_proyectos = 0 WHERE cantidad_proyectos IS NULL",
        # Figura "Uso del recurso" (spec 2026-07-06): cliente en bolsa, planta usada
        # en contrato; Unergy le paga a precio bolsa. Clasifica doble (a+c).
        "ALTER TABLE asic_solicitudes ADD COLUMN IF NOT EXISTS uso_del_recurso BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE clasificacion_energia_mensual ADD COLUMN IF NOT EXISTS uso_del_recurso BOOLEAN NOT NULL DEFAULT FALSE",
        # Panel de fronteras pendientes de Quoia (migracion 043) -- respaldo por
        # si alembic no llega a aplicarla (ver incidente de la migracion 035).
        "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS quoia_border_id INTEGER",
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
