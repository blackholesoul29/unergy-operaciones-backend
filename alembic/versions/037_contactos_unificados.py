"""Unificar contactos en el directorio de Cliente + puntero por área en Proyecto.

Diseño: los correos reales viven SIEMPRE en `contactos` (cliente_id NOT NULL).
Un Proyecto nunca guarda un correo suelto -- si para un `tipo` (área) necesita
un contacto distinto al de su cliente titular, apunta a otro Cliente vía
`proyecto_area_contacto` (proyecto_id, tipo, cliente_id). Mismo patrón que ya
usa `ProyectoInversionista.cliente_id`: el proyecto referencia OTRO cliente
para un propósito puntual, no inventa un contacto ad-hoc.

Sustituye `proyecto_contactos` (confirmado vacía en producción, 0 filas — se
puede reemplazar sin backfill de ese lado) y los 7 campos de correo sueltos de
`clientes` (correo_electronico se deja intacto: no es un canal de
notificación, es la llave de conciliación con Origina en
app/services/correlation.py).

También sirve de merge: el árbol de revisiones tenía dos heads sin fusionar
(036 y 5650ccf73b5c) — probablemente por dos ramas de trabajo en paralelo.

Revision ID: 037
Revises: 036, 5650ccf73b5c
Create Date: 2026-07-07
"""
from alembic import op
from sqlalchemy import text

revision = "037"
down_revision = ("036", "5650ccf73b5c")
branch_labels = None
depends_on = None

# Fix 2026-08-19: "ya existe" (CREATE ... IF NOT EXISTS / duplicate_object)
# antes se aceptaba a ciegas -- si el objeto preexistente venía de un deploy
# anterior que murió a medio camino, quedaba con una forma incompleta y
# nadie se enteraba hasta que algo MUY más adelante (una query cualquiera)
# tronaba con un error que no apuntaba de vuelta a esta migración. Ahora se
# verifica la forma real contra la esperada y se falla FUERTE, aquí mismo,
# si no coincide -- igual que fallaba antes del fix de idempotencia
# (b1a9b61), pero solo cuando de verdad hay algo mal, no en cualquier
# reintento legítimo.


def _verificar_columnas(bind, tabla: str, esperadas: set[str]) -> None:
    reales = {
        r[0] for r in bind.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
        ), {"t": tabla})
    }
    faltantes = esperadas - reales
    if faltantes:
        raise RuntimeError(
            f"Migración 037: la tabla '{tabla}' ya existía pero le faltan columnas "
            f"que esta migración espera: {sorted(faltantes)}. Probablemente quedó de "
            f"un deploy anterior que murió a medio camino -- revisar a mano antes de "
            f"reintentar (no se puede resolver solo con CREATE TABLE IF NOT EXISTS)."
        )


def _verificar_constraint(bind, tabla: str, constraint: str) -> None:
    existe = bind.execute(text(
        "SELECT 1 FROM information_schema.table_constraints "
        "WHERE table_name = :t AND constraint_name = :c"
    ), {"t": tabla, "c": constraint}).first()
    if not existe:
        raise RuntimeError(
            f"Migración 037: la tabla '{tabla}' ya existía pero le falta la "
            f"constraint '{constraint}' -- probablemente un deploy anterior murió "
            f"a medio camino. Revisar a mano antes de reintentar."
        )


def _verificar_enum(bind, tipo: str, esperados: set[str]) -> None:
    reales = {
        r[0] for r in bind.execute(text(
            "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
            "WHERE t.typname = :t"
        ), {"t": tipo})
    }
    faltantes = esperados - reales
    if faltantes:
        raise RuntimeError(
            f"Migración 037: el tipo '{tipo}' ya existía pero le faltan valores "
            f"que esta migración espera: {sorted(faltantes)}. Probablemente quedó "
            f"de un deploy anterior que murió a medio camino -- revisar a mano "
            f"antes de reintentar."
        )


