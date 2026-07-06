"""Paridad front↔back de los campos de detalle del contrato de servicio.

El frontend (commit d68b586, live en master) captura y POSTea cuatro campos de
detalle operacional/contractual. Antes de la migración 036 el backend no tenía
esas columnas y Pydantic los descartaba en silencio → data-loss con toast de
éxito. Este test bloquea la regresión: si un refactor futuro tira uno de los
campos del modelo ORM o de cualquiera de los tres schemas de I/O, el data-loss
vuelve parcialmente sin que nadie lo note. Es un guard de contrato, sin DB.
"""
from app.models.contratos import ContratoServicio
from app.schemas.contratos_servicio import (
    ContratoServicioCreate,
    ContratoServicioOut,
    ContratoServicioUpdate,
)

# Los cuatro nombres deben coincidir CARÁCTER POR CARÁCTER con el payload del
# wizard del frontend (ContratoServicioWizard.vue) — cualquier divergencia
# reintroduce el data-loss silencioso.
DETAIL_FIELDS = ("service_scope", "specific_service_terms", "slas", "responsibilities")


def test_model_tiene_los_campos_de_detalle():
    columnas = set(ContratoServicio.__table__.columns.keys())
    faltantes = [f for f in DETAIL_FIELDS if f not in columnas]
    assert not faltantes, f"columnas ausentes en el modelo ORM: {faltantes}"


def test_schemas_de_escritura_y_lectura_cubren_los_campos():
    # Create y Update deben aceptar los campos (entrada); Out debe exponerlos
    # (salida, para que el detalle del frontend los lea de vuelta).
    for schema in (ContratoServicioCreate, ContratoServicioUpdate, ContratoServicioOut):
        campos = set(schema.model_fields.keys())
        faltantes = [f for f in DETAIL_FIELDS if f not in campos]
        assert not faltantes, f"campos ausentes en {schema.__name__}: {faltantes}"
