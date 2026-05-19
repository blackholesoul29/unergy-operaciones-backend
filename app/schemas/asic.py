from pydantic import BaseModel, ConfigDict
from datetime import date, datetime


class AsicSolicitudOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requerimiento_asic: str | None = None
    tipo_solicitud: str
    prioridad_limitacion: int | None = None
    codigo_sic_contrato: str | None = None
    codigo_sic_vendedor: str | None = None
    codigo_sic_comprador: str | None = None
    contrato_interno: str | None = None
    nombre_contacto_solicitante: str | None = None
    fecha_solicitud: date | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    tipo_mercado: str | None = None
    tipo_asignacion: str | None = None
    porcentaje_fncer: float | None = None
    porcentaje_despacho: float | None = None
    estado_solicitud: str
    nombre_interno: str | None = None
    observaciones: str | None = None
    link_archivo: str | None = None
    reemplaza_anterior: bool = True
    es_duplicado: bool = False
    created_at: datetime

    # Nombre de la planta (resuelto en endpoint)
    proyecto_id: int | None = None
    planta_nombre: str | None = None


class AsicSolicitudCreate(BaseModel):
    requerimiento_asic: str | None = None
    tipo_solicitud: str
    prioridad_limitacion: int | None = None
    codigo_sic_contrato: str | None = None
    codigo_sic_vendedor: str | None = None
    codigo_sic_comprador: str | None = None
    contrato_interno: str | None = None
    nombre_contacto_solicitante: str | None = None
    fecha_solicitud: date | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    tipo_mercado: str | None = None
    tipo_asignacion: str | None = None
    porcentaje_fncer: float | None = None
    porcentaje_despacho: float | None = None
    estado_solicitud: str = "en_proceso"
    nombre_interno: str | None = None
    observaciones: str | None = None
    link_archivo: str | None = None
    reemplaza_anterior: bool = True
    es_duplicado: bool = False
    proyecto_id: int | None = None


class AsicSolicitudUpdate(BaseModel):
    requerimiento_asic: str | None = None
    tipo_solicitud: str | None = None
    prioridad_limitacion: int | None = None
    codigo_sic_contrato: str | None = None
    codigo_sic_vendedor: str | None = None
    codigo_sic_comprador: str | None = None
    contrato_interno: str | None = None
    nombre_contacto_solicitante: str | None = None
    fecha_solicitud: date | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    tipo_mercado: str | None = None
    tipo_asignacion: str | None = None
    porcentaje_fncer: float | None = None
    porcentaje_despacho: float | None = None
    estado_solicitud: str | None = None
    nombre_interno: str | None = None
    observaciones: str | None = None
    link_archivo: str | None = None
    reemplaza_anterior: bool | None = None
    es_duplicado: bool | None = None
    proyecto_id: int | None = None


class AsicCambioCreate(BaseModel):
    solicitud_id: int | None = None
    codigo_sic_contrato: str | None = None
    contrato_interno: str | None = None
    proyecto_original_id: int | None = None
    codigo_frt_original: str | None = None
    energia_mensual_mwh_original: float | None = None
    proyecto_nuevo_id: int | None = None
    codigo_frt_nuevo: str | None = None
    energia_mensual_mwh_nuevo: float | None = None
    accion: str | None = None
    nombre_archivo: str | None = None


class AsicCambioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    solicitud_id: int | None = None
    codigo_sic_contrato: str | None = None
    contrato_interno: str | None = None
    proyecto_original_id: int | None = None
    codigo_frt_original: str | None = None
    energia_mensual_mwh_original: float | None = None
    proyecto_nuevo_id: int | None = None
    codigo_frt_nuevo: str | None = None
    energia_mensual_mwh_nuevo: float | None = None
    accion: str | None = None
    nombre_archivo: str | None = None
    created_at: datetime


class GesconDiccionarioCreate(BaseModel):
    codigo_contrato: str
    nombre: str | None = None


class GesconDiccionarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo_contrato: str
    nombre: str | None = None
    created_at: datetime
