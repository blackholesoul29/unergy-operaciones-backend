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
    cedula_agente_vendedor: str | None = None
    cedula_agente_comprador: str | None = None
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
    uso_del_recurso: bool = False
    fecha_envio_xm: date | None = None
    fecha_respuesta_xm: date | None = None
    numero_radicado: str | None = None
    created_at: datetime

    # Nombre de la planta (resuelto en endpoint)
    proyecto_id: int | None = None
    planta_nombre: str | None = None
    contrato_ppa_id: int | None = None

    # Vigencia efectiva (calculada en endpoint vía gescon_vigencia, no almacenada).
    # fecha_fin_efectiva: fin REAL de la ventana — recortada si un relevo o una
    # modificación posterior en el mismo SIC superó a esta fila (la fecha_fin
    # cruda se conserva arriba). None = abierta o sin resolver (fallback: cruda).
    # es_version_vigente: esta fila es la versión vigente actual de su SIC
    # (False para filas superadas, terminadas, no publicadas o desistimientos).
    fecha_fin_efectiva: date | None = None
    es_version_vigente: bool = False


class AsicSolicitudCreate(BaseModel):
    requerimiento_asic: str | None = None
    tipo_solicitud: str
    prioridad_limitacion: int | None = None
    codigo_sic_contrato: str | None = None
    codigo_sic_vendedor: str | None = None
    codigo_sic_comprador: str | None = None
    cedula_agente_vendedor: str | None = None
    cedula_agente_comprador: str | None = None
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
    uso_del_recurso: bool = False
    proyecto_id: int | None = None
    contrato_ppa_id: int | None = None

    # XM tracking
    fecha_envio_xm: date | None = None
    fecha_respuesta_xm: date | None = None
    numero_radicado: str | None = None


class AsicSolicitudUpdate(BaseModel):
    requerimiento_asic: str | None = None
    tipo_solicitud: str | None = None
    prioridad_limitacion: int | None = None
    codigo_sic_contrato: str | None = None
    codigo_sic_vendedor: str | None = None
    codigo_sic_comprador: str | None = None
    cedula_agente_vendedor: str | None = None
    cedula_agente_comprador: str | None = None
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
    uso_del_recurso: bool | None = None
    proyecto_id: int | None = None
    contrato_ppa_id: int | None = None

    # XM tracking
    fecha_envio_xm: date | None = None
    fecha_respuesta_xm: date | None = None
    numero_radicado: str | None = None


class AsicModificacionCreate(BaseModel):
    """Modificación de un contrato GESCON ya registrado.

    Todo ocurre bajo el MISMO código SIC: lo único que una modificación puede
    cambiar es la fecha de fin, la planta inscrita, su % de despacho y su
    modalidad de suministro. El resto de datos (contrato interno, nombre
    interno, SIC vendedor/comprador, prioridad, tipo de mercado, % FNCER,
    cédulas, contacto, PPA) se HEREDA de la versión vigente de ese SIC: no
    tiene sentido volver a capturarlos y dejarlos vacíos rompería Cumplimiento,
    que resuelve por `contrato_interno`.

    `fecha_entrada` es el día en que la modificación toma efecto: se guarda como
    `fecha_inicio` de la fila nueva y `app/utils/gescon_vigencia.py` recorta la
    versión anterior al día previo. Antes de esa fecha nada cambia.
    """

    codigo_sic_contrato: str
    fecha_entrada: date
    requerimiento_asic: str

    # Lo modificable. Ausente = se hereda de la versión vigente.
    fecha_fin: date | None = None
    proyecto_id: int | None = None
    # Fracción 0-1 (1 = 100%), igual que en la tabla: Cumplimiento la usa como
    # multiplicador directo (generación × porcentaje_despacho).
    porcentaje_despacho: float | None = None
    modalidad: str | None = None  # normal | duplicado | uso_recurso

    # Cuál planta sale, cuando el SIC tiene varias coexistiendo.
    proyecto_saliente_id: int | None = None

    # Metadatos opcionales de la radicación.
    estado_solicitud: str = "publicado"
    fecha_solicitud: date | None = None
    link_archivo: str | None = None
    observaciones: str | None = None


class AsicModificacionOut(BaseModel):
    modificacion: AsicSolicitudOut
    # Fila de la planta que salió, cerrada explícitamente. Solo se llena cuando
    # el SIC tenía varias plantas coexistiendo y la modificación releva a una
    # sola: en el caso normal (una planta) el recorte lo hace la resolución de
    # vigencia, sin tocar datos.
    saliente: AsicSolicitudOut | None = None
    resumen: str


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
