"""fronteras: CHECK constraints en campos numericos (rangos geo + no
negativos + factor_perdidas)

Sara, 2026-08-25 -- diagnostico de integridad de Fronteras. Ningun campo
numerico de `fronteras` tenia proteccion contra typos de digitacion
(ej. latitud=950 en vez de 9.50, capacidad_efectiva_mw negativa).
Rangos verificados contra los valores reales en produccion antes de
agregarlos (145 fronteras, 2026-08-25) para no romper datos existentes:
latitud 1.6 a 10.9, longitud -77.3 a -72.5, capacidades 0.5 a 3.0,
factor_perdidas 1.0 a 1.05 (es un multiplicador, no una fraccion 0-1 --
energia_real = energia_medida x factor_perdidas), y los otros 4
factor_* siempre en 0.0 (solo se protege contra negativos, sin
evidencia de un rango superior real). Se replica el mismo rango en
Pydantic (app/schemas/fronteras.py) para un 422 claro antes de llegar a
la BD -- el CHECK queda como respaldo si algun dato entra por otro
camino (script, import directo).

Revision ID: 084
Revises: 083
Create Date: 2026-08-25
"""
from alembic import op

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None

_CONSTRAINTS = [
    ("ck_fronteras_latitud_rango", "latitud IS NULL OR (latitud >= -90 AND latitud <= 90)"),
    ("ck_fronteras_longitud_rango", "longitud IS NULL OR (longitud >= -180 AND longitud <= 180)"),
    ("ck_fronteras_capacidad_efectiva_mw_no_negativa", "capacidad_efectiva_mw IS NULL OR capacidad_efectiva_mw >= 0"),
    ("ck_fronteras_capacidad_transporte_mw_no_negativa", "capacidad_transporte_mw IS NULL OR capacidad_transporte_mw >= 0"),
    ("ck_fronteras_potencia_maxima_declarada_no_negativa", "potencia_maxima_declarada IS NULL OR potencia_maxima_declarada >= 0"),
    ("ck_fronteras_transferencia_maxima_kwh_no_negativa", "transferencia_maxima_kwh IS NULL OR transferencia_maxima_kwh >= 0"),
    ("ck_fronteras_factor_perdidas_rango", "factor_perdidas IS NULL OR (factor_perdidas > 0 AND factor_perdidas <= 2)"),
    ("ck_fronteras_factor_psf_no_negativo", "factor_psf IS NULL OR factor_psf >= 0"),
    ("ck_fronteras_factor_acordado_no_negativo", "factor_acordado IS NULL OR factor_acordado >= 0"),
    ("ck_fronteras_factor_ajuste_no_negativo", "factor_ajuste IS NULL OR factor_ajuste >= 0"),
    ("ck_fronteras_factor_perdidas_frontera_principal_no_negativo", "factor_perdidas_frontera_principal IS NULL OR factor_perdidas_frontera_principal >= 0"),
]


def upgrade():
    for nombre, condicion in _CONSTRAINTS:
        op.create_check_constraint(nombre, "fronteras", condicion)


def downgrade():
    for nombre, _ in _CONSTRAINTS:
        op.drop_constraint(nombre, "fronteras", type_="check")
