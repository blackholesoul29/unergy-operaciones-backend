"""add om_pagina_sin_match table

Motivo: las paginas del PDF consolidado de Mantenimiento que no logran
emparejarse a un contrato (sin_match) solo vivian en la respuesta HTTP del
momento del upload -- no habia forma de revisarlas despues ni de asignarlas
manualmente a un proyecto. Esta tabla las persiste para poder mostrarlas en
Proveedor entre recargas y resolverlas via PATCH /om/factura/{periodo}/sin-match/{id}/asignar.

Revision ID: 049
Revises: 048
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_COLUMNAS_ESPERADAS = {
    "id", "periodo", "pagina", "nombre_extraido", "estrategia", "razon",
    "numero_factura", "muestra_texto", "origen", "resuelto",
    "contrato_id_asignado", "asignado_en", "created_at",
}


def _verificar_columnas(bind, tabla: str, esperadas: set[str]) -> None:
    # Mismo chequeo que 037_contactos_unificados.py: un "ya existe" aceptado
    # a ciegas puede ser una tabla incompleta de un deploy anterior.
    reales = {r[0] for r in bind.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    ), {"t": tabla})}
    faltantes = esperadas - reales
    if faltantes:
        raise RuntimeError(
            f"Migración 049: la tabla '{tabla}' ya existía pero le faltan columnas "
            f"que esta migración espera: {sorted(faltantes)}. Revisar a mano antes "
            f"de reintentar."
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Fix 2026-08-19: create_all() (ver init_db.py, corre antes de Alembic
    # en cada boot) ya había creado esta tabla a partir del modelo ORM
    # app/models/om.py -- este create_table() sin guarda tronaba con
    # DuplicateTable y hacía rollback de TODA la cadena de migraciones
    # pendientes en el mismo `alembic upgrade head` (una sola transacción).
    ya_existia = bind.execute(text("SELECT to_regclass('om_pagina_sin_match')")).scalar() is not None

    if ya_existia:
        _verificar_columnas(bind, "om_pagina_sin_match", _COLUMNAS_ESPERADAS)
        # create_all() no aplica server_default (solo el default= de Python
        # del ORM), así que la tabla quedó sin default a nivel de BD en estas
        # dos columnas NOT NULL -- un INSERT que no pase por el ORM violaría
        # NOT NULL. Ver mismo patrón en contactos.recibe_notificaciones.
        op.execute("ALTER TABLE om_pagina_sin_match ALTER COLUMN origen SET DEFAULT 'upload'")
        op.execute("ALTER TABLE om_pagina_sin_match ALTER COLUMN resuelto SET DEFAULT false")
        return

    op.create_table(
        "om_pagina_sin_match",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("periodo", sa.String(7), nullable=False, index=True),
        sa.Column("pagina", sa.Integer, nullable=False),
        sa.Column("nombre_extraido", sa.String(300), nullable=True),
        sa.Column("estrategia", sa.String(30), nullable=True),
        sa.Column("razon", sa.String(200), nullable=False),
        sa.Column("numero_factura", sa.String(30), nullable=True),
        sa.Column("muestra_texto", sa.String(500), nullable=True),
        sa.Column("origen", sa.String(20), nullable=False, server_default="upload"),
        sa.Column("resuelto", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("contrato_id_asignado", sa.BigInteger,
                  sa.ForeignKey("contratos_servicio.id"), nullable=True),
        sa.Column("asignado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
        sa.UniqueConstraint("periodo", "pagina",
                            name="uq_om_sin_match_periodo_pagina"),
    )


def downgrade() -> None:
    op.drop_table("om_pagina_sin_match")
