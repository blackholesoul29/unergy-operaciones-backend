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

revision = "037"
down_revision = ("036", "5650ccf73b5c")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE tipo_contacto_enum AS ENUM "
        "('operacional', 'cgm', 'liquidacion', 'soporte', 'monitoreo')"
    )

    op.execute("""
        CREATE TABLE contactos (
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
    op.execute("CREATE INDEX ix_contactos_cliente_id ON contactos (cliente_id)")

    op.execute("""
        CREATE TABLE proyecto_area_contacto (
            id BIGSERIAL PRIMARY KEY,
            proyecto_id BIGINT NOT NULL REFERENCES proyectos(id),
            tipo tipo_contacto_enum NOT NULL,
            cliente_id BIGINT NOT NULL REFERENCES clientes(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_proyecto_area_contacto_tipo UNIQUE (proyecto_id, tipo)
        )
    """)
    op.execute("CREATE INDEX ix_proyecto_area_contacto_proyecto_id ON proyecto_area_contacto (proyecto_id)")
    op.execute("CREATE INDEX ix_proyecto_area_contacto_cliente_id ON proyecto_area_contacto (cliente_id)")

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
