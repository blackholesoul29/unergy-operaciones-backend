"""Fusionar proyecto_inicio_operacion en proyecto_informe_om

Auditoria de "Informe de Puesta en Marcha" 2026-08-31: proyecto_informe_om
tiene 0 filas en produccion (nadie ha guardado nunca un informe) en parte
porque depende de datos (fechas, checklist, pendientes) que solo vivian en
proyecto_inicio_operacion -- tabla que perdio su unico editor el 2026-08-21
y desde entonces no tiene ningun endpoint que la escriba (quedo con 2 filas
de prototipo, no historia real). Un proyecto nuevo no tenia forma de
completar esos datos.

Se fusiona todo en proyecto_informe_om (la tabla con el flujo vivo, el unico
PUT real) y se retira proyecto_inicio_operacion por completo. El checklist
tecnico se estructura en 4 columnas tipadas (antes era un JSONB `checklist`
sin ningun esquema en BD) cubriendo solo las 4 categorias que ya se
resumian en un semaforo -- el resto del catalogo viejo (CCTV, cableado
MT/BT, transformadores, tableros, shelter, obras civiles, paneles,
trackers, checklist detallado por inversor) no se revive, nunca tuvo lector
real (ver docstring de ProyectoInformeOM).

Se agrega ademas un campo `estado` propio (borrador/en_revision/aprobado)
que reemplaza el envio a InformeGuardado/app/api/v1/informes.py (sistema
generico compartido con Mensuales/Portafolio/Ranking, revisor hardcodeado
por email, desconectado de esta ficha).

Revision ID: 133
Revises: 132
Create Date: 2026-08-31
"""
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic_idempotencia import agregar_columna_si_falta, tabla_existe
import sqlalchemy as sa

revision = "133"
down_revision = "132"
branch_labels = None
depends_on = None

_COLUMNAS_NUEVAS = [
    sa.Column("empresa_contratista", sa.String(255), nullable=True),
    sa.Column("fecha_energizacion", sa.Date, nullable=True),
    sa.Column("fecha_inicio_operacion", sa.Date, nullable=True),
    sa.Column("pendientes", postgresql.JSONB, nullable=False, server_default="[]"),
    sa.Column("checklist_fusion_solar", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_frontera", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_estacion_meteo", postgresql.JSONB, nullable=False, server_default="{}"),
    sa.Column("checklist_reconectador", postgresql.JSONB, nullable=False, server_default="{}"),
]


def upgrade():
    bind = op.get_bind()

    for columna in _COLUMNAS_NUEVAS:
        agregar_columna_si_falta(bind, "proyecto_informe_om", columna)

    # create_type=False en la columna: sin eso, un op.add_column futuro que
    # toque esta tabla reemitiria CREATE TYPE al reconstruir la columna y
    # reventaria con DuplicateObject si el tipo ya existe (mismo gotcha que
    # la migracion 131, ver alembic_idempotencia.py).
    estado_enum = postgresql.ENUM(
        "borrador", "en_revision", "aprobado", name="estado_informe_om_enum", create_type=False)
    postgresql.ENUM(
        "borrador", "en_revision", "aprobado", name="estado_informe_om_enum"
    ).create(bind, checkfirst=True)
    agregar_columna_si_falta(
        bind, "proyecto_informe_om",
        sa.Column("estado", estado_enum, nullable=False, server_default="borrador"),
    )

    if not tabla_existe(bind, "proyecto_inicio_operacion"):
        return

    filas = bind.execute(text(
        "SELECT proyecto_id, empresa_contratista, fecha_energizacion, "
        "fecha_inicio_operacion, pendientes, checklist FROM proyecto_inicio_operacion"
    )).mappings().all()

    # Guard: verificado en produccion 2026-08-31 -- proyecto 230 todo NULL,
    # proyecto 52 solo fecha_inicio_operacion, checklist casi vacio en ambas.
    # Si aparece un checklist real con contenido, alguien debe revisarlo a
    # mano antes de perderlo -- no tiene forma de mapearse a las 4 columnas
    # tipadas nuevas sin decidir a mano el traslado.
    for fila in filas:
        checklist = fila["checklist"] or {}
        if checklist and any(checklist.values()):
            raise RuntimeError(
                f"Migracion 133: proyecto_inicio_operacion.proyecto_id={fila['proyecto_id']} "
                f"tiene contenido real en 'checklist' -- revisar a mano antes de fusionar "
                f"(las 4 columnas checklist_* nuevas no son un mapeo automatico del checklist viejo)."
            )

    for fila in filas:
        if not any((fila["empresa_contratista"], fila["fecha_energizacion"],
                    fila["fecha_inicio_operacion"], fila["pendientes"])):
            continue
        bind.execute(text("""
            INSERT INTO proyecto_informe_om (proyecto_id, empresa_contratista,
                fecha_energizacion, fecha_inicio_operacion, pendientes)
            VALUES (:proyecto_id, :empresa_contratista, :fecha_energizacion,
                :fecha_inicio_operacion, :pendientes)
            ON CONFLICT (proyecto_id) DO UPDATE SET
                empresa_contratista = COALESCE(proyecto_informe_om.empresa_contratista, EXCLUDED.empresa_contratista),
                fecha_energizacion = COALESCE(proyecto_informe_om.fecha_energizacion, EXCLUDED.fecha_energizacion),
                fecha_inicio_operacion = COALESCE(proyecto_informe_om.fecha_inicio_operacion, EXCLUDED.fecha_inicio_operacion),
                pendientes = CASE WHEN proyecto_informe_om.pendientes = '[]'::jsonb
                                   THEN EXCLUDED.pendientes ELSE proyecto_informe_om.pendientes END
        """), dict(fila))

    op.execute("DROP TABLE proyecto_inicio_operacion")


def downgrade():
    # Perdida aceptada para las columnas nuevas y para proyecto_inicio_operacion
    # -- mismo criterio que las migraciones 117/130: no hay contenido real que
    # valga la pena reconstruir (2 filas de prototipo, 0 fichas de informe_om).
    op.execute("""
        CREATE TABLE IF NOT EXISTS proyecto_inicio_operacion (
            id                      BIGSERIAL PRIMARY KEY,
            proyecto_id             BIGINT NOT NULL UNIQUE REFERENCES proyectos(id),
            empresa_contratista     VARCHAR(255),
            fecha_energizacion      DATE,
            fecha_inicio_operacion  DATE,
            checklist               JSONB NOT NULL DEFAULT '{}'::jsonb,
            pruebas                 JSONB NOT NULL DEFAULT '{}'::jsonb,
            documentos              JSONB NOT NULL DEFAULT '{}'::jsonb,
            pendientes              JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_proyecto_inicio_operacion_proyecto_id "
        "ON proyecto_inicio_operacion(proyecto_id)"
    )
    op.execute("ALTER TABLE proyecto_informe_om DROP COLUMN IF EXISTS estado")
    op.execute("DROP TYPE IF EXISTS estado_informe_om_enum")
    for columna in _COLUMNAS_NUEVAS:
        op.execute(f"ALTER TABLE proyecto_informe_om DROP COLUMN IF EXISTS {columna.name}")
