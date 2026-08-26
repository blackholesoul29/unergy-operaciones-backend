from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, model_validator

# Tope de tamaño de rango -- sin esto, una request con fecha_inicio/fecha_fin
# muy separadas dispara una llamada paginada a Quoia por CADA frontera
# involucrada, cubriendo todo ese rango (ver fetch_filas_rango en
# reporte_cgm.py), y arma un Excel/correo con esa cantidad de filas -- sin
# guardrail, un rango de meses/años multiplicado por "Operaciones Unergy"
# (~300 fronteras) puede tardar minutos o agotar memoria. 92 días (~3 meses)
# cubre con margen el uso real (un día, o el mes-a-la-fecha en curso) sin
# permitir un rango arbitrariamente grande (auditoría CGM 2026-08-26,
# finding #5).
RANGO_MAXIMO_DIAS = 92


class DestinatarioSeleccionado(BaseModel):
    tipo: Literal["operador", "cliente"]
    id: int
    proyectos: Optional[list[int]] = None  # None = todas las fronteras del destinatario;
    # lista (incluso vacía) = filtrar solo a esos proyecto_id


class EnviarReporteCGMRequest(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    destinatarios: list[DestinatarioSeleccionado]

    @model_validator(mode="after")
    def _validar_rango_de_fechas(self) -> "EnviarReporteCGMRequest":
        dias = abs((self.fecha_fin - self.fecha_inicio).days) + 1
        if dias > RANGO_MAXIMO_DIAS:
            raise ValueError(
                f"El rango de fechas no puede superar {RANGO_MAXIMO_DIAS} días "
                f"(pediste {dias})."
            )
        return self


class EnvioResultado(BaseModel):
    tipo: str
    id: int
    nombre: str
    correos: list[str]
    fronteras: int
    ok: bool
    error: Optional[str] = None
    # Envío completado (ok=True) pero con datos parciales -- ej. Quoia no
    # respondió para algunas fronteras/días por un fallo de red/timeout, no
    # porque de verdad no haya reporte esa fecha (ver fetch_filas() en
    # reporte_cgm.py, estado "Error de conexión con Quoia").
    warning: Optional[str] = None


class EnviarReporteCGMResponse(BaseModel):
    resultados: list[EnvioResultado]
