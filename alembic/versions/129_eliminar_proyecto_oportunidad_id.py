"""eliminar proyectos.oportunidad_id (reemplazado por la M2M via oferta)

Auditoria de Proyectos 2026-08-28. `oportunidad_id` estaba en 0/188 y
alimentaba una seccion rota del CRM: la lista de "proyectos vinculados" del
detalle de Oportunidad (GET /comercial/oportunidades/{id}) y los campos
num_proyectos/capacidad_total_kwp del listado (GET /comercial/oportunidades)
siempre daban vacio/cero para cualquier oportunidad, aunque tuviera plantas
reales colgadas de sus ofertas -- el resto del pipeline (incluyendo
/proyectos-operando, la superficie de integracion externa) ya resolvia los
proyectos de una oportunidad via sus Ofertas y la M2M
`oportunidad_oferta_proyectos`, nunca via esta columna.

El unico escritor real era `POST /comercial/backfill` (migracion inicial de
clientes historicos sin Oportunidad) -- se corrigio para usar la misma M2M
en vez de esta columna. Con eso, ya no queda ningun lector ni escritor.

Revision ID: 129
Revises: 128
Create Date: 2026-08-28
"""
from alembic import op
from sqlalchemy import text

revision = "129"
down_revision = "128"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    n = bind.execute(text(
        "SELECT count(*) FROM proyectos WHERE oportunidad_id IS NOT NULL"
    )).scalar()
    if n:
        raise RuntimeError(
            f"Migracion 129: proyectos tiene {n} fila(s) con oportunidad_id "
            f"poblado -- se esperaba 0. Revisar a mano antes de eliminar "
            f"(podria perderse un vinculo real que ya no se resuelve por la M2M)."
        )

    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS oportunidad_id")


def downgrade():
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS oportunidad_id BIGINT REFERENCES oportunidades(id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proyectos_oportunidad_id ON proyectos (oportunidad_id)")
