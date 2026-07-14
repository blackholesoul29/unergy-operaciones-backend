from pydantic import BaseModel
from datetime import date, datetime
from typing import Literal

# Con qué precio se valora el déficit de cumplimiento del contrato.
# HIBRIDO: el mayor entre penalidad y bolsa. Ver app/services/cumplimiento_service.py.
TipoPrecioReferencia = Literal["HIBRIDO", "PENALIDAD_CONTRACTUAL", "PRECIO_BOLSA"]


class ProyectoBasico(BaseModel):
    id: int
    nombre_comercial: str
    model_config = {"from_attributes": True}


class ClienteBasico(BaseModel):
    id: int
    razon_social_nombre: str
    nit_cedula: str | None = None
    model_config = {"from_attributes": True}


class PPATarifaIn(BaseModel):
    año: int
    mes: int
    tarifa: float | None = None


class PPATarifaOut(PPATarifaIn):
    id: int
    contrato_id: int
    model_config = {"from_attributes": True}


class PPACompromisoIn(BaseModel):
    año: int
    mes: int
    energia_minima: float | None = None
    energia_maxima: float | None = None
    cantidad_proyectos: int | None = None


class PPACompromisoOut(PPACompromisoIn):
    id: int
    contrato_id: int
    model_config = {"from_attributes": True}


class PPAContratoCreate(BaseModel):
    proyecto_ids: list[int] = []
    comprador_id: int | None = None
    vendedor_id: int | None = None
    numero_codigo_contrato: str | None = None
    nombre_interno: str | None = None
    comprador_nombre: str | None = None
    comprador_nit: str | None = None
    vendedor_nombre: str | None = None
    vendedor_nit: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    tarifa_base: float | None = None
    indice_indexacion: str | None = None
    periodicidad_indexacion: str | None = None
    periodo_indexacion_base: str | None = None
    valor_indexacion_base: float | None = None
    cantidad_minima_kwh_mes: float | None = None
    cantidad_maxima_kwh_mes: float | None = None
    periodicidad_facturacion: str | None = None
    tiempo_pago: int | None = None
    condiciones_pago: str | None = None
    codigo_sic: str | None = None
    gescon_codigo: str | None = None
    gescon_fecha_inicio: date | None = None
    gescon_fecha_fin: date | None = None
    gescon_precio: float | None = None
    gescon_cantidades_kwh: float | None = None
    precio_penalidad_mwh: float | None = None  # COP/MWh
    tipo_precio_referencia: TipoPrecioReferencia = "HIBRIDO"
    tipo_contrato: str | None = "venta"
    carpeta_link: str | None = None
    renovacion_automatica: bool | None = None


class PPAContratoUpdate(BaseModel):
    proyecto_ids: list[int] | None = None
    comprador_id: int | None = None
    vendedor_id: int | None = None
    numero_codigo_contrato: str | None = None
    nombre_interno: str | None = None
    comprador_nombre: str | None = None
    comprador_nit: str | None = None
    vendedor_nombre: str | None = None
    vendedor_nit: str | None = None
    fecha_inicio: date | None = None
    fecha_fin: date | None = None
    tarifa_base: float | None = None
    indice_indexacion: str | None = None
    periodicidad_indexacion: str | None = None
    periodo_indexacion_base: str | None = None
    valor_indexacion_base: float | None = None
    cantidad_minima_kwh_mes: float | None = None
    cantidad_maxima_kwh_mes: float | None = None
    periodicidad_facturacion: str | None = None
    tiempo_pago: int | None = None
    condiciones_pago: str | None = None
    codigo_sic: str | None = None
    gescon_codigo: str | None = None
    gescon_fecha_inicio: date | None = None
    gescon_fecha_fin: date | None = None
    gescon_precio: float | None = None
    gescon_cantidades_kwh: float | None = None
    precio_penalidad_mwh: float | None = None  # COP/MWh
    # None = no se toca (la columna es NOT NULL; el endpoint ignora el null explícito).
    tipo_precio_referencia: TipoPrecioReferencia | None = None
    tipo_contrato: str | None = None
    carpeta_link: str | None = None
    renovacion_automatica: bool | None = None


class PPAContratoOut(BaseModel):
    id: int
    proyectos: list[ProyectoBasico] = []
    comprador_id: int | None = None
    vendedor_id: int | None = None
    comprador: ClienteBasico | None = None
    vendedor: ClienteBasico | None = None
    numero_codigo_contrato: str | None
    nombre_interno: str | None
    comprador_nombre: str | None
    comprador_nit: str | None
    vendedor_nombre: str | None
    vendedor_nit: str | None
    fecha_inicio: date | None
    fecha_fin: date | None
    tarifa_base: float | None
    indice_indexacion: str | None
    periodicidad_indexacion: str | None
    periodo_indexacion_base: str | None
    valor_indexacion_base: float | None
    cantidad_minima_kwh_mes: float | None
    cantidad_maxima_kwh_mes: float | None
    periodicidad_facturacion: str | None
    tiempo_pago: int | None
    condiciones_pago: str | None
    codigo_sic: str | None
    gescon_codigo: str | None
    gescon_fecha_inicio: date | None
    gescon_fecha_fin: date | None
    gescon_precio: float | None
    gescon_cantidades_kwh: float | None
    precio_penalidad_mwh: float | None = None  # COP/MWh
    tipo_precio_referencia: str | None = None
    tipo_contrato: str | None = None
    carpeta_link: str | None = None
    renovacion_automatica: bool | None = None
    tarifas: list[PPATarifaOut] = []
    compromisos_energia: list[PPACompromisoOut] = []
    # Computed visibility fields (populated by endpoint, not ORM)
    estado_cumplimiento: str | None = None  # on_track / at_risk / deficit
    dias_restantes: int | None = None
    cobertura_actual_pct: float | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
