"""registros: expediente documental por proyecto (documentos + parametros)

Crea las tres tablas de la seccion "Registros":

  documentos_proyecto          casilla del expediente (proceso + numeral de item)
  documentos_proyecto_archivo  archivos montados en cada casilla
  parametros_proyecto          valor de cada dato, una sola vez por proyecto

Se anclan a `proyectos`, no a `registro_conexion`: el expediente existe desde
que existe el proyecto y no depende del flujo de estados del tramite. No se
toca ninguna tabla existente.

Las tres van con guarda `has_table` porque en este backend `create_all()` corre
en el arranque y puede haberlas creado antes de que llegue la migracion (mismo
criterio que 085_contrato_frontera y 086_alertas_vencimiento_ppa).

Revision ID: 126
Revises: 125
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None


def _tabla_existe(bind, nombre: str) -> bool:
    return sa.inspect(bind).has_table(nombre)


def upgrade():
    bind = op.get_bind()

    if not _tabla_existe(bind, "documentos_proyecto"):
        op.create_table(
            "documentos_proyecto",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("proyecto_id", sa.BigInteger(), nullable=False),
            sa.Column("proceso", sa.String(length=10), nullable=False),
            sa.Column("item_codigo", sa.String(length=10), nullable=False),
            sa.Column("estado", sa.String(length=20), nullable=False,
                      server_default="PENDIENTE"),
            sa.Column("radicado", sa.String(length=120), nullable=True),
            sa.Column("fecha_emision", sa.Date(), nullable=True),
            sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
            sa.Column("emisor", sa.String(length=200), nullable=True),
            sa.Column("notas", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["proyecto_id"], ["proyectos.id"],
                                    ondelete="CASCADE"),
            sa.UniqueConstraint("proyecto_id", "proceso", "item_codigo",
                                name="uq_documentos_proyecto_item"),
        )
        op.create_index("ix_documentos_proyecto_proyecto_id",
                        "documentos_proyecto", ["proyecto_id"])
        op.create_index("ix_documentos_proyecto_proyecto_proceso",
                        "documentos_proyecto", ["proyecto_id", "proceso"])

    if not _tabla_existe(bind, "documentos_proyecto_archivo"):
        op.create_table(
            "documentos_proyecto_archivo",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("documento_id", sa.BigInteger(), nullable=False),
            sa.Column("origen", sa.String(length=10), nullable=False,
                      server_default="LINK"),
            sa.Column("url", sa.String(length=1000), nullable=False),
            sa.Column("nombre_archivo", sa.String(length=500), nullable=True),
            sa.Column("drive_file_id", sa.String(length=120), nullable=True),
            sa.Column("tamano_bytes", sa.Integer(), nullable=True),
            sa.Column("tipo_mime", sa.String(length=120), nullable=True),
            sa.Column("subido_por", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["documento_id"], ["documentos_proyecto.id"],
                                    ondelete="CASCADE"),
        )
        op.create_index("ix_documentos_proyecto_archivo_documento_id",
                        "documentos_proyecto_archivo", ["documento_id"])

    if not _tabla_existe(bind, "parametros_proyecto"):
        op.create_table(
            "parametros_proyecto",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column("proyecto_id", sa.BigInteger(), nullable=False),
            sa.Column("clave", sa.String(length=120), nullable=False),
            # equipo_tipo y equipo_posicion NO son nulables a proposito: en
            # Postgres dos NULL no colisionan, asi que con columnas nulables la
            # restriccion de unicidad de abajo no impediria guardar el mismo
            # parametro dos veces -- que es justo lo que este modulo evita.
            sa.Column("equipo_tipo", sa.String(length=40), nullable=False,
                      server_default=""),
            sa.Column("equipo_posicion", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("valor", sa.Text(), nullable=True),
            sa.Column("valor_numero", sa.Numeric(), nullable=True),
            sa.Column("valor_fecha", sa.Date(), nullable=True),
            sa.Column("documento_origen_id", sa.BigInteger(), nullable=True),
            sa.Column("verificado", sa.Boolean(), nullable=False,
                      server_default=sa.text("false")),
            sa.Column("notas", sa.Text(), nullable=True),
            sa.Column("actualizado_por", sa.String(length=200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["proyecto_id"], ["proyectos.id"],
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["documento_origen_id"],
                                    ["documentos_proyecto.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("proyecto_id", "clave", "equipo_tipo",
                                "equipo_posicion",
                                name="uq_parametros_proyecto_clave"),
        )
        op.create_index("ix_parametros_proyecto_proyecto_id",
                        "parametros_proyecto", ["proyecto_id"])
        op.create_index("ix_parametros_proyecto_clave",
                        "parametros_proyecto", ["clave"])


def downgrade():
    # Orden inverso por las llaves foraneas: parametros apunta a documentos.
    op.drop_table("parametros_proyecto")
    op.drop_table("documentos_proyecto_archivo")
    op.drop_table("documentos_proyecto")
