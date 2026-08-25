"""proyectos.reportar_asic_forzado -- excepcion para incluir en el clasificador

Decidido con el usuario (Sara) 2026-08-21, tras el caso real de GD Isabela,
Los Taurus VIII/IX/X, El Mandarino, MGS 0042 San Martin Norte, La Perdiz,
Garza, Chinu Sur 4, Monterrubio, Chima Oriente 2 y Merecumbe -- ninguno
tenia fila de reporte para el 20-ago porque `orquestador._fronteras_con_
reporte()` solo procesa proyectos `en_operacion` + `srv_cgm`, y estos 12
siguen `en_desarrollo`/sin CGM contratado pese a ya tener frontera
registrada en Quoia.

En vez de reportarlos a mano cada dia (endpoint /reportar-manual, agregado
en el commit anterior), este campo los marca para que el clasificador los
incluya en su corrida diaria normal -- corre el arbol de decision real
igual que cualquier otra frontera; si Quoia no tiene dato, cae en 'Sin
dato' como siempre, pendiente de revisar manualmente (no es un atajo a
matriz de ceros automatica).

Se deja marcado en True para los 12 proyectos ya identificados -- de aqui
en adelante, cualquier otro caso similar se marca desde el checkbox en el
formulario de Proyecto, sin tocar codigo.

Revision ID: 072
Revises: 071
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None

_PROYECTOS_IDS = [276, 261, 262, 263, 264, 165, 259, 260, 226, 210, 204, 176]


def upgrade():
    op.add_column(
        "proyectos",
        sa.Column("reportar_asic_forzado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE proyectos SET reportar_asic_forzado = true WHERE id = ANY(:ids)"),
        {"ids": _PROYECTOS_IDS},
    )


def downgrade():
    op.drop_column("proyectos", "reportar_asic_forzado")
