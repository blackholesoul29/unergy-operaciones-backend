from pydantic import BaseModel, ConfigDict, Field
from datetime import date, datetime
from typing import Optional

from app.models.fronteras import TipoFronteraEnum, EstadoFronteraEnum


class FronteraBase(BaseModel):
    proyecto_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    nombre_frontera: str
    tipo_frontera: TipoFronteraEnum
    estado: Optional[EstadoFronteraEnum] = EstadoFronteraEnum.activa
    quoia_border_id: Optional[int] = None
    fecha_registro_asic: Optional[date] = None

    # Registro ASIC
    registrada_por: Optional[str] = None
    nivel_tension: Optional[int] = None
    nivel_tension_kv: Optional[float] = None
    transferencia_maxima_kwh: Optional[float] = Field(default=None, ge=0)
    representante_frontera: Optional[str] = None
    fecha_inicio_representacion: Optional[date] = None
    operador_red_id: Optional[int] = None

    # Técnico
    tipo_punto_medicion: Optional[int] = None
    factor_perdidas: Optional[float] = Field(default=None, gt=0, le=2)
    clase_ct: Optional[str] = None
    clase_pt: Optional[str] = None

    # Agentes
    representante_anterior: Optional[str] = None
    agente_exportador: Optional[str] = None
    agente_importador: Optional[str] = None
    nombre_recurso_generacion: Optional[str] = None
    clasificacion_recurso: Optional[str] = None

    # Ubicación
    centro_poblado: Optional[str] = None

    # Códigos SIC
    codigo_sic_submercado_exportador: Optional[str] = None
    codigo_sic_submercado_consumo: Optional[str] = None
    codigo_sic_frontera_generacion: Optional[str] = None
    codigo_sic_frontera_usuario: Optional[str] = None
    potencia_maxima_declarada: Optional[float] = Field(default=None, ge=0)

    # Medidor principal
    nro_serie_med_ppal: Optional[str] = None
    marca_med_ppal: Optional[str] = None
    modelo_med_ppal: Optional[str] = None
    clase_medidor: Optional[str] = None
    num_elementos_med_ppal: Optional[int] = None
    fecha_cambio_med_ppal: Optional[date] = None
    entidad_calibradora_med_ppal: Optional[str] = None
    fecha_calibracion_med_ppal: Optional[date] = None
    fecha_actualizacion_ppal: Optional[date] = None

    # Medidor respaldo
    nro_serie_med_resp: Optional[str] = None
    marca_med_resp: Optional[str] = None
    modelo_med_resp: Optional[str] = None
    num_elementos_med_resp: Optional[int] = None
    fecha_cambio_med_resp: Optional[date] = None
    entidad_calibradora_med_resp: Optional[str] = None
    fecha_calibracion_med_resp: Optional[date] = None
    fecha_actualizacion_resp: Optional[date] = None

    # Agrupación/embebido
    es_agrupadora: Optional[bool] = False
    factor_psf: Optional[float] = Field(default=None, ge=0)
    es_principal_embebido: Optional[bool] = False
    factor_acordado: Optional[float] = Field(default=None, ge=0)
    factor_ajuste: Optional[float] = Field(default=None, ge=0)
    factor_perdidas_frontera_principal: Optional[float] = Field(default=None, ge=0)

    # Clasificación industrial
    codigo_ciiu: Optional[str] = None
    clasificacion_industrial_general: Optional[str] = None
    clasificacion_industrial_especifica: Optional[str] = None


class FronteraCreate(FronteraBase):
    pass


