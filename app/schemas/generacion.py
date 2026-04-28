from datetime import date, datetime
from pydantic import BaseModel, ConfigDict


class GeneracionDiariaBase(BaseModel):
    fecha: date
    kwh_real: float | None = None
    kwh_p90: float | None = None
    kwh_autoconsumo: float | None = None
    fuente: str = "manual"
    notas: str | None = None


class GeneracionDiariaCreate(GeneracionDiariaBase):
    proyecto_id: int


class GeneracionDiariaUpdate(BaseModel):
    kwh_real: float | None = None
    kwh_p90: float | None = None
    kwh_autoconsumo: float | None = None
    fuente: str | None = None
    notas: str | None = None


class GeneracionDiariaOut(GeneracionDiariaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    proyecto_id: int
    created_at: datetime
    updated_at: datetime


class GeneracionDiariaBulkItem(BaseModel):
    fecha: date
    kwh_real: float | None = None
    kwh_p90: float | None = None
    kwh_autoconsumo: float | None = None
    fuente: str = "manual"
    notas: str | None = None


class GeneracionDiariaBulkUpsert(BaseModel):
    proyecto_id: int
    datos: list[GeneracionDiariaBulkItem]
