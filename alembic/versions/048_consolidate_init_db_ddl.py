"""048 -- consolidate startup DDL from init_db.py add_columns()

``init_db.py`` used to apply its own idempotent DDL on every run via
``add_columns()`` (column additions + a handful of enum ``ADD VALUE`` calls),
overlapping with -- but not identical to -- the ``app/main.py`` safety-net now
captured in migration 047. This migration version-controls that DDL too, so
``init_db.py`` can be reduced to table creation + seeding for local dev/test.

Every statement is idempotent, so applying this after 047 (or on an already
up-to-date database) is a safe no-op.

Revision ID: 048
Revises: 047
Create Date: 2026-07-11
"""
from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


# Verbatim copy of the former ``init_db.add_columns()`` DDL (columns + enums).
_STATEMENTS = [
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS rut_url VARCHAR(1000)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_liquidacion VARCHAR(255)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_monitoreo VARCHAR(255)",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correo_soporte VARCHAR(255)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS alias_monitoreo TEXT",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS sub_project VARCHAR(50)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_bitacora VARCHAR(255)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS nombre_clientes VARCHAR(255)",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS srv_operacion BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_inicio_comercializacion DATE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS fecha_comercializacion_editada_manual BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS cantidad_total_paneles INTEGER",
    "ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS produccion_especifica_kwh_kwp NUMERIC(10,2)",
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
    # enum values added by the old init_db.add_columns() helper
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


def _apply(statements):
    """Apply idempotent DDL, mirroring the old startup safety-net behaviour.

    ``ALTER TYPE ... ADD VALUE`` must run outside a transaction block, so those
    run in an autocommit block first. Every other statement runs inside its own
    SAVEPOINT so a statement that legitimately fails (e.g. a bare ``CREATE TYPE``
    for a type that already exists) is skipped instead of aborting the whole
    migration -- exactly how ``_run_column_migrations`` behaved on every boot.
    All statements are idempotent, so re-applying on an up-to-date database is a
    safe no-op.
    """
    bind = op.get_bind()
    add_value = [s for s in statements if "ADD VALUE" in s.upper()]
    regular = [s for s in statements if "ADD VALUE" not in s.upper()]

    with op.get_context().autocommit_block():
        for stmt in add_value:
            try:
                op.execute(stmt)
            except Exception as e:  # noqa: BLE001 -- idempotent skip, as before
                print(f"[migration {revision} ddl skipped] {e}")

    for stmt in regular:
        try:
            with bind.begin_nested():
                op.execute(stmt)
        except Exception as e:  # noqa: BLE001 -- idempotent skip, as before
            print(f"[migration {revision} ddl skipped] {e}")


def upgrade() -> None:
    _apply(_STATEMENTS)


def downgrade() -> None:
    # These statements were an additive, idempotent safety-net (new columns,
    # tables, indexes, enum values and guarded backfills). There is no safe
    # automatic reversal -- dropping them would risk data loss -- so downgrade
    # is intentionally a no-op, consistent with the other additive/data
    # migrations in this project (e.g. 006, 035, 038).
    pass
