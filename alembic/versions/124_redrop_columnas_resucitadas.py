"""re-drop de columnas que resucitaron en produccion tras 121/122

Verificacion post-deploy 2026-08-28 (sesion de auditoria de Clientes): pese
a que `alembic_version` marco 121 y 122 como aplicadas sin error, una
consulta directa contra produccion mostro que 5 columnas seguian existiendo,
vacias (0 filas pobladas):
  - clientes.banco / tipo_cuenta / numero_cuenta / titular_cuenta (121)
  - clientes.rut_url (122)
  - ppa_contratos.carpeta_link (122)

Dentro de la misma migracion 122, `contratos_servicio.enlace_drive` SI se
borro correctamente -- mismo patron de codigo, mismo archivo. La causa mas
probable es el mismo patron ya documentado para nombre_bitacora/nombre_clientes
(ver alembic_idempotencia.py y memoria del proyecto): una ventana de rolling
deploy en Railway donde un contenedor con el `init_db.py`/`_PENDING_DDLS`
todavia viejo (que si tenia estos `ADD COLUMN IF NOT EXISTS`) arranco
despues de que la migracion ya habia hecho el DROP.

DROP directo (sin `columna_existe`) para no depender del mismo guard que ya
fallo en silencio una vez.

Revision ID: 124
Revises: 123
Create Date: 2026-08-28
"""
from alembic import op

revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS banco")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS tipo_cuenta")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS numero_cuenta")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS titular_cuenta")
    op.execute("ALTER TABLE clientes DROP COLUMN IF EXISTS rut_url")
    op.execute("ALTER TABLE ppa_contratos DROP COLUMN IF EXISTS carpeta_link")


def downgrade():
    # 0/96 poblado siempre (ver migraciones 121/122): no hay nada que valga
    # la pena recrear.
    pass