def upgrade() -> None:
    bind = op.get_bind()

    # CREATE TYPE no soporta IF NOT EXISTS en Postgres -- si un intento de
    # deploy anterior murio a medio camino (tipo creado, migracion sin marcar
    # como aplicada), el proximo intento debe poder re-ejecutar esto sin tronar.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tipo_contacto_enum AS ENUM
                ('operacional', 'cgm', 'liquidacion', 'soporte', 'monitoreo');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    _verificar_enum(bind, "tipo_contacto_enum",
                     {"operacional", "cgm", "liquidacion", "soporte", "monitoreo"})

    op.execute("""
        CREATE TABLE IF NOT EXISTS contactos (
            id BIGSERIAL PRIMARY KEY,
            cliente_id BIGINT NOT NULL REFERENCES clientes(id),
            nombre VARCHAR(255),
            email VARCHAR(255) NOT NULL,
            tipo tipo_contacto_enum NOT NULL,
            recibe_notificaciones BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_contacto_cliente_email_tipo UNIQUE (cliente_id, email, tipo)
        )
    """)
    _verificar_columnas(bind, "contactos", {
        "id", "cliente_id", "nombre", "email", "tipo",
        "recibe_notificaciones", "created_at", "updated_at",
    })
    _verificar_constraint(bind, "contactos", "uq_contacto_cliente_email_tipo")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contactos_cliente_id ON contactos (cliente_id)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS proyecto_area_contacto (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            tipo tipo_contacto_enum NOT NULL,
            cliente_id BIGINT NOT NULL REFERENCES clientes(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_proyecto_area_contacto_tipo UNIQUE (proyecto_id, tipo)
        )
    """)
    _verificar_columnas(bind, "proyecto_area_contacto", {
        "id", "proyecto_id", "tipo", "cliente_id", "created_at", "updated_at",
    })
    _verificar_constraint(bind, "proyecto_area_contacto", "uq_proyecto_area_contacto_tipo")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proyecto_area_contacto_proyecto_id ON proyecto_area_contacto (proyecto_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proyecto_area_contacto_cliente_id ON proyecto_area_contacto (cliente_id)")

    # ── Backfill desde clientes ─────────────────────────────────────────────
    # Campos escalares → una fila por cliente si tienen valor.
    for columna, tipo in (
        ("correo_operacional", "operacional"),
        ("correo_liquidacion", "liquidacion"),
        ("correo_monitoreo", "monitoreo"),
        ("correo_soporte", "soporte"),
    ):
        op.execute(f"""
            INSERT INTO contactos (cliente_id, email, tipo)
            SELECT id, lower(trim({columna})), '{tipo}'
            FROM clientes
            WHERE {columna} IS NOT NULL AND trim({columna}) <> ''
            ON CONFLICT (cliente_id, email, tipo) DO NOTHING
        """)

    # Arrays JSONB → una fila por elemento.
    for columna, tipo in (
        ("correos_operacionales", "operacional"),
        ("correos_cgm", "cgm"),
    ):
        op.execute(f"""
            INSERT INTO contactos (cliente_id, email, tipo)
            SELECT c.id, lower(trim(e)), '{tipo}'
            FROM clientes c, jsonb_array_elements_text(COALESCE(c.{columna}, '[]'::jsonb)) AS e
            WHERE trim(e) <> ''
            ON CONFLICT (cliente_id, email, tipo) DO NOTHING
        """)

    # proyecto_contactos está vacía en producción — se elimina sin backfill
    # (y aunque tuviera filas, no aplicaría: ahora el override de proyecto es
    # un puntero a Cliente, no un correo suelto).
    op.execute("DROP TABLE IF EXISTS proyecto_contactos")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE proyecto_contactos (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            nombre VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            tipo VARCHAR(50),
            recibe_notificaciones BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_proyecto_contactos_proyecto_id ON proyecto_contactos (proyecto_id)")
    op.execute("DROP TABLE IF EXISTS proyecto_area_contacto")
    op.execute("DROP TABLE IF EXISTS contactos")
    op.execute("DROP TYPE IF EXISTS tipo_contacto_enum")
