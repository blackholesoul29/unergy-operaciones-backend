"""proyectos.project_id_solarview -- ID nuevo de la API SolarView (Fase 1: Reporte de Energía)

Solé reemplazó la API vieja de Solenium por una nueva ("SolarView",
https://api.sole.tech). Los `project_id` son completamente distintos entre
las dos APIs (no es un rename) -- se agrega una columna nueva en vez de
reescribir `project_id_solenium`, porque esa columna la siguen usando ~20
archivos fuera de Reporte de Energía que por ahora se quedan en la API
vieja (la migración se hace por fases; esta es solo Reporte de Energía).

Los 36 pares se reconciliaron por nombre contra el endpoint
`GET /solarview/config/company-projects/` en vivo con el token real de
Sara (2026-08-24). Se hace el match por el ID viejo (no por nombre) para
no depender de encoding/tildes en `nombre_comercial`.

Quedan sin mapeo (a la espera de que el equipo de Solé los agregue a su
API): El Encanto, Minigranja 0029 - Monterrubio, Minigranja 0037 -
Merecumbé -- se comportan igual que cualquier proyecto sin
project_id_solarview (caen al resto de la cadena del clasificador).

Revision ID: 075
Revises: 074
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None

# (project_id_solenium, project_id_solarview)
MAPEO = [
    ("122", "1"), ("136", "11"), ("118", "12"), ("130", "13"), ("108", "14"),
    ("144", "15"), ("127", "16"), ("113", "17"), ("143", "18"), ("149", "19"),
    ("104", "20"), ("150", "21"), ("157", "27"), ("153", "28"), ("146", "22"),
    ("148", "23"), ("147", "24"), ("102", "25"), ("145", "26"), ("176", "29"),
    ("154", "30"), ("160", "31"), ("156", "32"), ("159", "33"), ("168", "34"),
    ("162", "108"), ("161", "109"), ("167", "107"), ("175", "5"), ("178", "7"),
    ("165", "8"), ("166", "103"), ("174", "75"), ("173", "77"), ("180", "210"),
    ("111", "135"), ("158", "154"),
]


def upgrade():
    op.add_column(
        "proyectos",
        sa.Column("project_id_solarview", sa.String(100), nullable=True),
    )
    op.create_unique_constraint(
        "uq_proyectos_project_id_solarview", "proyectos", ["project_id_solarview"],
    )

    conn = op.get_bind()
    for viejo, nuevo in MAPEO:
        conn.execute(
            sa.text(
                "UPDATE proyectos SET project_id_solarview = :nuevo "
                "WHERE project_id_solenium = :viejo"
            ),
            {"nuevo": nuevo, "viejo": viejo},
        )


def downgrade():
    op.drop_constraint("uq_proyectos_project_id_solarview", "proyectos", type_="unique")
    op.drop_column("proyectos", "project_id_solarview")
