"""fronteras: eliminar subestacion, nombre_cgm, niu, punto_conexion

Auditoria de calidad de datos de Fronteras (2026-08-25). Los 4 campos
comparten el mismo perfil: sin FK, sin logica de negocio que los lea (solo
se mostraban de solo lectura en FronteraDetailView.vue), y su unico origen
fue el import historico de GESCON (script cargar_fronteras_gescon.py, ya
retirado, commit d0fad40) -- nada los vuelve a poblar.

subestacion, niu y punto_conexion estaban 100% vacios (0/145 filas vivas).
nombre_cgm si tenia dato real (94/145, 64.8%) -- se elimina igual, a
pedido explicito de Sara, con la perdida de ese dato asumida.

Revision ID: 089
Revises: 088
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("fronteras", "subestacion")
    op.drop_column("fronteras", "nombre_cgm")
    op.drop_column("fronteras", "niu")
    op.drop_column("fronteras", "punto_conexion")


def downgrade():
    op.add_column("fronteras", sa.Column("punto_conexion", sa.String(length=500), nullable=True))
    op.add_column("fronteras", sa.Column("niu", sa.String(length=50), nullable=True))
    op.add_column("fronteras", sa.Column("nombre_cgm", sa.String(length=255), nullable=True))
    op.add_column("fronteras", sa.Column("subestacion", sa.String(length=255), nullable=True))
