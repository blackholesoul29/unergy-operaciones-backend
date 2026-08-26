from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel


class DestinatarioSeleccionado(BaseModel):
    tipo: Literal["operador", "cliente"]
    id: int
    proyectos: Optional[list[int]] = None  # None = todas las fronteras del destinatario;
    # lista (incluso vacía) = filtrar solo a esos proyecto_id


class EnviarReporteCGMRequest(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    destinatarios: list[DestinatarioSeleccionado]


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
