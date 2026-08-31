from __future__ import annotations
from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List, Any


# ── Indexación O&M ────────────────────────────────────────────────────────────

class FilaIndexacion(BaseModel):
    anio: int
    ipc_aplicado: Optional[float] = None   # None = año base
    valor: float
    es_base: Optional[bool] = None


class FilaIndexacionCGM(BaseModel):
    año: int
    ipc: Optional[float] = None
    valor: float
    esBase: Optional[bool] = None


class ContratoFacturaCreate(BaseModel):
    tipo: str                             # 'solenium' | 'inversionista'
    fecha: str                            # formato YYYY-MM
    inversionista: Optional[str] = None
    numero_factura: Optional[str] = None
    monto: Optional[float] = None
    enlace_soporte: Optional[str] = None


class ContratoFacturaUpdate(BaseModel):
    fecha: Optional[str] = None
    inversionista: Optional[str] = None
    numero_factura: Optional[str] = None
    monto: Optional[float] = None
    enlace_soporte: Optional[str] = None


class ContratoFacturaOut(BaseModel):
    id: int
    contrato_id: int
    tipo: str
    fecha: str
    inversionista: Optional[str] = None
    numero_factura: Optional[str] = None
    monto: Optional[float] = None
    enlace_soporte: Optional[str] = None
    model_config = {"from_attributes": True}


class ImportarIndexacionEntry(BaseModel):
    proyecto: str
    filas: List[FilaIndexacion]


# ─────────────────────────────────────────────────────────────────────────────

