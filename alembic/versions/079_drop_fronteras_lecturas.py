"""fronteras_lecturas -- eliminar tabla completa (huérfana: sin escritor real
ni consumidor real)

Diagnóstico de Fronteras, Sara, 2026-08-24/25: la tabla + sus 3 endpoints
CRUD (GET/POST /fronteras/{id}/lecturas, /lecturas/bulk) y el endpoint
GET /fronteras/resumen (que la agregaba para 2 de sus 4 números) nunca
tuvieron ni un escritor automático (ningún job/pipeline/script inserta acá
-- solo era posible a mano vía los POST) ni un consumidor real del lado del
frontend (confirmado: FronterasView.vue nunca llama a ninguno de los 4
endpoints). Probablemente diseño previo a reporte_energia_generacion/
consumo, que es lo que sí se usa hoy para "cuánta energía reportó esta
frontera".

Se elimina la tabla completa, el modelo `FronteraLectura`, el enum
`FuenteLecturaEnum`/`fuente_lectura_enum`, los 3 endpoints de lecturas,
`GET /fronteras/resumen` completo (sin sustancia real sin la tabla), y sus
schemas (`FronteraLecturaCreate/Out`, `FronteraResumen`).

Revision ID: 079
Revises: 078
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("fronteras_lecturas")
    op.execute("DROP TYPE IF EXISTS fuente_lectura_enum")


def downgrade():
    fuente_lectura_enum = postgresql.ENUM(
        "medidor_principal", "medidor_respaldo", name="fuente_lectura_enum",
    )
    fuente_lectura_enum.create(op.get_bind())
    op.create_table(
        "fronteras_lecturas",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("frontera_id", sa.BigInteger(), sa.ForeignKey("fronteras.id"), nullable=False),
        sa.Column("fuente", fuente_lectura_enum, nullable=False),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False),
        sa.Column("periodo_inicio", sa.Date(), nullable=False),
        sa.Column("periodo_fin", sa.Date(), nullable=False),
        sa.Column("energia_activa_import_kwh", sa.Numeric(14, 4), nullable=True),
        sa.Column("energia_activa_export_kwh", sa.Numeric(14, 4), nullable=True),
        sa.Column("energia_react_ind_import_kvarh", sa.Numeric(14, 4), nullable=True),
        sa.Column("energia_react_ind_export_kvarh", sa.Numeric(14, 4), nullable=True),
        sa.Column("energia_react_cap_import_kvarh", sa.Numeric(14, 4), nullable=True),
        sa.Column("energia_react_cap_export_kvarh", sa.Numeric(14, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fronteras_lecturas_frontera_id", "fronteras_lecturas", ["frontera_id"])
    op.create_index("ix_frontera_lectura_frontera_fecha", "fronteras_lecturas", ["frontera_id", "fecha_hora"])
