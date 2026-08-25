"""proyectos.operador_red / fronteras.operador_red / fronteras.operador_red_zona -- eliminar (texto libre legacy, ya redundante con operador_red_id)

`operador_red_id` (FK al catálogo `operadores_red`) es el único vínculo real
que se mantiene -- ver app/services/operadores_red_sync.py y
Proyecto.operador_red_legal. Decidido con el usuario (Sara) 2026-08-24, como
parte del diagnóstico de Fronteras: los 3 campos (operador_red texto,
operador_red_zona, operador_red_id) eran redundantes.

Verificado en vivo antes de este cambio: 0 filas dependían del texto libre
sin también tener operador_red_id (63/63 proyectos, 100/100 fronteras con
texto también tenían el FK), y operador_red_zona tenía 0 filas pobladas --
no hay pérdida de datos real. Todos los lugares que leían/escribían el texto
libre directo se migraron a `operador_red_legal` (o se eliminó la escritura,
ver backfill-operador-red y proyectos_backfill_solenium.py) en el mismo
cambio que esta migración.

Revision ID: 076
Revises: 075
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("proyectos", "operador_red")
    op.drop_column("fronteras", "operador_red")
    op.drop_column("fronteras", "operador_red_zona")


def downgrade():
    op.add_column("proyectos", sa.Column("operador_red", sa.String(100), nullable=True))
    op.add_column("fronteras", sa.Column("operador_red", sa.String(255), nullable=True))
    op.add_column("fronteras", sa.Column("operador_red_zona", sa.String(255), nullable=True))
