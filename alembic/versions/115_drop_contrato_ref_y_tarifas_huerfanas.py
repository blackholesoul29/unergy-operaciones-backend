"""proyecto_inversionistas.contrato_ref + tarifas huérfanas de dos intentos abandonados

Auditoria de integridad de Proyectos (2026-08-27).

`proyecto_inversionistas.contrato_ref`: 0/116 filas pobladas jamás, sin
ninguna vista que lo muestre ni lo edite. Vive en `_PENDING_DDLS`
(migration 008) desde siempre sin que nada lo haya usado nunca.

`tarifa_administracion`/`tarifa_cgm`/`tarifa_representacion` en
`proyecto_inversionistas` Y en `clientes`: restos de DOS intentos
abandonados del mismo feature, ambos el mismo día (2026-04-29):
1. Se agregaron primero a `proyecto_inversionistas` (commit a8c8261,
   "nivel incorrecto" según el propio mensaje).
2. Se movieron a `clientes` (migración 009, script
   cargar_tarifas_clientes.py pobló 27 clientes) -- y minutos después
   TAMBIÉN se revirtió (commit 98a0273).

Ambos reverts borraron modelo y schema del código pero ninguno bajó una
migración de DROP COLUMN, así que las columnas quedaron huérfanas con
datos reales (22/116 filas en proyecto_inversionistas, 25/122 en
clientes) que ningún código lee ni escribe hoy. El feature real y
vigente vive en `ContratoServicio.tarifa_admin/tarifa_cgm/tarifa_representacion`
(`app/models/contratos.py`), confirmado activo en costos_panel.py y la
API de clientes -- ese no se toca.

Revision ID: 115
Revises: 114
Create Date: 2026-08-27
"""
from alembic import op

from alembic_idempotencia import columna_existe

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None

_COLUMNAS_INVERSIONISTAS = ("contrato_ref", "tarifa_administracion", "tarifa_cgm", "tarifa_representacion")
_COLUMNAS_CLIENTES = ("tarifa_administracion", "tarifa_cgm", "tarifa_representacion")


def upgrade():
    bind = op.get_bind()
    for col in _COLUMNAS_INVERSIONISTAS:
        if columna_existe(bind, "proyecto_inversionistas", col):
            op.execute(f"ALTER TABLE proyecto_inversionistas DROP COLUMN {col}")
    for col in _COLUMNAS_CLIENTES:
        if columna_existe(bind, "clientes", col):
            op.execute(f"ALTER TABLE clientes DROP COLUMN {col}")


def downgrade():
    # Datos huerfanos de un feature dos veces abandonado y sin ningun
    # lector hoy: no hay nada que de verdad valga la pena recrear.
    pass
