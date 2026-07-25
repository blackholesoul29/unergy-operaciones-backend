from pydantic import BaseModel, ConfigDict
from datetime import date, datetime
from typing import Optional


class FronteraBase(BaseModel):
    proyecto_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    nombre_frontera: str
    codigo_propio: Optional[str] = None
    tipo_frontera: str
    estado: Optional[str] = "activa"
    quoia_border_id: Optional[int] = None
    fecha_registro_asic: Optional[date] = None
    fecha_primer_registro_asic: Optional[date] = None

    # Registro ASIC
    registrada_por: Optional[str] = None
    nit: Optional[str] = None
    nivel_tension: Optional[int] = None
    nivel_tension_kv: Optional[float] = None
    transferencia_maxima_kwh: Optional[float] = None
    representante_frontera: Optional[str] = None
    fecha_inicio_representacion: Optional[date] = None
    operador_red: Optional[str] = None
    operador_red_id: Optional[int] = None
    operador_red_zona: Optional[str] = None
    nombre_cgm: Optional[str] = None
    predio_id: Optional[str] = None
    nombre_predio: Optional[str] = None
    representante_ddv: Optional[str] = None

    # Técnico
    tipo_punto_medicion: Optional[int] = None
    capacidad_transporte_mw: Optional[float] = None
    capacidad_transporte_compartida_mw: Optional[float] = None
    capacidad_efectiva_mw: Optional[float] = None
    factor_perdidas: Optional[float] = None
    clase_ct: Optional[str] = None
    clase_pt: Optional[str] = None

    # Agentes
    nit_rf: Optional[str] = None
    nit_cgm: Optional[str] = None
    representante_anterior: Optional[str] = None
    agente_exportador: Optional[str] = None
    agente_importador: Optional[str] = None
    nombre_recurso_generacion: Optional[str] = None
    clasificacion_recurso: Optional[str] = None

    # Operativo
    niu: Optional[str] = None
    consumo_promedio_mensual_mwh: Optional[float] = None
    relacion_transformacion_ct: Optional[str] = None
    relacion_transformacion_pt: Optional[str] = None

    # Ubicación
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    centro_poblado: Optional[str] = None
    direccion: Optional[str] = None
    subestacion: Optional[str] = None
    punto_conexion: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    altitud_msnm: Optional[int] = None

    # Códigos SIC
    codigo_sic_ddv: Optional[str] = None
    codigo_sic_submercado_exportador: Optional[str] = None
    codigo_sic_submercado_consumo: Optional[str] = None
    codigo_sic_submercado_usuario: Optional[str] = None
    codigo_sic_frontera_generacion: Optional[str] = None
    codigo_sic_frontera_usuario: Optional[str] = None
    potencia_maxima_declarada: Optional[float] = None
    tipo_tecnologia: Optional[str] = None

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
    factor_psf: Optional[float] = None
    es_principal_embebido: Optional[bool] = False
    factor_acordado: Optional[float] = None
    factor_ajuste: Optional[float] = None
    factor_perdidas_frontera_principal: Optional[float] = None

    # Clasificación industrial
    codigo_ciiu: Optional[str] = None
    clasificacion_industrial_general: Optional[str] = None
    clasificacion_industrial_especifica: Optional[str] = None


class FronteraCreate(FronteraBase):
    frontera_gemela_id: Optional[int] = None
    agrupada_bajo_id: Optional[int] = None
    embebida_bajo_id: Optional[int] = None


