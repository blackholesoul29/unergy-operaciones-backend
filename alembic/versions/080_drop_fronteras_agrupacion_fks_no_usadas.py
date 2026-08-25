"""fronteras.agrupada_bajo_id / embebida_bajo_id / frontera_gemela_id --
eliminar por completo (FKs auto-referenciadas nunca conectadas a lógica real)

Diagnóstico de campos de GESCON, Sara, 2026-08-25: los 3 son 0/145 en
producción, no tienen `relationship()` en el modelo `Frontera`, y ningún
query/servicio del backend los usa (confirmado con auditoría de 2 agentes,
backend + frontend). `scripts/cargar_fronteras_gescon.py` (recién
eliminado) mandaba `agrupada_bajo`/`embebida_bajo` como texto libre --
nombre de otra frontera -- pero el modelo esperaba un FK numérico, así que
Pydantic los descartaba en silencio sin error; ese bug queda sin objeto al
eliminar tanto el script como las columnas.

Revision ID: 080
Revises: 079
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("fronteras", "agrupada_bajo_id")
    op.drop_column("fronteras", "embebida_bajo_id")
    op.drop_column("fronteras", "frontera_gemela_id")


def downgrade():
    op.add_column("fronteras", sa.Column("frontera_gemela_id", sa.BigInteger(), sa.ForeignKey("fronteras.id"), nullable=True))
    op.add_column("fronteras", sa.Column("agrupada_bajo_id", sa.BigInteger(), sa.ForeignKey("fronteras.id"), nullable=True))
    op.add_column("fronteras", sa.Column("embebida_bajo_id", sa.BigInteger(), sa.ForeignKey("fronteras.id"), nullable=True))
    op.create_index("ix_fronteras_frontera_gemela_id", "fronteras", ["frontera_gemela_id"])
    op.create_index("ix_fronteras_agrupada_bajo_id", "fronteras", ["agrupada_bajo_id"])
    op.create_index("ix_fronteras_embebida_bajo_id", "fronteras", ["embebida_bajo_id"])
