"""fronteras: eliminar departamento y tipo_tecnologia (duplicaban Proyecto)

Auditoria de calidad de datos de Fronteras (2026-08-25). departamento
coincidia 71/71 (100%) con Proyecto.departamento donde ambos tenian dato;
tipo_tecnologia coincidia 98/98 (100%, case-insensitive -- Frontera
guardaba texto libre "Solar", Proyecto usa el enum TipoTecnologiaEnum.solar)
con Proyecto.tipo_tecnologia. Sara decidio: viven en Proyecto, Frontera se
alimenta de ahi (mismo patron que potencia_instalada_kwp).

Antes de eliminar: 16 proyectos no tenian su propio departamento y 1
(id 84, GD La Hormiguita -- el mismo de la migracion 090) no tenia
tipo_tecnologia -- se rellenan con el valor de su(s) frontera(s), sin
conflicto entre fronteras del mismo proyecto en ningun caso.

A diferencia de esos dos, NO se tocan en esta migracion: municipio (68%
de coincidencia real, uso activo en filtro/columna de FronterasView.vue),
direccion/direccion_vereda (nombres distintos a proposito, no son
duplicados), latitud/longitud (divergen significativamente, incluidos 3
casos de ~21km -- posible dato erroneo en Proyecto, no en Frontera) y
altitud_msnm (sin equivalente en Proyecto). Quedan para revision caso por
caso.

Revision ID: 091
Revises: 090
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None

_BACKFILL_DEPARTAMENTO = {
    3: "Norte de Santander",
    6: "Norte de Santander",
    7: "Córdoba",
    15: "Córdoba",
    18: "Nariño",
    29: "Atlántico",
    32: "Nariño",
    33: "Nariño",
    34: "Nariño",
    38: "Cauca",
    39: "Cauca",
    44: "Córdoba",
    46: "Norte de Santander",
    55: "Meta",
    56: "Bolívar",
    84: "Atlántico",
}


def upgrade():
    conn = op.get_bind()
    for proyecto_id, departamento in _BACKFILL_DEPARTAMENTO.items():
        conn.execute(
            sa.text("UPDATE proyectos SET departamento = :d WHERE id = :id AND departamento IS NULL"),
            {"d": departamento, "id": proyecto_id},
        )
    conn.execute(
        sa.text("UPDATE proyectos SET tipo_tecnologia = 'solar' WHERE id = 84 AND tipo_tecnologia IS NULL")
    )
    op.drop_column("fronteras", "departamento")
    op.drop_column("fronteras", "tipo_tecnologia")


def downgrade():
    op.add_column("fronteras", sa.Column("tipo_tecnologia", sa.String(length=100), nullable=True))
    op.add_column("fronteras", sa.Column("departamento", sa.String(length=100), nullable=True))