class FronteraUpdate(BaseModel):
    """All fields optional for PATCH updates."""
    proyecto_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    nombre_frontera: Optional[str] = None
    tipo_frontera: Optional[TipoFronteraEnum] = None
    estado: Optional[EstadoFronteraEnum] = None
    quoia_border_id: Optional[int] = None
    fecha_registro_asic: Optional[date] = None

    # Registro ASIC
    registrada_por: Optional[str] = None
    nivel_tension: Optional[int] = None
    nivel_tension_kv: Optional[float] = None
    transferencia_maxima_kwh: Optional[float] = Field(default=None, ge=0)
    representante_frontera: Optional[str] = None
    fecha_inicio_representacion: Optional[date] = None
    operador_red_id: Optional[int] = None

    # Tecnico
    tipo_punto_medicion: Optional[int] = None
    factor_perdidas: Optional[float] = Field(default=None, gt=0, le=2)
    clase_ct: Optional[str] = None
    clase_pt: Optional[str] = None

    # Agentes
    representante_anterior: Optional[str] = None
    agente_exportador: Optional[str] = None
    agente_importador: Optional[str] = None
    nombre_recurso_generacion: Optional[str] = None
    clasificacion_recurso: Optional[str] = None

    # Ubicacion
    centro_poblado: Optional[str] = None

    # Codigos SIC
    codigo_sic_submercado_exportador: Optional[str] = None
    codigo_sic_submercado_consumo: Optional[str] = None
    codigo_sic_frontera_generacion: Optional[str] = None
    codigo_sic_frontera_usuario: Optional[str] = None
    potencia_maxima_declarada: Optional[float] = Field(default=None, ge=0)

    # Medidor principal
    nro_serie_med_ppal: Optional[str] = None
    marca_med_ppal: Optional[str] = None
    modelo_med_ppal: Optional[str] = None
    clase_medidor: Optional[str] = None
    num_elementos_med_ppal: Optional[int] = None
    fecha_cambio_med_ppal: Optional[date] = None
    entidad_calibradora_med_ppal: Optional[str] = None
    fecha_calibracion_med_ppal: Optional[date] = None
    fecha_actualizacion_ppal: Optional[date] = None

    # Medidor respaldo
    nro_serie_med_resp: Optional[str] = None
    marca_med_resp: Optional[str] = None
    modelo_med_resp: Optional[str] = None
    num_elementos_med_resp: Optional[int] = None
    fecha_cambio_med_resp: Optional[date] = None
    entidad_calibradora_med_resp: Optional[str] = None
    fecha_calibracion_med_resp: Optional[date] = None
    fecha_actualizacion_resp: Optional[date] = None

    # Agrupacion/embebido
    es_agrupadora: Optional[bool] = None
    factor_psf: Optional[float] = Field(default=None, ge=0)
    es_principal_embebido: Optional[bool] = None
    factor_acordado: Optional[float] = Field(default=None, ge=0)
    factor_ajuste: Optional[float] = Field(default=None, ge=0)
    factor_perdidas_frontera_principal: Optional[float] = Field(default=None, ge=0)

    # Clasificacion industrial
    codigo_ciiu: Optional[str] = None
    clasificacion_industrial_general: Optional[str] = None
    clasificacion_industrial_especifica: Optional[str] = None


class FronteraOut(FronteraBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

    proyecto_nombre: Optional[str] = None
    proyecto_fecha_inicio_comercializacion: Optional[date] = None
    # Reemplaza a capacidad_transporte_mw/capacidad_efectiva_mw (eliminados
    # 2026-08-25 -- 52/53 fronteras de generacion con dato coincidian exacto
    # con esto, solo con conversion de unidad kWp->MW). potencia_instalada_kwp
    # es la fuente unica del proyecto, no se vuelve a duplicar en Frontera.
    proyecto_potencia_instalada_mw: Optional[float] = None
    # Reemplazan a Frontera.departamento/tipo_tecnologia (eliminados
    # 2026-08-25 -- coincidian 100% con esto donde ambos tenian dato).
    proyecto_departamento: Optional[str] = None
    proyecto_tipo_tecnologia: Optional[str] = None
    # Reemplaza a Frontera.municipio (eliminado 2026-08-25 -- 47/69 (68%)
    # coincidian donde ambos tenian dato, el resto eran diferencias de
    # formato/nivel de detalle, no datos contradictorios).
    proyecto_municipio: Optional[str] = None
    # Reemplaza a Frontera.direccion (eliminado 2026-08-25). A diferencia de
    # los demas campos de ubicacion, NO era el mismo texto (0/45 identicas
    # donde ambas tenian dato) -- son dos transcripciones independientes del
    # mismo sitio; Proyecto.direccion_vereda gana siempre de aca en adelante.
    proyecto_direccion: Optional[str] = None
    # Reemplazan a Frontera.latitud/longitud/altitud_msnm (eliminados
    # 2026-08-25). altitud_msnm no existia en Proyecto -- se agrego junto
    # con esta consolidacion.
    proyecto_latitud: Optional[float] = None
    proyecto_longitud: Optional[float] = None
    proyecto_altitud_msnm: Optional[int] = None
    # Basado en las últimas corridas del pipeline Reporte Energía
    # (reporte_energia_generacion), no en fecha_inicio_comercializacion --
    # cubre todas las fronteras de generación, no solo las que tienen
    # identificador de monitoreo Unergy resuelto. None = todavía sin ninguna
    # corrida para esta frontera (no implica que no genere).
    generando_actual: Optional[bool] = None
    fecha_ultima_generacion: Optional[date] = None
    operador_comercial: Optional[str] = None
    operador_correos: list[str] = []
    # Uno por cada cliente que sea fuente del contacto CGM de este proyecto
    # (puntero de área, o inversionista vigente si no hay puntero) -- puede
    # haber varios si el proyecto tiene varios inversionistas.
    clientes_cgm: list[dict] = []



class FronteraQuoiaPendiente(BaseModel):
    frt_code: str
    nombre_quoia: str
    categoria: str  # "generacion" | "consumo"
    proyecto_sugerido_id: Optional[int] = None
    proyecto_sugerido_nombre: Optional[str] = None


class FronteraQuoiaConfirmar(BaseModel):
    proyecto_id: int
    nombre_frontera: Optional[str] = None
    tipo_frontera: Optional[TipoFronteraEnum] = None


class FronteraQuoiaIgnorar(BaseModel):
    motivo: Optional[str] = None
