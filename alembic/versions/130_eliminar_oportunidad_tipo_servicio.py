"""eliminar oportunidades.tipo_servicio (imposible de setear desde ningun UI)

Auditoria de la tabla oportunidades 2026-08-28. 0/66 poblado -- y no por
falta de uso: el dropdown viejo de "Tipo de servicio" en el frontend usaba
por error las etiquetas de OTRO enum (TipoOfertaComercialEnum: servicios_
operacionales/compra_energia/comunidad_energetica) contra este campo, cuyo
propio enum solo acepta representacion/comunidad_energetica -- guardar
tiraba 422 siempre. La "solucion" fue dejar de enviar el campo en el
autosave del detalle (ver comentario en OportunidadDetailView.vue), sin
arreglar el enum mal mapeado. Resultado: es imposible ponerle un valor
desde crear o editar, hoy o en el futuro tal como esta.

Distinto de `estado` (tambien deprecado por el mismo traslado del pipeline
a la Oferta, 2026-08-02): esa columna SI tiene datos historicos reales y
se conserva a proposito (ver comentario en el modelo). tipo_servicio nunca
tuvo un valor real que preservar.

Revision ID: 130
Revises: 129
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "130"
down_revision = "129"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM oportunidades WHERE tipo_servicio IS NOT NULL"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 130: oportunidades tiene {n} fila(s) con tipo_servicio "
            f"poblado -- se esperaba 0. Revisar a mano antes de eliminar."
        )

    op.execute("ALTER TABLE oportunidades DROP COLUMN IF EXISTS tipo_servicio")
    op.execute("DROP TYPE IF EXISTS tipo_servicio_oportunidad_enum")


def downgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tipo_servicio_oportunidad_enum AS ENUM
                ('representacion', 'comunidad_energetica');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS tipo_servicio tipo_servicio_oportunidad_enum")
