"""drop cliente.telefono_contacto (redundante con contactos.telefono)

telefono_contacto era un campo suelto en Cliente, sin relación con la tabla
contactos que ya modela telefono por persona/area (ver migracion 037). Antes
de borrar se rescata el UNICO dato real que existia (cliente_id=75, 'CGM
Ingenieria S.A.S', '300 694 35 62') adjuntandolo al contacto tipo=cgm que ya
tiene ese cliente (nicolas.o@cgm-i.com) -- no se crea un contacto nuevo
porque contactos.email es NOT NULL y no hay un correo propio para este
telefono. El resto de clientes nunca tuvo este campo poblado.

Revision ID: 065
Revises: 064
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE contactos
        SET telefono = c.telefono_contacto
        FROM clientes c
        WHERE contactos.cliente_id = c.id
          AND c.telefono_contacto IS NOT NULL
          AND trim(c.telefono_contacto) <> ''
          AND contactos.telefono IS NULL
          AND contactos.id = (
              SELECT ct.id FROM contactos ct
              WHERE ct.cliente_id = c.id
              ORDER BY ct.id
              LIMIT 1
          )
    """)
    op.drop_column("clientes", "telefono_contacto")


def downgrade():
    op.add_column("clientes", sa.Column("telefono_contacto", sa.String(length=100), nullable=True))
