"""Eliminar fallas_cat_estados.color_hex y fallas_cat_prioridades.color_hex

Auditoria del dominio Fallas 2026-09-02: el unico consumidor real de estas
dos columnas era el frontend (badges/tags de estado y prioridad en
MonitoreoView.vue, GestionFallasView.vue, FallaDetailView.vue y toda la app
movil) -- el correo real de notificacion tiene su propio esquema de colores
independiente (`_ESTADO_MAP` en email_service.py) que nunca leyo estas
columnas. Se homologaron los valores hex (los mismos que tenia la BD, sin
inventar colores nuevos) en un catalogo unico del lado del frontend
(unergy-operaciones-frontend/app/features/fallas/utils/colores.ts).

Nota de gobernanza: docs/refactor/06-plan-migracion.md declara los 5
catalogos `fallas_cat_*` "intactos" ("Laura ya los administra. Solo se les
agrega un indice"). Este DROP se aparta de esa decision -- confirmado
explicitamente por la usuaria el 2026-09-02 como cambio legitimo y
necesario, sin haber consultado a Laura en esta conversacion. Documentado
aca para que quede trazable si el plan de refactor lo retoma.

Revision ID: 141
Revises: 140
Create Date: 2026-09-02
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "141"
down_revision = "140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if columna_existe(bind, "fallas_cat_estados", "color_hex"):
        op.drop_column("fallas_cat_estados", "color_hex")
    if columna_existe(bind, "fallas_cat_prioridades", "color_hex"):
        op.drop_column("fallas_cat_prioridades", "color_hex")


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    if not columna_existe(bind, "fallas_cat_estados", "color_hex"):
        op.add_column("fallas_cat_estados", sa.Column("color_hex", sa.String(7), nullable=True))
    if not columna_existe(bind, "fallas_cat_prioridades", "color_hex"):
        op.add_column("fallas_cat_prioridades", sa.Column("color_hex", sa.String(7), nullable=True))