class ClienteBasico(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: Optional[str] = None
    model_config = {"from_attributes": True}


class ProyectoBasico(BaseModel):
    id: int
    nombre_comercial: str
    # `tipo_proyecto` viaja acá para que el listado de contratos pueda decir a
    # qué clase de planta pertenece cada uno (minigranja / autoconsumo / gd)
    # sin tener que cargar además todo /proyectos.
    tipo_proyecto: Optional[str] = None
    codigo_tsf: Optional[str] = None
    model_config = {"from_attributes": True}


class FronteraBasico(BaseModel):
    """Puntos de medida especificos que cubre un contrato -- distinto de
    ProyectoBasico, que solo dice a que planta pertenece el contrato."""
    id: int
    codigo_frontera: Optional[str] = None
    nombre_frontera: str
    tipo_frontera: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    model_config = {"from_attributes": True}


class ContratoServicioCreate(BaseModel):
    proyecto_id: Optional[int] = None
    servicio_aplica: str  # representacion | mantenimiento | arriendo | internet | rec
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    # El inversionista como relacion; `inversionista_nombre` queda como el texto
    # que trajo el acta. Ver services/representacion_inversionista.py.
    inversionista_id: Optional[int] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_inicio_om: Optional[date] = None   # Fecha de inicio O&M (base de indexación)
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    tarifa_mensual: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    responsable_iva: Optional[bool] = None
    indice_indexacion: Optional[str] = None
    estado: Optional[str] = "vigente"
    fecha_firma_contrato: Optional[date] = None
    renovacion_automatica: Optional[bool] = None
    fecha_indexacion: Optional[date] = None
    enlace_drive: Optional[str] = None
    estado_pago: Optional[str] = None
    plan_datos_gb: Optional[str] = None
    velocidad_mbps: Optional[int] = None
    tipo_conexion: Optional[str] = None
    linea_servicio: Optional[str] = None
    id_router: Optional[str] = None
    numero_kit: Optional[str] = None
    latencia_ms: Optional[int] = None
    wifi_seguridad: Optional[str] = None
    wifi_password: Optional[str] = None
    ubicacion_lat: Optional[float] = None
    ubicacion_lng: Optional[float] = None
    # CGM
    tiene_cgm: bool = False
    cgm_codigo_sic: Optional[str] = None
    # REC
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None
    # CGM / Representación
    inversionista_nombre: Optional[str] = None
    portafolio: Optional[str] = None
    codigo_sun_factory: Optional[str] = None
    tarifa_admin: Optional[float] = None
    tarifa_cgm: Optional[float] = None
    tarifa_representacion: Optional[float] = None
    indexacion_cgm: Optional[List[FilaIndexacionCGM]] = None
    indexacion_representacion: Optional[List[FilaIndexacionCGM]] = None
    # Puntos de medida especificos que cubre el contrato (opcional).
    frontera_ids: List[int] = []


class ContratoServicioUpdate(BaseModel):
    proyecto_id: Optional[int] = None
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    inversionista_id: Optional[int] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_inicio_om: Optional[date] = None   # Fecha de inicio O&M (base de indexación)
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    responsable_iva: Optional[bool] = None
    indice_indexacion: Optional[str] = None
    estado: Optional[str] = None
    fecha_firma_contrato: Optional[date] = None
    renovacion_automatica: Optional[bool] = None
    fecha_indexacion: Optional[date] = None
    enlace_drive: Optional[str] = None
    estado_pago: Optional[str] = None
    plan_datos_gb: Optional[str] = None
    velocidad_mbps: Optional[int] = None
    tipo_conexion: Optional[str] = None
    linea_servicio: Optional[str] = None
    id_router: Optional[str] = None
    numero_kit: Optional[str] = None
    latencia_ms: Optional[int] = None
    wifi_seguridad: Optional[str] = None
    wifi_password: Optional[str] = None
    ubicacion_lat: Optional[float] = None
    ubicacion_lng: Optional[float] = None
    tiene_cgm: Optional[bool] = None
    cgm_codigo_sic: Optional[str] = None
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None
    indexacion_anual: Optional[List[FilaIndexacion]] = None
    indexacion_mensual: Optional[List[FilaIndexacion]] = None
    # CGM / Representación
    inversionista_nombre: Optional[str] = None
    portafolio: Optional[str] = None
    codigo_sun_factory: Optional[str] = None
    tarifa_admin: Optional[float] = None
    tarifa_cgm: Optional[float] = None
    tarifa_representacion: Optional[float] = None
    indexacion_cgm: Optional[List[FilaIndexacionCGM]] = None
    indexacion_representacion: Optional[List[FilaIndexacionCGM]] = None
    # None = no tocar los vinculos actuales; [] = desvincular todas.
    frontera_ids: Optional[List[int]] = None


class ContratoServicioOut(BaseModel):
    id: int
    proyecto_id: Optional[int] = None
    # La planta a la que pertenece el contrato. `proyecto_id` sola no le sirve a
    # ninguna tabla: obliga a cruzar contra /proyectos en el cliente. Va anidada
    # y NULL cuando el contrato quedó huérfano, que es justo el caso a corregir.
    proyecto: Optional[ProyectoBasico] = None
    servicio_aplica: str
    contratante_id: Optional[int] = None
    prestador_id: Optional[int] = None
    contratante: Optional[ClienteBasico] = None
    prestador: Optional[ClienteBasico] = None
    inversionista_id: Optional[int] = None
    # Cuando viene NULL el contrato aun no esta vinculado a un inversionista de
    # la planta, y por eso no se puede saber si su participacion sigue vigente.
    inversionista: Optional[ClienteBasico] = None
    contratante_nombre: Optional[str] = None
    contratante_nit: Optional[str] = None
    prestador_nombre: Optional[str] = None
    prestador_nit: Optional[str] = None
    numero_contrato: Optional[str] = None
    fecha_inicio: Optional[date] = None
    fecha_inicio_om: Optional[date] = None   # Fecha de inicio O&M (base de indexación)
    fecha_fin: Optional[date] = None
    tarifa_base: Optional[float] = None
    tarifa_mensual: Optional[float] = None
    periodicidad_pago: Optional[str] = None
    responsable_iva: Optional[bool] = None
    indice_indexacion: Optional[str] = None
    estado: str
    fecha_firma_contrato: Optional[date] = None
    renovacion_automatica: Optional[bool] = None
    fecha_indexacion: Optional[date] = None
    enlace_drive: Optional[str] = None
    estado_pago: Optional[str] = None
    plan_datos_gb: Optional[str] = None
    velocidad_mbps: Optional[int] = None
    tipo_conexion: Optional[str] = None
    linea_servicio: Optional[str] = None
    id_router: Optional[str] = None
    numero_kit: Optional[str] = None
    latencia_ms: Optional[int] = None
    wifi_seguridad: Optional[str] = None
    wifi_password: Optional[str] = None
    ubicacion_lat: Optional[float] = None
    ubicacion_lng: Optional[float] = None
    tiene_cgm: bool = False
    cgm_codigo_sic: Optional[str] = None
    rec_cantidad: Optional[float] = None
    rec_precio_unitario: Optional[float] = None
    rec_vintage: Optional[str] = None
    indexacion_anual: Optional[List[FilaIndexacion]] = None
    indexacion_mensual: Optional[List[FilaIndexacion]] = None
    facturas_solenium: Optional[List[FilaFactura]] = None
    facturas_inversionistas: Optional[List[FilaFactura]] = None
    # CGM / Representación
    inversionista_nombre: Optional[str] = None
    portafolio: Optional[str] = None
    codigo_sun_factory: Optional[str] = None
    nombre_proyecto_ref: Optional[str] = None
    tarifa_admin: Optional[float] = None
    tarifa_cgm: Optional[float] = None
    tarifa_representacion: Optional[float] = None
    indexacion_cgm: Optional[List[Any]] = None
    indexacion_representacion: Optional[List[Any]] = None
    fronteras: List[FronteraBasico] = []
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class PagoServicioCreate(BaseModel):
    mes: int
    año: int
    valor_pagado: Optional[float] = None
    estado: str = "pendiente"
    enlace_factura: Optional[str] = None


class PagoServicioUpdate(BaseModel):
    mes: Optional[int] = None
    año: Optional[int] = None
    valor_pagado: Optional[float] = None
    estado: Optional[str] = None
    enlace_factura: Optional[str] = None


class PagoServicioOut(BaseModel):
    id: int
    contrato_id: int
    mes: int
    año: int
    valor_pagado: Optional[float] = None
    estado: str
    enlace_factura: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