class FronteraUpdate(BaseModel):
    """All fields optional for PATCH updates."""
    proyecto_id: Optional[int] = None
    codigo_frontera: Optional[str] = None
    nombre_frontera: Optional[str] = None
    codigo_propio: Optional[str] = None
    tipo_frontera: Optional[str] = None
    estado: Optional[str] = None
    quoia_border_id: Optional[int] = None
    fecha_registro_asic: Optional[date] = None
    fecha_primer_registro_asic: Optional[date] = None

    # Registro ASIC
    registrada_por: Optional[str] = None
    nit: Optional[str] = None
    nivel_tension: Optional[int] = None
    nivel_tension_kv: Optional[float] = None
    transferencia_maxima_kwh: Optional[float] = None
    representante_frontera: Optional[str] = None
    fecha_inicio_representacion: Optional[date] = None
    operador_red: Optional[str] = None
    operador_red_id: Optional[int] = None
    operador_red_zona: Optional[str] = None
    nombre_cgm: Optional[str] = None
    predio_id: Optional[str] = None
    nombre_predio: Optional[str] = None
    representante_ddv: Optional[str] = None

    # Tecnico
    tipo_punto_medicion: Optional[int] = None
    capacidad_transporte_mw: Optional[float] = None
    capacidad_transporte_compartida_mw: Optional[float] = None
    capacidad_efectiva_mw: Optional[float] = None
    factor_perdidas: Optional[float] = None
    clase_ct: Optional[str] = None
    clase_pt: Optional[str] = None

    # Agentes
    nit_rf: Optional[str] = None
    nit_cgm: Optional[str] = None
    representante_anterior: Optional[str] = None
    agente_exportador: Optional[str] = None
    agente_importador: Optional[str] = None
    nombre_recurso_generacion: Optional[str] = None
    clasificacion_recurso: Optional[str] = None

    # Operativo
    niu: Optional[str] = None
    consumo_promedio_mensual_mwh: Optional[float] = None
    relacion_transformacion_ct: Optional[str] = None
    relacion_transformacion_pt: Optional[str] = None

    # Ubicacion
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    centro_poblado: Optional[str] = None
    direccion: Optional[str] = None
    subestacion: Optional[str] = None
    punto_conexion: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    altitud_msnm: Optional[int] = None

    # Codigos SIC
    codigo_sic_ddv: Optional[str] = None
    codigo_sic_submercado_exportador: Optional[str] = None
    codigo_sic_submercado_consumo: Optional[str] = None
    codigo_sic_submercado_usuario: Optional[str] = None
    codigo_sic_frontera_generacion: Optional[str] = None
    codigo_sic_frontera_usuario: Optional[str] = None
    potencia_maxima_declarada: Optional[float] = None
    tipo_tecnologia: Optional[str] = None

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
    factor_psf: Optional[float] = None
    es_principal_embebido: Optional[bool] = None
    factor_acordado: Optional[float] = None
    factor_ajuste: Optional[float] = None
    factor_perdidas_frontera_principal: Optional[float] = None

    # Self-referential FK
    frontera_gemela_id: Optional[int] = None
    agrupada_bajo_id: Optional[int] = None
    embebida_bajo_id: Optional[int] = None

    # Clasificacion industrial
    codigo_ciiu: Optional[str] = None
    clasificacion_industrial_general: Optional[str] = None
    clasificacion_industrial_especifica: Optional[str] = None


class FronteraOut(FronteraBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    frontera_gemela_id: Optional[int] = None
    agrupada_bajo_id: Optional[int] = None
    embebida_bajo_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    proyecto_nombre: Optional[str] = None
    operador_comercial: Optional[str] = None
    operador_correos: list[str] = []
    # Uno por cada cliente que sea fuente del contacto CGM de este proyecto
    # (puntero de área, o inversionista vigente si no hay puntero) -- puede
    # haber varios si el proyecto tiene varios inversionistas.
    clientes_cgm: list[dict] = []


class FronteraLecturaCreate(BaseModel):
    fuente: str
    fecha_hora: datetime
    periodo_inicio: date
    periodo_fin: date
    energia_activa_import_kwh: Optional[float] = None
    energia_activa_export_kwh: Optional[float] = None
    energia_react_ind_import_kvarh: Optional[float] = None
    energia_react_ind_export_kvarh: Optional[float] = None
    energia_react_cap_import_kvarh: Optional[float] = None
    energia_react_cap_export_kvarh: Optional[float] = None


class FronteraLecturaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    frontera_id: int
    fuente: str
    fecha_hora: datetime
    periodo_inicio: date
    periodo_fin: date
    energia_activa_import_kwh: Optional[float] = None
    energia_activa_export_kwh: Optional[float] = None
    energia_react_ind_import_kvarh: Optional[float] = None
    energia_react_ind_export_kvarh: Optional[float] = None
    energia_react_cap_import_kvarh: Optional[float] = None
    energia_react_cap_export_kvarh: Optional[float] = None
    created_at: datetime


class FronteraResumen(BaseModel):
    total_activas: int
    total_inactivas: int
    total_kwh_import_30d: float
    total_kwh_export_30d: float
    sin_datos_recientes: int
    fronteras_sin_datos: list[dict]


class FronteraQuoiaPendiente(BaseModel):
    frt_code: str
    nombre_quoia: str
    categoria: str  # "generacion" | "consumo"
    proyecto_sugerido_id: Optional[int] = None
    proyecto_sugerido_nombre: Optional[str] = None


class FronteraQuoiaConfirmar(BaseModel):
    proyecto_id: int
    nombre_frontera: Optional[str] = None
    codigo_propio: Optional[str] = None
    tipo_frontera: Optional[str] = None


class FronteraQuoiaIgnorar(BaseModel):
    motivo: Optional[str] = None
