"""Consolidar DDL idempotente migrado desde init_db.py (add_columns)

DDL idempotente trasladado desde `init_db.py::add_columns()` (sentencias
`stmts` + los `ALTER TYPE ... ADD VALUE` que la función construía). La mayoría
se solapa con la migración 026 (mismas sentencias IF NOT EXISTS, inofensivas al
repetirse); se incluyen las propias de init_db.py para que init_db quede solo
con create_all + seed y Alembic sea la única fuente de verdad del esquema.

Revision ID: 027_ddl_init_db
Revises: 026_pending_ddls_main
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = "027_ddl_init_db"
down_revision = "026_pending_ddls_main"
branch_labels = None
depends_on = None

REV = "027_ddl_init_db"

_DDLS = [
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
        # ppa_compromisos_energia: plantas inscritas exigidas por mes (condición a cumplir; denominador del indicador de cumplimiento de plantas)
        "ALTER TABLE ppa_compromisos_energia ADD COLUMN IF NOT EXISTS cantidad_proyectos INTEGER",
        # Toda fila arranca en 0 (el equipo completa los valores reales luego); default 0 para filas futuras.
        "ALTER TABLE ppa_compromisos_energia ALTER COLUMN cantidad_proyectos SET DEFAULT 0",
        "UPDATE ppa_compromisos_energia SET cantidad_proyectos = 0 WHERE cantidad_proyectos IS NULL",
    ]

_DDLS += [
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'rut'",
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'certificado_bancario'",
    "ALTER TYPE tipo_documento_cliente_enum ADD VALUE IF NOT EXISTS 'camara_comercio'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'despacho'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'ventas_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'compras_en_bolsa'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'redistribucion_ingresos'",
    "ALTER TYPE tipo_linea_mandato_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
    "ALTER TYPE tipo_costo_enum ADD VALUE IF NOT EXISTS 'cambio_equipos_medida'",
    "ALTER TYPE tipo_venta_liq_enum ADD VALUE IF NOT EXISTS 'autoconsumo'",
]

def _run(stmts):
    """Ejecuta cada sentencia de forma independiente y en autocommit, saltando
    las que fallen. Es una réplica exacta del comportamiento idempotente que
    tenía el arranque de la app: como toda sentencia usa IF NOT EXISTS (o es un
    catch-up idempotente), en una BD que ya las contiene (producción) simplemente
    se omiten sin efecto. `ALTER TYPE ... ADD VALUE` debe correr fuera de una
    transacción, así que todo el bloque va en autocommit y los ADD VALUE primero
    para que los nuevos valores de enum existan antes del DDL que los referencia.
    """
    add_value = [s for s in stmts if "ADD VALUE" in s.upper()]
    regular = [s for s in stmts if "ADD VALUE" not in s.upper()]
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        for stmt in add_value + regular:
            try:
                bind.execute(sa.text(stmt))
            except Exception as e:  # noqa: BLE001 — idempotente: saltar si ya existe
                print(f"[{REV} ddl skipped] {e}")


def upgrade() -> None:
    _run(_DDLS)


def downgrade() -> None:
    # Consolidación idempotente acumulada (cientos de ALTER/CREATE ... IF NOT
    # EXISTS y backfills de datos). No existe un downgrade seguro: revertir
    # borraría columnas, tablas y valores de enum, con pérdida de datos en
    # producción. Intencionalmente no-op.
    pass
