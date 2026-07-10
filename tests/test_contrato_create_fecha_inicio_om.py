"""ContratoServicioCreate debe aceptar y propagar fecha_inicio_om (usado por om_calculator)."""
from datetime import date
from app.schemas.contratos_servicio import ContratoServicioCreate
from app.models.contratos import ContratoServicio


def test_create_incluye_fecha_inicio_om():
    dto = ContratoServicioCreate(
        servicio_aplica="mantenimiento",
        proyecto_id=1,
        tarifa_base=1_000_000,
        fecha_firma_contrato=date(2025, 1, 1),
        fecha_inicio_om=date(2025, 3, 1),
    )
    dump = dto.model_dump()
    assert "fecha_inicio_om" in dump
    assert dump["fecha_inicio_om"] == date(2025, 3, 1)
    # El dump debe poder construir el modelo sin campos desconocidos
    contrato = ContratoServicio(**dump)
    assert contrato.fecha_inicio_om == date(2025, 3, 1)
