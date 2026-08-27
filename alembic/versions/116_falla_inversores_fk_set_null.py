"""falla_inversores.proyecto_inversor_id: FK a ON DELETE SET NULL

Auditoria de integridad de Proyectos/Fallas (2026-08-27), a raiz de la
limpieza de proyecto_inversores de hoy. El propio docstring del modelo
`FallaInversor` documenta que "proyecto_inversor_id puede quedar NULL
si el inversor se borra del catalogo" (nombre/potencia_kw quedan de
snapshot para conservar el reporte historico) -- pero la tabla, creada
via `Base.metadata.create_all()` (nunca tuvo migracion Alembic propia),
quedo con el FK en NO ACTION (el default de Postgres), no en SET NULL.

Con 4213 filas reales en falla_inversores, borrar cualquier
ProyectoInversor con al menos una falla historica asociada revienta
con un IntegrityError sin capturar (500) en vez de retirarse
limpiamente como documenta el modelo.

Revision ID: 116
Revises: 115
Create Date: 2026-08-27
"""
from alembic import op

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE falla_inversores "
        "DROP CONSTRAINT falla_inversores_proyecto_inversor_id_fkey"
    )
    op.execute(
        "ALTER TABLE falla_inversores "
        "ADD CONSTRAINT falla_inversores_proyecto_inversor_id_fkey "
        "FOREIGN KEY (proyecto_inversor_id) REFERENCES proyecto_inversores(id) "
        "ON DELETE SET NULL"
    )


def downgrade():
    op.execute(
        "ALTER TABLE falla_inversores "
        "DROP CONSTRAINT falla_inversores_proyecto_inversor_id_fkey"
    )
    op.execute(
        "ALTER TABLE falla_inversores "
        "ADD CONSTRAINT falla_inversores_proyecto_inversor_id_fkey "
        "FOREIGN KEY (proyecto_inversor_id) REFERENCES proyecto_inversores(id)"
    )
