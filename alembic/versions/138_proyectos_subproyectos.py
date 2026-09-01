"""Agregar proyectos.proyecto_padre_id (subproyectos de autoconsumo)

Un autoconsumo repartido en varias conexiones -- Laureles Campestre, IML,
Clinica Somer, San Esteban, Coopsana -- es UN proyecto, no cinco plantas. Hasta
ahora cada conexion era una fila suelta y las que no tenian fila propia no
existian en la plataforma.

La jerarquia es de UN solo nivel (padre -> conexiones), igual que en Unergy,
donde un `subproject` no tiene subproyectos. El hijo lleva su conexion en
`sub_project`; el padre no lleva ninguna, porque consultar generacion con el
topico del padre (`iml`, `laurelescampestre`, `somer`) devuelve cero lecturas
-- los datos solo existen a nivel de subproyecto. El padre si lleva
`topico_liquidaciones`: en Unergy la liquidacion es a nivel de padre.

NULL = proyecto suelto, que es el caso de la enorme mayoria, asi que la columna
entra sin default y sin tocar ninguna fila existente.

Revision ID: 138
Revises: 137
Create Date: 2026-09-01
"""
from alembic import op

revision = "138"
down_revision = "137"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE proyectos ADD COLUMN IF NOT EXISTS proyecto_padre_id BIGINT")
    op.execute(
        "ALTER TABLE proyectos DROP CONSTRAINT IF EXISTS fk_proyectos_proyecto_padre_id"
    )
    op.execute(
        "ALTER TABLE proyectos ADD CONSTRAINT fk_proyectos_proyecto_padre_id "
        "FOREIGN KEY (proyecto_padre_id) REFERENCES proyectos(id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyectos_proyecto_padre_id "
        "ON proyectos (proyecto_padre_id)"
    )
    # Un proyecto no puede ser su propio padre. No cubre ciclos de mas de un
    # salto, pero la jerarquia es de un solo nivel por diseno y el chequeo
    # barato ataja el error real: pegarse el propio id al editar. Los ciclos
    # largos los rechaza la API (_verificar_padre en app/api/v1/proyectos.py).
    op.execute(
        "ALTER TABLE proyectos DROP CONSTRAINT IF EXISTS ck_proyectos_padre_no_es_si_mismo"
    )
    op.execute(
        "ALTER TABLE proyectos ADD CONSTRAINT ck_proyectos_padre_no_es_si_mismo "
        "CHECK (proyecto_padre_id IS NULL OR proyecto_padre_id <> id)"
    )


def downgrade():
    op.execute(
        "ALTER TABLE proyectos DROP CONSTRAINT IF EXISTS ck_proyectos_padre_no_es_si_mismo"
    )
    op.execute("DROP INDEX IF EXISTS ix_proyectos_proyecto_padre_id")
    op.execute(
        "ALTER TABLE proyectos DROP CONSTRAINT IF EXISTS fk_proyectos_proyecto_padre_id"
    )
    op.execute("ALTER TABLE proyectos DROP COLUMN IF EXISTS proyecto_padre_id")
