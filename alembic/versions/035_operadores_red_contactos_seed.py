"""Sembrar correos reales de Operadores de Red + columna clientes.correos_cgm.

Segundo paso de la integración del reporte CGM a la plataforma (ver 033).
Carga los correos de contacto de los operadores de red que ya se usan hoy
en el script standalone (ReporteCGM/operadores.csv) para CENS, AIR-E y ESSA.
No se migra el correo de "COX" porque no es un operador de red real -- es
el cliente/inversionista del proyecto; ese correo se carga manualmente
desde la ficha del cliente una vez exista el campo `correos_cgm`.

Revision ID: 035
Revises: 034
Create Date: 2026-07-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


CONTACTOS_POR_OPERADOR = {
    "CENTRALES ELECTRICAS DEL NORTE DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR": [
        "LANDIS.CAMARGO@cens.com.co",
        "DARWIN.ORDUZ@cens.com.co",
        "Grupo.Telemedida@cens.com.co",
        "RUBEN.TARAZONA@cens.com.co",
        "ANDERSON.PENA@cens.com.co",
        "Edgar.Mojica@cens.com.co",
    ],
    "AIR-E S.A.S. E.S.P. - DISTRIBUIDOR": [
        "Cgmair-e@air-e.com",
    ],
    "ELECTRIFICADORA DE SANTANDER S.A. E.S.P. - DISTRIBUIDOR": [
        "AtencionCGM@essa.com.co",
    ],
}


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS correos_cgm JSONB DEFAULT '[]'::jsonb"
    ))

    for nombre_legal, correos in CONTACTOS_POR_OPERADOR.items():
        operador_id = conn.execute(sa.text(
            "SELECT id FROM operadores_red WHERE nombre_legal = :nombre"
        ), {"nombre": nombre_legal}).scalar()
        if operador_id is None:
            continue
        for email in correos:
            conn.execute(sa.text("""
                INSERT INTO operadores_red_contactos (operador_red_id, email)
                SELECT :operador_id, :email
                WHERE NOT EXISTS (
                    SELECT 1 FROM operadores_red_contactos
                    WHERE operador_red_id = :operador_id AND email = :email
                )
            """), {"operador_id": operador_id, "email": email})


def downgrade() -> None:
    conn = op.get_bind()
    for correos in CONTACTOS_POR_OPERADOR.values():
        for email in correos:
            conn.execute(sa.text(
                "DELETE FROM operadores_red_contactos WHERE email = :email"
            ), {"email": email})
    op.drop_column("clientes", "correos_cgm")
