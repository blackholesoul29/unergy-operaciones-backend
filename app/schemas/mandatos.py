from datetime import date
from pydantic import BaseModel, Field


class MandatoCrear(BaseModel):
    cmu: str = Field(..., max_length=20)
    periodo: date                      # primer día del mes
    proyecto: str | None = None
    tercero: str | None = None
    inversionista_id: int | None = None
    estado: str = "pendiente_envio"
    observacion: str | None = None


class MandatoActualizar(BaseModel):
    proyecto: str | None = None
    tercero: str | None = None
    inversionista_id: int | None = None
    estado: str | None = None
    observacion: str | None = None
    fecha_envio_revisoria: date | None = None
    fecha_firmado: date | None = None
    fecha_envio_inversionista: date | None = None


class InversionistaOut(BaseModel):
    id: int
    nombre: str
    activo: bool

    model_config = {"from_attributes": True}
