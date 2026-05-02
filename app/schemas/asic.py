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
    observaciones: str | None = None
    link_archivo: str | None = None
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
    observaciones: str | None = None
    link_archivo: str | None = None
    proyecto_id: int | None = None
