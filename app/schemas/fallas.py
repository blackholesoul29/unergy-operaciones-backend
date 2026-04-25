from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime, date, time


class FallaCatEstadoOut(BaseModel):
    id: int
    codigo: str
    etiqueta: str
    color_hex: Optional[str]
    orden: int
    es_estado_final: bool
    model_config = {"from_attributes": True}


class FallaCatPrioridadOut(BaseModel):
    id: int
    codigo: str
    etiqueta: str
    color_hex: Optional[str]
    nivel: int
    model_config = {"from_attributes": True}


class FallaCatCategoriaOut(BaseModel):
    id: int
    codigo: str
    etiqueta: str
    icono: Optional[str]
    color_hex: Optional[str]
    orden: int
    model_config = {"from_attributes": True}


class FallaCatTipoOut(BaseModel):
    id: int
    codigo: str
    etiqueta: str
    descripcion: Optional[str]
    categoria: FallaCatCategoriaOut
    model_config = {"from_attributes": True}


class FallaCatResolucionOut(BaseModel):
    id: int
    codigo: str
    etiqueta: str
    model_config = {"from_attributes": True}


class UsuarioResumen(BaseModel):
    id: int
    nombre: str
    email: str
    model_config = {"from_attributes": True}


class ProyectoResumen(BaseModel):
    id: int
    nombre_comercial: str
    model_config = {"from_attributes": True}


class FallaCreate(BaseModel):
    proyecto_id: int
    tipo_id: int
    estado_id: int
    prioridad_id: int
    resolucion_id: Optional[int] = None
    asignado_a_id: Optional[int] = None
    descripcion: str
    fecha_identificacion: date
    hora_identificacion: Optional[time] = None
    fecha_ocurrencia: Optional[datetime] = None
    fecha_resolucion: Optional[datetime] = None
    sla_limite_horas: Optional[int] = None
    codigo_legado: Optional[str] = None


class FallaUpdate(BaseModel):
    tipo_id: Optional[int] = None
    estado_id: Optional[int] = None
    prioridad_id: Optional[int] = None
    resolucion_id: Optional[int] = None
    asignado_a_id: Optional[int] = None
    descripcion: Optional[str] = None
    fecha_identificacion: Optional[date] = None
    hora_identificacion: Optional[time] = None
    fecha_ocurrencia: Optional[datetime] = None
    fecha_resolucion: Optional[datetime] = None
    sla_limite_horas: Optional[int] = None
    sla_cumplido: Optional[bool] = None


class FallaSeguimientoCreate(BaseModel):
    nota: Optional[str] = None
    estado_nuevo_id: Optional[int] = None


class FallaSeguimientoOut(BaseModel):
    id: int
    falla_id: int
    nota: Optional[str]
    estado_nuevo: Optional[FallaCatEstadoOut]
    usuario: UsuarioResumen
    created_at: datetime
    model_config = {"from_attributes": True}


class FallaOut(BaseModel):
    id: int
    codigo_interno: str
    codigo_legado: Optional[str]
    proyecto_id: int
    proyecto: ProyectoResumen
    tipo: FallaCatTipoOut
    estado: FallaCatEstadoOut
    prioridad: FallaCatPrioridadOut
    resolucion: Optional[FallaCatResolucionOut]
    registrado_por: UsuarioResumen
    asignado_a: Optional[UsuarioResumen]
    descripcion: str
    fecha_identificacion: date
    hora_identificacion: Optional[time]
    fecha_ocurrencia: Optional[datetime]
    fecha_resolucion: Optional[datetime]
    sla_limite_horas: Optional[int]
    sla_cumplido: Optional[bool]
    tiene_fotos: bool = False
    dias_abierta: Optional[int] = None
    sla_limite_dias: Optional[int] = None
    seguimientos: list[FallaSeguimientoOut] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("seguimientos", mode="before")
    @classmethod
    def none_to_list(cls, v):
        return v if v is not None else []


class FallaCatalogos(BaseModel):
    estados: list[FallaCatEstadoOut]
    prioridades: list[FallaCatPrioridadOut]
    tipos: list[FallaCatTipoOut]
    resoluciones: list[FallaCatResolucionOut]
