"""fronteras: eliminar centro_poblado, registrada_por, representante_frontera

Auditoria de calidad de datos de Fronteras (2026-08-25). Sin FK, sin
logica de negocio que los lea (solo de solo lectura en
FronteraDetailView.vue), sin equivalente en Proyecto -- a diferencia de
los campos de ubicacion consolidados antes (municipio, departamento,
etc.), estos no se mueven a ningun lado, se eliminan directamente.

registrada_por y representante_frontera tienen ademas casi cero
contenido informativo real: representante_frontera es LITERALMENTE
constante (94/94 filas con dato = "UNERGY ENERGY DIGITAL S.A.S E.S.P -
GENERADOR"), registrada_por casi (92/94 el mismo valor, 2 con
"ESPACIO PRODUCTIVO S.A.S. E.S.P. - GENERADOR"). centro_poblado si tiene
variedad real (corregimientos/veredas) pero tampoco lo usa nada.

Revision ID: 095
Revises: 094
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("fronteras", "centro_poblado")
    op.drop_column("fronteras", "registrada_por")
    op.drop_column("fronteras", "representante_frontera")


def downgrade():
    op.add_column("fronteras", sa.Column("representante_frontera", sa.String(length=255), nullable=True))
    op.add_column("fronteras", sa.Column("registrada_por", sa.String(length=255), nullable=True))
    op.add_column("fronteras", sa.Column("centro_poblado", sa.String(length=100), nullable=True))
