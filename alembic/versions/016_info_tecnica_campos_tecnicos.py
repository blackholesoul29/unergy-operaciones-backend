"""Agregar campos técnicos a proyecto_info_tecnica

Revision ID: 016
Revises: 015
Create Date: 2026-06-09
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

COLS = [
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS voltaje_red VARCHAR(50)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS potencia_panel_kwp VARCHAR(100)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS cantidad_inversores INTEGER",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS potencia_inversores_kwp VARCHAR(100)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS potencia_ac_kw NUMERIC(12,3)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS capacidad_instalada_kwp NUMERIC(12,3)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS cantidad_strings INTEGER",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS tipo_tracker VARCHAR(10)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_paneles VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_inversores VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_transformador VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_reconectador_rele VARCHAR(500)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_totalizador VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_seguidor_solar VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_medidores_frontera VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_modem_reconectador VARCHAR(500)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_modems_frontera VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS cctv_estado TEXT",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS marca_cctv VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS seguridad_fisica VARCHAR(255)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS tiene_internet VARCHAR(10)",
    "ALTER TABLE proyecto_info_tecnica ADD COLUMN IF NOT EXISTS ip_modem_reconectador VARCHAR(100)",
]

DROP_COLS = [
    "voltaje_red", "potencia_panel_kwp", "cantidad_inversores", "potencia_inversores_kwp",
    "potencia_ac_kw", "capacidad_instalada_kwp", "cantidad_strings", "tipo_tracker",
    "marca_paneles", "marca_inversores", "marca_transformador", "marca_reconectador_rele",
    "marca_totalizador", "marca_seguidor_solar", "marca_medidores_frontera",
    "marca_modem_reconectador", "marca_modems_frontera", "cctv_estado", "marca_cctv",
    "seguridad_fisica", "tiene_internet", "ip_modem_reconectador",
]


def upgrade() -> None:
    for sql in COLS:
        op.execute(sql)


def downgrade() -> None:
    for col in DROP_COLS:
        op.execute(f"ALTER TABLE proyecto_info_tecnica DROP COLUMN IF EXISTS {col}")
