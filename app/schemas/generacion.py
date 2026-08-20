from pydantic import BaseModel, model_validator
from typing import Optional
from datetime import datetime, date
from decimal import Decimal


class GeneracionDiariaCreate(BaseModel):
    proyecto_id: int
    fecha: date
    kwh_real: Optional[Decimal] = None
    kwh_p90: Optional[Decimal] = None
    kwh_autoconsumo: Optional[Decimal] = None
    fuente: str = "manual"
    notas: Optional[str] = None


class GeneracionDiariaUpdate(BaseModel):
    kwh_real: Optional[Decimal] = None
    kwh_p90: Optional[Decimal] = None
    kwh_autoconsumo: Optional[Decimal] = None
    fuente: Optional[str] = None
    notas: Optional[str] = None


class ProyectoResumenGen(BaseModel):
    id: int
    nombre_comercial: str
    model_config = {"from_attributes": True}


class GeneracionDiariaOut(BaseModel):
    id: int
    proyecto_id: int
    proyecto: ProyectoResumenGen
    fecha: date
    kwh_real: Optional[Decimal]
    kwh_p90: Optional[Decimal]
    kwh_autoconsumo: Optional[Decimal]
    fuente: str
    notas: Optional[str]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class GeneracionDiariaBulkItem(BaseModel):
    """Un registro dentro del bulk. Si proyecto_nombre_externo no coincide
    se intenta matching fuzzy con nombre_comercial."""
    proyecto_id: Optional[int] = None
    proyecto_nombre_externo: Optional[str] = None  # fallback fuzzy
    fecha: date
    kwh_real: Optional[Decimal] = None
    kwh_p90: Optional[Decimal] = None
    kwh_autoconsumo: Optional[Decimal] = None
    fuente: str = "sheets"
    notas: Optional[str] = None

    @model_validator(mode="after")
    def validar_proyecto(self) -> "GeneracionDiariaBulkItem":
        if not self.proyecto_id and not self.proyecto_nombre_externo:
            raise ValueError("Se requiere proyecto_id o proyecto_nombre_externo")
        return self


class GeneracionDiariaBulkCreate(BaseModel):
    items: list[GeneracionDiariaBulkItem]
    overwrite: bool = False  # si True, hace upsert; si False, skip duplicados


class GeneracionDiariaBulkResult(BaseModel):
    insertados: int
    actualizados: int
    omitidos: int
    errores: list[str] = []


class GeneracionResumenProyecto(BaseModel):
    proyecto_id: int
    nombre_comercial: str
    total_kwh_real: Optional[Decimal]
    total_kwh_p90: Optional[Decimal]
    dias_con_dato: int
    fecha_inicio: Optional[date]
    fecha_fin: Optional[date]
