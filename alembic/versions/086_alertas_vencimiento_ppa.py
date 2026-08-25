"""alertas: tabla generica de alertas persistentes, primer uso -- vencimiento
proactivo de contratos PPA

Rescate del hueco confirmado en la auditoria de integridad de Fronteras:
no habia nada que avisara proactivamente cuando un PPA esta por vencer
(solo alertas "pull" en app/api/v1/alertas.py, calculadas cuando el
frontend pregunta). El job app/jobs/ppa_expiration_checker.py puebla
esta tabla con una fila por cada ventana de antelacion (90/60/30 dias)
que un contrato cruza; la restriccion unica (ppa_id, days_to_expiration)
es la que garantiza que correr el job dos veces no duplique la alerta.

Revision ID: 086
Revises: 085
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotente: mismo caso que 085_contrato_frontera -- _run_create_tables()
    # (Base.metadata.create_all pre-Alembic, sigue vivo en paralelo) ya habia
    # creado esta tabla completa cuando se desplego el modelo Alerta,
    # verificado 2026-08-25 (mismas columnas/indices, 0 filas).
    if not sa.inspect(op.get_bind()).has_table("alertas"):
        op.create_table(
            "alertas",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("ppa_id", sa.BigInteger(),
                       sa.ForeignKey("ppa_contratos.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.BigInteger(),
                       sa.ForeignKey("proyectos.id", ondelete="CASCADE"), nullable=True),
            sa.Column("alert_type", sa.String(50), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("trigger_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("days_to_expiration", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="new"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("ppa_id", "days_to_expiration", name="uq_alertas_ppa_dias"),
        )
        op.create_index("ix_alertas_ppa_id", "alertas", ["ppa_id"])
        op.create_index("ix_alertas_project_id", "alertas", ["project_id"])


def downgrade():
    op.drop_table("alertas")
