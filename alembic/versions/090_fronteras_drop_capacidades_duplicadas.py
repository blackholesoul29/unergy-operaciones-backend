"""fronteras: eliminar capacidad_transporte_mw y capacidad_efectiva_mw

Auditoria de calidad de datos de Fronteras (2026-08-25): en las 50
fronteras de generacion con ambos campos poblados, 49 tenian el mismo
valor exacto; y ese valor coincidia (con conversion kWp->MW) con
Proyecto.potencia_instalada_kwp en 52 de las 53 fronteras con dato --
la misma capacidad se guardaba tres veces. Sara decidio: Proyecto.
potencia_instalada_kwp queda como unica fuente (ya limpiada en una
sesion anterior, ver memoria project_potencia_instalada_kwp_es_ac).

Antes de eliminar:
- Se rellena potencia_instalada_kwp del proyecto 84 (GD La Hormiguita)
  con 990.0, tomado de Frontera.capacidad_efectiva_mw (0.99 MW) -- ese
  proyecto no tenia el dato propio y se habria perdido sin este backfill.
- Se pierde a proposito el matiz de GD 1MVA SAN ONOFRE (frontera id 51),
  el unico caso real donde capacidad_transporte_mw (0.99, limite de
  conexion) difiere de capacidad_efectiva_mw/potencia_instalada_kwp
  (0.90, instalada) -- 1 de 145 fronteras, aceptado explicitamente.

Los 3 puntos del pipeline de Reporte de Energia y Reporte CGM que leian
Frontera.capacidad_efectiva_mw directo (limite plausible del
reconectador, resumen CGM) ya se migraron en el mismo cambio para leer
Proyecto.potencia_instalada_kwp en su lugar.

Revision ID: 090
Revises: 089
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE proyectos SET potencia_instalada_kwp = 990.0 "
        "WHERE id = 84 AND potencia_instalada_kwp IS NULL"
    )
    op.drop_column("fronteras", "capacidad_transporte_mw")
    op.drop_column("fronteras", "capacidad_efectiva_mw")


def downgrade():
    op.add_column("fronteras", sa.Column("capacidad_efectiva_mw", sa.Numeric(10, 4), nullable=True))
    op.add_column("fronteras", sa.Column("capacidad_transporte_mw", sa.Numeric(10, 4), nullable=True))
    op.create_check_constraint(
        "ck_fronteras_capacidad_efectiva_mw_no_negativa",
        "fronteras", "capacidad_efectiva_mw IS NULL OR capacidad_efectiva_mw >= 0",
    )
    op.create_check_constraint(
        "ck_fronteras_capacidad_transporte_mw_no_negativa",
        "fronteras", "capacidad_transporte_mw IS NULL OR capacidad_transporte_mw >= 0",
    )
