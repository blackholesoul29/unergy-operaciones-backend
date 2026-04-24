from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date


class ProyectoInversionistaCreate(BaseModel):
    cliente_id: int
    porcentaje_participacion: Optional[float] = None
    es_patrimonio_autonomo: bool = False
    contrato_ref: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None


class ProyectoInversionistaOut(ProyectoInversionistaCreate):
    id: int
    proyecto_id: int
    cliente_nombre: str = ""
    created_at: datetime
    model_config = {"from_attributes": True}


class ProyectoCreate(BaseModel):
    nombre_comercial: str
    cliente_id: int
    portafolio_id: Optional[int] = None
    proyecto_padre_id: Optional[int] = None
    nombre_bitacora: Optional[str] = None
    nombre_clientes: Optional[str] = None
    topic_slug: Optional[str] = None
    clasificacion_regulatoria: Optional[str] = None
    tipo_tecnologia: Optional[str] = None
    tipo_proyecto: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    cantidad_total_paneles: Optional[int] = None
    produccion_especifica_kwh_kwp: Optional[float] = None
    estado: Optional[str] = "en_desarrollo"
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    operador_red: Optional[str] = None
    carpeta_drive_codigo: Optional[str] = None


class ProyectoUpdate(ProyectoCreate):
    nombre_comercial: Optional[str] = None
    cliente_id: Optional[int] = None


class ProyectoOut(BaseModel):
    id: int
    nombre_comercial: str
    cliente_id: int
    portafolio_id: Optional[int]
    proyecto_padre_id: Optional[int]
    nombre_bitacora: Optional[str]
    nombre_clientes: Optional[str]
    topic_slug: Optional[str]
    clasificacion_regulatoria: Optional[str]
    tipo_tecnologia: Optional[str]
    tipo_proyecto: Optional[str]
    potencia_instalada_kwp: Optional[float]
    cantidad_total_paneles: Optional[int]
    produccion_especifica_kwh_kwp: Optional[float]
    estado: str
    departamento: Optional[str]
    municipio: Optional[str]
    operador_red: Optional[str]
    carpeta_drive_codigo: Optional[str]
    srv_operacion: bool
    srv_representacion: bool
    srv_cgm: bool
    srv_ppa: bool
    srv_promotor: bool
    srv_rec: bool
    inversionistas: list[ProyectoInversionistaOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("inversionistas", mode="before")
    @classmethod
    def none_to_list(cls, v):
        return v if v is not None else []
