"""Catálogo de Operadores de Red y sus contactos, + vínculo fronteras.operador_red_id.

Primer paso de la integración del reporte CGM a la plataforma (envío del
reporte a los operadores de red). fronteras.operador_red sigue existiendo
como texto (viene de GESCON, ya es confiable) -- esta migración agrega la
relación estructurada por encima, sin duplicar el dato en `proyectos` para
no repetir el problema de sincronización que se corrigió hoy con
fronteras.proyecto_id.

Revision ID: 033
Revises: 032
Create Date: 2026-07-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS en cada paso: esta migración se cortó a medias en un deploy
    # (quedaron las tablas creadas pero no la columna/seed/backfill, y
    # alembic_version no se actualizó) -- probablemente por un restart/redeploy
    # concurrente durante el arranque. Con estos guards, reintentarla desde
    # cero es seguro sin importar en qué paso se haya quedado la vez anterior.
    conn = op.get_bind()

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS operadores_red (
            id BIGSERIAL PRIMARY KEY,
            nombre_legal VARCHAR(255) NOT NULL UNIQUE,
            nombre_comercial VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))

    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS operadores_red_contactos (
            id BIGSERIAL PRIMARY KEY,
            operador_red_id BIGINT NOT NULL REFERENCES operadores_red(id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            nombre VARCHAR(255),
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_operadores_red_contactos_operador_red_id "
        "ON operadores_red_contactos (operador_red_id)"
    ))

    conn.execute(sa.text(
        "ALTER TABLE fronteras ADD COLUMN IF NOT EXISTS operador_red_id "
        "BIGINT REFERENCES operadores_red(id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_fronteras_operador_red_id ON fronteras (operador_red_id)"
    ))

    # Seed: los operadores reales que ya aparecen en fronteras.operador_red
    # (texto de GESCON). nombre_comercial solo se pone cuando ya se veía usado
    # en proyectos.operador_red (Afinia/Air-e/ESSA) -- para los otros 4 no se
    # inventa un nombre comercial sin confirmar.
    operadores = [
        ("CARIBEMAR DE LA COSTA S.A.S. E.S.P. - DISTRIBUIDOR", "Afinia"),
        ("AIR-E S.A.S. E.S.P. - DISTRIBUIDOR", "Air-e"),
        ("ELECTRIFICADORA DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR", "ESSA"),
        ("CENTRALES ELECTRICAS DE NARIÑO S.A. E.S.P. - DISTRIBUIDOR", None),
        ("CENTRALES ELECTRICAS DEL NORTE DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR", None),
        ("EMPRESA DE ENERGIA DE CASANARE S.A. E.S.P. - DISTRIBUIDOR", None),
        ("EMPRESAS PUBLICAS DE MEDELLIN E.S.P. - DISTRIBUIDOR", None),
    ]
    for nombre_legal, nombre_comercial in operadores:
        conn.execute(sa.text("""
            INSERT INTO operadores_red (nombre_legal, nombre_comercial)
            VALUES (:legal, :comercial)
            ON CONFLICT (nombre_legal) DO NOTHING
        """), {"legal": nombre_legal, "comercial": nombre_comercial})

    # Backfill: fronteras.operador_red_id a partir del texto ya existente
    # (match exacto -- ambos valores vienen literalmente de GESCON, sin
    # necesidad de fuzzy matching). Re-ejecutar esto no hace daño: solo
    # actualiza filas cuyo texto coincide con el catálogo.
    conn.execute(sa.text("""
        UPDATE fronteras f
        SET operador_red_id = o.id
        FROM operadores_red o
        WHERE f.operador_red = o.nombre_legal
          AND (f.operador_red_id IS NULL OR f.operador_red_id <> o.id)
    """))


def downgrade() -> None:
    op.drop_index("ix_fronteras_operador_red_id", table_name="fronteras")
    op.drop_column("fronteras", "operador_red_id")
    op.drop_table("operadores_red_contactos")
    op.drop_table("operadores_red")
