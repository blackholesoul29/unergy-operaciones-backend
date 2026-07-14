from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel


class DestinatarioSeleccionado(BaseModel):
    tipo: Literal["operador", "cliente"]
    id: int


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


class EnviarReporteCGMResponse(BaseModel):
    resultados: list[EnvioResultado]
