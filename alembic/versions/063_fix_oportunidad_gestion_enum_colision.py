"""Fix: oportunidad_gestiones.tipo usaba el enum de otro modelo por completo.

tipo_gestion_enum ya era el tipo de GestionRegistro (app/models/gestion.py,
migracion 007: pqr/preventivo/correctivo, gestiones de mantenimiento por
proyecto). oportunidad_gestiones (bitacora de Comercial: llamada/correo/
reunion/whatsapp/nota) nunca tuvo su propia migracion -- solo create_all()
al arrancar -- y como el nombre ya existia, SQLAlchemy lo reuso tal cual en
vez de crear el suyo. Resultado: cualquier insert con los valores reales
(llamada/correo/...) viola el enum ajeno, y la tabla lleva en 0 filas desde
que existe (confirmado en produccion 2026-08-19).

Como no hay ninguna fila que convertir, el fix es directo: crear el tipo
correcto y apuntar la columna ahi.

Revision ID: 063
Revises: 062
Create Date: 2026-08-19
"""
from alembic import op
from sqlalchemy import text

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    filas = bind.execute(text("SELECT count(*) FROM oportunidad_gestiones")).scalar()
    if filas:
        raise RuntimeError(
            f"Migracion 063: oportunidad_gestiones tiene {filas} fila(s) -- se "
            f"esperaba 0 (nunca pudo guardar nada por el choque de enum). "
            f"Revisar a mano antes de convertir la columna, no asumir que sigue vacia."
        )

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tipo_gestion_oportunidad_enum AS ENUM
                ('llamada', 'correo', 'reunion', 'whatsapp', 'nota');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute(
        "ALTER TABLE oportunidad_gestiones ALTER COLUMN tipo TYPE tipo_gestion_oportunidad_enum "
        "USING tipo::text::tipo_gestion_oportunidad_enum"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE oportunidad_gestiones ALTER COLUMN tipo TYPE tipo_gestion_enum "
        "USING tipo::text::tipo_gestion_enum"
    )
    op.execute("DROP TYPE IF EXISTS tipo_gestion_oportunidad_enum")
