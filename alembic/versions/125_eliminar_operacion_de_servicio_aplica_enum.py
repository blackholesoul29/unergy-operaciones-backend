"""eliminar 'operacion' del enum servicio_aplica_enum

Auditoria de campos de ContratoServicio 2026-08-28. `servicio_aplica='operacion'`
nunca se uso en produccion (0/162): el contrato real de Operacion y
Mantenimiento se guarda con `servicio_aplica='mantenimiento'` (o `arriendo`/
`internet`, segun el sub-tipo) -- el propio frontend ya trabajaba alrededor
de esto (ver comentario en ServiciosUnificadoView.vue: pedir ?tipo=operacion
siempre devolvia 0 filas).

De paso se corrigio un bug real: `app/api/v1/monitoreo.py` (_action_get_all_
contratos/_action_get_fmo_data, consumidos por el informe mensual FMO O&M)
filtraba por este mismo valor muerto y por eso jamas encontraba el contrato
real de mantenimiento de ningun proyecto.

Postgres no soporta `ALTER TYPE ... DROP VALUE`: se recrea el tipo sin ese
valor (mismo patron que la migracion 063).

Revision ID: 125
Revises: 124
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM contratos_servicio WHERE servicio_aplica = 'operacion'"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 125: contratos_servicio tiene {n} fila(s) con "
            f"servicio_aplica='operacion' -- se esperaba 0. Revisar a mano "
            f"antes de eliminar el valor del enum."
        )

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE servicio_aplica_enum_v2 AS ENUM
                ('representacion', 'cgm', 'promotor', 'rec', 'mantenimiento',
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
    op.execute("ALTER TYPE servicio_aplica_enum ADD VALUE IF NOT EXISTS 'operacion'")
