"""eliminar cliente_servicios (manual, vestigial)

Auditoria de Clientes 2026-08-28. `cliente_servicios` era una lista manual
de "que servicios presta Unergy a este cliente", cargada a mano al crear el
cliente. Confirmado en produccion: 1 fila en toda la historia del sistema,
contra 162 contratos reales en `contratos_servicio`. El propio codigo
(services/clientes_panel.py::servicios_por_cliente) ya venia derivando la
lista real desde `contratos_servicio` (contratante + prestador) y solo
UNIA la fila manual encima -- con una sola fila esa union nunca cambiaba el
resultado que ve nadie. Se elimina el modelo, los 3 endpoints CRUD, la UI
("Servicios registrados manualmente" en ClienteDetailView.vue) y la tabla.

La unica fila real (cliente_id=57 "Ayura S.A.S.", tipo='operacion',
fecha_inicio=2026-04-01, notas='3.8%') no se preserva: `notas` era
write-only (nunca se mostro en ningun lado), asi que ese dato ya era
invisible para todos antes de este drop.

`cliente_documentos_comerciales.servicio_id` (FK a cliente_servicios.id,
0/N documentos la usaban en produccion) se elimina junto con la tabla.

Revision ID: 123
Revises: 122
Create Date: 2026-08-28
"""
from alembic import op

from alembic_idempotencia import columna_existe, tabla_existe

revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if columna_existe(bind, "cliente_documentos_comerciales", "servicio_id"):
        op.execute("ALTER TABLE cliente_documentos_comerciales DROP COLUMN servicio_id")
    if tabla_existe(bind, "cliente_servicios"):
        op.execute("DROP TABLE cliente_servicios")
    op.execute("DROP TYPE IF EXISTS tipo_servicio_cliente_enum")


def downgrade():
    # 1 fila en toda la historia, y su unico dato no-trivial (notas) era
    # write-only: no hay nada que valga la pena recrear.
    pass
