"""fronteras: uniformar ondelete a RESTRICT en las tablas que guardan
historial regulatorio/financiero por frontera

Sara, 2026-08-25 -- diagnostico de integridad de Fronteras post-limpieza.
`reporte_energia_generacion`, `reporte_energia_consumo` y
`reporte_energia_exclusiones` tenian `ondelete="CASCADE"`: un hard-delete
de una Frontera habria borrado en silencio su historial de reporte al
ASIC junto con ella. `liquidacion_xm_datos` no tenia `ondelete` explicito
(NO ACTION implicito de Postgres -- en la practica ya bloqueaba el
borrado, pero sin documentarlo). Hoy nada en el backend hace un
hard-delete real de Frontera (solo soft-delete via `deleted_at`), pero
esto es una proteccion para el dia que alguien agregue esa funcion:
las 4 tablas quedan en RESTRICT explicito -- un intento de hard-delete
falla ruidosamente en vez de cascadear datos regulatorios/financieros
o depender de un default sin documentar.

Revision ID: 083
Revises: 082
Create Date: 2026-08-25
"""
from alembic import op

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None

_FKS = [
    ("reporte_energia_generacion_frontera_id_fkey", "reporte_energia_generacion"),
    ("reporte_energia_consumo_frontera_id_fkey", "reporte_energia_consumo"),
    ("reporte_energia_exclusiones_frontera_id_fkey", "reporte_energia_exclusiones"),
    ("liquidacion_xm_datos_frontera_id_fkey", "liquidacion_xm_datos"),
]


def upgrade():
    for nombre, tabla in _FKS:
        op.drop_constraint(nombre, tabla, type_="foreignkey")
        op.create_foreign_key(nombre, tabla, "fronteras", ["frontera_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    for nombre, tabla in _FKS:
        op.drop_constraint(nombre, tabla, type_="foreignkey")
    for nombre, tabla in _FKS[:3]:
        op.create_foreign_key(nombre, tabla, "fronteras", ["frontera_id"], ["id"], ondelete="CASCADE")
    # liquidacion_xm_datos volvia sin ondelete explicito (NO ACTION implicito).
    op.create_foreign_key(_FKS[3][0], _FKS[3][1], "fronteras", ["frontera_id"], ["id"])
