from __future__ import annotations
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class ClienteBasico(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    model_config = {"from_attributes": True}


class ProyectoBasico(BaseModel):
    id: int
    nombre_comercial: str
    model_config = {"from_attributes": True}


class ContratoServicioCreate(BaseModel):
    proyecto_id: Optional[int] = None
    servicio_aplica: str  # representacion | operacion | rec
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    indice_indexacion: Optional[str] = None
    canones_otros: Optional[float] = None
    estado: Optional[str] = "vigente"
    # CGM
    tiene_cgm: bool = False
    cgm_codigo_sic: Optional[str] = None
    cgm_porcentaje_fncer: Optional[float] = None
    cgm_tipo_asignacion: Optional[str] = None
    # Promotor
    tiene_promotor: bool = False
    promotor_tarifa: Optional[float] = None
    promotor_condiciones: Optional[str] = None
    # REC
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None


class ContratoServicioUpdate(BaseModel):
    proyecto_id: Optional[int] = None
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    indice_indexacion: Optional[str] = None
    canones_otros: Optional[float] = None
    estado: Optional[str] = None
    tiene_cgm: Optional[bool] = None
    cgm_codigo_sic: Optional[str] = None
    cgm_porcentaje_fncer: Optional[float] = None
    cgm_tipo_asignacion: Optional[str] = None
    tiene_promotor: Optional[bool] = None
    promotor_tarifa: Optional[float] = None
    promotor_condiciones: Optional[str] = None
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None


class ContratoServicioOut(BaseModel):
    id: int
    proyecto_id: Optional[int] = None
    servicio_aplica: str
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    contratante: Optional[ClienteBasico] = None
    prestador: Optional[ClienteBasico] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    indice_indexacion: Optional[str] = None
    canones_otros: Optional[float] = None
    estado: str
    tiene_cgm: bool = False
    cgm_codigo_sic: Optional[str] = None
    cgm_porcentaje_fncer: Optional[float] = None
    cgm_tipo_asignacion: Optional[str] = None
    tiene_promotor: bool = False
    promotor_tarifa: Optional[float] = None
    promotor_condiciones: Optional[str] = None
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
