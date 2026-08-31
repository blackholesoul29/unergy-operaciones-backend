"""eliminar tiene_promotor/promotor_tarifa/promotor_condiciones + valor 'promotor' del enum

Auditoria de campos de ContratoServicio 2026-08-28. `tiene_promotor` (True en
0/162), `promotor_tarifa` (0/162) y `promotor_condiciones` (0/162) nunca se
usaron -- ni siquiera para los 3 proyectos que SI tienen `Proyecto.srv_promotor
= true` (bandera separada e independiente, a nivel de Proyecto, que se
conserva intacta: no es candidata, tiene uso real). Los terminos financieros
de esos 3 promotores reales nunca se cargaron en `contratos_servicio`.

`servicio_aplica='promotor'` (el tipo de contrato standalone, distinto del
flag `tiene_promotor` dentro de un contrato de Representacion) tambien esta en
0/162 y, a diferencia de 'operacion', nunca aparece como opcion alcanzable en
el frontend (ni siquiera un boton roto) -- confirmado sin ningun `'promotor'`
literal en app/features/**.

Postgres no soporta `ALTER TYPE ... DROP VALUE`: se recrea el tipo sin ese
valor (mismo patron que las migraciones 063 y 125).

Revision ID: 126
Revises: 125
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM contratos_servicio "
        "WHERE servicio_aplica = 'promotor' OR tiene_promotor = true "
        "OR promotor_tarifa IS NOT NULL OR promotor_condiciones IS NOT NULL"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 126: contratos_servicio tiene {n} fila(s) usando "
            f"promotor (servicio_aplica, tiene_promotor o sus campos) -- se "
            f"esperaba 0. Revisar a mano antes de eliminar."
        )

    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS tiene_promotor")
    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS promotor_tarifa")
    op.execute("ALTER TABLE contratos_servicio DROP COLUMN IF EXISTS promotor_condiciones")

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE servicio_aplica_enum_v2 AS ENUM
                ('representacion', 'cgm', 'rec', 'mantenimiento',
                 'arriendo', 'internet');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute(
        "ALTER TABLE contratos_servicio ALTER COLUMN servicio_aplica TYPE servicio_aplica_enum_v2 "
        "USING servicio_aplica::text::servicio_aplica_enum_v2"
    )
    op.execute("DROP TYPE servicio_aplica_enum")
    op.execute("ALTER TYPE servicio_aplica_enum_v2 RENAME TO servicio_aplica_enum")


def downgrade():
    op.execute("ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'promotor'")
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS tiene_promotor BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS promotor_tarifa NUMERIC(12,4)")
    op.execute("ALTER TABLE contratos_servicio ADD COLUMN IF NOT EXISTS promotor_condiciones TEXT")
