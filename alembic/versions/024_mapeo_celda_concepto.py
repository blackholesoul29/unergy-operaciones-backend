"""Mapeo de celdas por concepto para el Panel Contable

El parser PROPONE la celda de cada concepto del ER; la usuaria CORRIGE la celda
(hoja!celda) y el sistema RECUERDA el mapeo por (proyecto, concepto) para releer
esa misma celda los próximos meses. Además se guarda un snapshot de las celdas
del ER recalculado por panel, para poder releer una celda sin re-subir el archivo.

Revision ID: 024b
Revises: 024
Create Date: 2026-06-18

Relinealización (nightwatch 2026-06-26): id 024→024b para deshacer la colisión
con 024_informe_tipo_ranking; encadena detrás de 024 (ranking). Cuerpo intacto.
"""
from alembic import op

revision = "024b"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mapeo persistente por (proyecto, concepto): la celda que la usuaria confirmó.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mapeo_celda_concepto (
            id           BIGSERIAL PRIMARY KEY,
            proyecto_id  BIGINT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
            concepto     VARCHAR(255) NOT NULL,
            hoja         VARCHAR(120) NOT NULL,
            celda        VARCHAR(20)  NOT NULL,
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_mapeo_proyecto_concepto UNIQUE (proyecto_id, concepto)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mapeo_proyecto ON mapeo_celda_concepto (proyecto_id)"
    )

    # Snapshot del ER recalculado por panel: {hoja: {coord: valor}} en JSON, para
    # releer una celda al cambiar el mapeo sin volver a subir el archivo.
    op.execute("ALTER TABLE panel_contable ADD COLUMN IF NOT EXISTS er_snapshot TEXT")

    # Celda de origen de cada línea (de qué hoja!celda del ER salió el valor base).
    op.execute("ALTER TABLE panel_contable_linea ADD COLUMN IF NOT EXISTS hoja VARCHAR(120)")
    op.execute("ALTER TABLE panel_contable_linea ADD COLUMN IF NOT EXISTS celda VARCHAR(20)")


def downgrade() -> None:
    op.execute("ALTER TABLE panel_contable_linea DROP COLUMN IF EXISTS celda")
    op.execute("ALTER TABLE panel_contable_linea DROP COLUMN IF EXISTS hoja")
    op.execute("ALTER TABLE panel_contable DROP COLUMN IF EXISTS er_snapshot")
    op.execute("DROP TABLE IF EXISTS mapeo_celda_concepto")
