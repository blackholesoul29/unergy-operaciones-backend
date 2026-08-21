"""xm_process_id/xm_estado/xm_exitoso/xm_verificado_en en reporte_energia_*

Decidido con el usuario (Sara) 2026-08-21: hoy no sabemos si un reporte ya
enviado a Quoia (gaia.post_report) fue realmente APROBADO por XM -- solo
guardamos si el POST HTTP en si tuvo exito (enviado_quoia_ok). Quoia pone
cada envio en "En espera" y despues XM lo resuelve a "Exitoso"/"Error"
(visible en el dashboard propio de Quoia).

gaia.get_border_report_status(border_id, fecha) ya trae ese detalle
(confirmado contra Quoia real): accepted/validated/success, xm_process_id,
status ('OK'/'WARNING'/'ERROR...'), validation_errors. Estos campos guardan
el resultado de re-consultar eso DESPUES de enviar -- distinto de
'estado_reporte', que se llena UNA VEZ al clasificar (antes del envio) y
sirve para otra cosa (si el CGM automatico de Quoia es valido como fuente).

Revision ID: 073
Revises: 072
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade():
    for tabla in ("reporte_energia_generacion", "reporte_energia_consumo"):
        op.add_column(tabla, sa.Column("xm_process_id", sa.String(100), nullable=True))
        op.add_column(tabla, sa.Column("xm_estado", sa.String(30), nullable=True))
        op.add_column(tabla, sa.Column("xm_exitoso", sa.Boolean(), nullable=True))
        op.add_column(tabla, sa.Column("xm_verificado_en", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    for tabla in ("reporte_energia_generacion", "reporte_energia_consumo"):
        op.drop_column(tabla, "xm_verificado_en")
        op.drop_column(tabla, "xm_exitoso")
        op.drop_column(tabla, "xm_estado")
        op.drop_column(tabla, "xm_process_id")
