from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
