"""email_envios.cliente_id: FK a ON DELETE SET NULL

Auditoria de Clientes 2026-08-27. `email_envios` es una tabla de solo
registro/trazabilidad (nunca tuvo modelo ORM, se provisiona por SQL crudo
en app/main.py) -- su FK a clientes quedo en NO ACTION (el default), asi
que borrar un Cliente con al menos un correo registrado (41/868 filas en
produccion) reventaba con un IntegrityError sin capturar, sin que
delete_cliente() supiera siquiera que esa tabla podia ser la causa.

No hay ninguna razon de negocio para bloquear el borrado de un cliente
por su historial de correos -- mismo criterio que ya aplica
contratos_servicio/ppa_contratos (SET NULL, se conserva el registro
historico, se pierde solo el vinculo).

Revision ID: 120
Revises: 119
Create Date: 2026-08-28
"""
from alembic import op

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE email_envios DROP CONSTRAINT email_envios_cliente_id_fkey")
    op.execute(
        "ALTER TABLE email_envios ADD CONSTRAINT email_envios_cliente_id_fkey "
        "FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE SET NULL"
    )


def downgrade():
    op.execute("ALTER TABLE email_envios DROP CONSTRAINT email_envios_cliente_id_fkey")
    op.execute(
        "ALTER TABLE email_envios ADD CONSTRAINT email_envios_cliente_id_fkey "
        "FOREIGN KEY (cliente_id) REFERENCES clientes(id)"
    )
