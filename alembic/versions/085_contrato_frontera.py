"""contrato_frontera: vinculo muchos-a-muchos entre ContratoServicio y
Frontera

Item 4 del diagnostico de integridad de Fronteras, 2026-08-25. Hoy
ContratoServicio.proyecto_id vincula un contrato a un Proyecto completo,
pero una planta puede tener varias Fronteras (generacion, consumo,
distintos medidores) y dos contratos sobre la misma planta (ej.
"Operacion" y "Representacion") a veces aplican a puntos de medida
distintos, no a la planta entera -- no habia forma de expresarlo.

CASCADE en las dos FK es correcto para esta tabla (a diferencia de la
politica RESTRICT recien establecida para reporte_energia_*/
liquidacion_xm_datos en la migracion 083): esta es una tabla de vinculo
puro sin datos propios -- si se borra un Contrato o una Frontera, lo
unico que debe desaparecer es el enlace.

Revision ID: 085
Revises: 084
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contrato_frontera",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("contrato_servicio_id", sa.BigInteger(),
                   sa.ForeignKey("contratos_servicio.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frontera_id", sa.BigInteger(),
                   sa.ForeignKey("fronteras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("contrato_servicio_id", "frontera_id", name="uq_contrato_frontera"),
    )
    op.create_index("ix_contrato_frontera_contrato_servicio_id", "contrato_frontera", ["contrato_servicio_id"])
    op.create_index("ix_contrato_frontera_frontera_id", "contrato_frontera", ["frontera_id"])


def downgrade():
    op.drop_table("contrato_frontera")
