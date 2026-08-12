# unergy-operaciones-backend/app/schemas/polizas.py
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class PolizaUpsert(BaseModel):
    numero_poliza: Optional[str] = None
    poliza_om: bool = False
    fecha_vencimiento: Optional[date] = None
    valor_poliza: Optional[float] = None

    mano_obra: Optional[float] = None
    estructura: Optional[float] = None
    paneles: Optional[float] = None
    inversores: Optional[float] = None
    otros: Optional[float] = None
    link_estudio_suelos: Optional[str] = None

    ipp_base: Optional[float] = None
    ipp_base_fecha: Optional[date] = None
    ipp_provisional: Optional[float] = None
    ipp_provisional_fecha: Optional[date] = None
    tarifa_base: Optional[float] = None
    generacion_anual_p90_kwh: Optional[float] = None


class PolizaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    proyecto_id: int
    nombre_comercial: str
    tipo_proyecto: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    direccion_vereda: Optional[str] = None

    marca_paneles: Optional[str] = None
    cantidad_total_paneles: Optional[int] = None
    marca_inversores: Optional[str] = None
    cantidad_inversores: Optional[int] = None
    capacidad_instalada_kwp: Optional[float] = None

    numero_poliza: Optional[str] = None
    poliza_om: bool = False
    fecha_vencimiento: Optional[date] = None
    valor_poliza: Optional[float] = None

    mano_obra: Optional[float] = None
    estructura: Optional[float] = None
    paneles: Optional[float] = None
    inversores: Optional[float] = None
    otros: Optional[float] = None
    valor_total_proyecto: Optional[float] = None
    link_estudio_suelos: Optional[str] = None

    ipp_base: Optional[float] = None
    ipp_base_fecha: Optional[date] = None
    ipp_provisional: Optional[float] = None
    ipp_provisional_fecha: Optional[date] = None
    tarifa_base: Optional[float] = None
    generacion_anual_p90_kwh: Optional[float] = None
    valor_lucro_cesante: Optional[float] = None

    updated_at: Optional[datetime] = None
