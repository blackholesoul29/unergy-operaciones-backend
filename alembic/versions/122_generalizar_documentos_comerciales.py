"""generalizar cliente_documentos_comerciales: tambien ContratoServicio y PPAContrato

Auditoria de Clientes 2026-08-28. `Cliente.rut_url`, `ContratoServicio.enlace_drive`
y `PPAContrato.carpeta_link` eran 3 campos de link sueltos, sin historial ni
estado, cada uno reinventando lo que `cliente_documentos_comerciales` ya
resuelve para Cliente (RUT, camara de comercio, etc). En vez de 3 tablas o 3
campos, esta migracion generaliza la que ya existe: `cliente_id` se vuelve
nullable y se agregan `contrato_servicio_id`/`ppa_contrato_id`, con un
CheckConstraint que exige exactamente un dueño por fila.

Los datos de los 3 campos viejos se migran 1:1 a una fila tipo='contrato' (o
'rut' para Cliente) antes de eliminar las columnas -- ningun link se pierde.
`ContratoServicio.enlace_drive` y `PPAContrato.carpeta_link` siguen existiendo
como @property de solo lectura en los modelos (ver models/contratos.py), asi
que ContratoServicioOut/PPAContratoOut y el frontend no cambian; la escritura
pasa por app/services/documentos.set_enlace_documento.

Las columnas/constraint nuevas puede que ya existan: _PENDING_DDLS
(app/main.py) corre en cada arranque ANTES que Alembic (ver
alembic_idempotencia.py), asi que de ahi los guardas con columna_existe/
constraint_existe en vez de las llamadas crudas de op.*.

Revision ID: 122
Revises: 121
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op

from alembic_idempotencia import columna_existe, constraint_existe

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    if not columna_existe(bind, "cliente_documentos_comerciales", "contrato_servicio_id"):
        op.add_column("cliente_documentos_comerciales", sa.Column(
            "contrato_servicio_id", sa.BigInteger(),
            sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=True))
        op.create_index("ix_cliente_documentos_contrato_servicio",
                         "cliente_documentos_comerciales", ["contrato_servicio_id"])
    if not columna_existe(bind, "cliente_documentos_comerciales", "ppa_contrato_id"):
        op.add_column("cliente_documentos_comerciales", sa.Column(
            "ppa_contrato_id", sa.BigInteger(),
            sa.ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=True))
        op.create_index("ix_cliente_documentos_ppa_contrato",
                         "cliente_documentos_comerciales", ["ppa_contrato_id"])

    op.execute("ALTER TABLE cliente_documentos_comerciales ALTER COLUMN cliente_id DROP NOT NULL")

    if not constraint_existe(bind, "cliente_documentos_comerciales", "ck_documento_un_solo_dueno"):
        op.execute("""
            ALTER TABLE cliente_documentos_comerciales ADD CONSTRAINT ck_documento_un_solo_dueno
              CHECK (CAST(cliente_id IS NOT NULL AS INTEGER)
                     + CAST(contrato_servicio_id IS NOT NULL AS INTEGER)
                     + CAST(ppa_contrato_id IS NOT NULL AS INTEGER) = 1)
        """)

    # ── Backfill + drop de las 3 columnas viejas ──────────────────────────────
    if columna_existe(bind, "contratos_servicio", "enlace_drive"):
        op.execute("""
            INSERT INTO cliente_documentos_comerciales
                (contrato_servicio_id, tipo, nombre, estado, archivo_url, created_at, updated_at)
            SELECT cs.id, 'contrato', 'Enlace Drive del contrato', 'firmado', cs.enlace_drive, NOW(), NOW()
              FROM contratos_servicio cs
             WHERE cs.enlace_drive IS NOT NULL AND cs.enlace_drive <> ''
               AND NOT EXISTS (
                     SELECT 1 FROM cliente_documentos_comerciales d
                      WHERE d.contrato_servicio_id = cs.id AND d.tipo = 'contrato')
        """)
        op.execute("ALTER TABLE contratos_servicio DROP COLUMN enlace_drive")

    if columna_existe(bind, "ppa_contratos", "carpeta_link"):
        op.execute("""
            INSERT INTO cliente_documentos_comerciales
                (ppa_contrato_id, tipo, nombre, estado, archivo_url, created_at, updated_at)
            SELECT p.id, 'contrato', 'Enlace Drive del contrato', 'firmado', p.carpeta_link, NOW(), NOW()
              FROM ppa_contratos p
             WHERE p.carpeta_link IS NOT NULL AND p.carpeta_link <> ''
               AND NOT EXISTS (
                     SELECT 1 FROM cliente_documentos_comerciales d
                      WHERE d.ppa_contrato_id = p.id AND d.tipo = 'contrato')
        """)
        op.execute("ALTER TABLE ppa_contratos DROP COLUMN carpeta_link")

    if columna_existe(bind, "clientes", "rut_url"):
        op.execute("""
            INSERT INTO cliente_documentos_comerciales
                (cliente_id, tipo, nombre, estado, archivo_url, created_at, updated_at)
            SELECT c.id, 'rut', 'RUT', 'aceptado', c.rut_url, NOW(), NOW()
              FROM clientes c
             WHERE c.rut_url IS NOT NULL AND c.rut_url <> ''
               AND NOT EXISTS (
                     SELECT 1 FROM cliente_documentos_comerciales d
                      WHERE d.cliente_id = c.id AND d.tipo = 'rut')
        """)
        op.execute("ALTER TABLE clientes DROP COLUMN rut_url")


def downgrade():
    bind = op.get_bind()
    if not columna_existe(bind, "contratos_servicio", "enlace_drive"):
        op.add_column("contratos_servicio", sa.Column("enlace_drive", sa.String(1000), nullable=True))
        op.execute("""
            UPDATE contratos_servicio cs SET enlace_drive = d.archivo_url
              FROM cliente_documentos_comerciales d
             WHERE d.contrato_servicio_id = cs.id AND d.tipo = 'contrato'
        """)
    if not columna_existe(bind, "ppa_contratos", "carpeta_link"):
        op.add_column("ppa_contratos", sa.Column("carpeta_link", sa.String(1000), nullable=True))
        op.execute("""
            UPDATE ppa_contratos p SET carpeta_link = d.archivo_url
              FROM cliente_documentos_comerciales d
             WHERE d.ppa_contrato_id = p.id AND d.tipo = 'contrato'
        """)
    if not columna_existe(bind, "clientes", "rut_url"):
        op.add_column("clientes", sa.Column("rut_url", sa.String(1000), nullable=True))
        op.execute("""
            UPDATE clientes c SET rut_url = d.archivo_url
              FROM cliente_documentos_comerciales d
             WHERE d.cliente_id = c.id AND d.tipo = 'rut'
        """)
    # El resto (columnas nuevas, constraint, cliente_id nullable) no se revierte:
    # no rompe nada si queda, y revertirlo botaria documentos de contratos/PPA
    # que ya podrian existir para entonces.
