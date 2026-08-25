from typing import Optional

from pydantic import BaseModel


class ProyectoLiquidacionesOut(BaseModel):
    """Proyecto de esta base cruzado con su configuración en la API de Liquidaciones."""

    proyecto_id: int
    nombre_comercial: str
    tipo_proyecto: Optional[str] = None
    estado: Optional[str] = None
    # Identificador del proyecto en la API externa (proyectos.sub_project).
    nombre_topico: Optional[str] = None
    # True si el tópico existe en la API; si es False los campos vienen vacíos.
    en_api: bool = False

    sic_gen: Optional[str] = None
    sic_con: Optional[str] = None
    frt_gen: Optional[str] = None
    frt_con: Optional[str] = None
    ac_power: Optional[float] = None
    from_generator: Optional[bool] = None
    from_commercializer: Optional[bool] = None

    # Los ids de Quoia no son del proyecto: son de cada subproyecto. Un proyecto
    # puede tener varios, así que vienen como lista y no como tres campos.
    subproyectos: list["SubproyectoQuoiaOut"] = []


class ProyectoLiquidacionesUpdate(BaseModel):
    """Campos editables de la configuración de liquidaciones (§3.1 de la guía)."""

    sic_gen: Optional[str] = None
    sic_con: Optional[str] = None
    frt_gen: Optional[str] = None
    frt_con: Optional[str] = None
    ac_power: Optional[float] = None
    from_generator: Optional[bool] = None
    from_commercializer: Optional[bool] = None


class TareaEstadoOut(BaseModel):
    """Estado normalizado de una tarea asíncrona del ciclo de liquidaciones."""

    task_id: str
    # 'en_curso' | 'exito' | 'fallo' (ver services.liquidaciones_api.EstadoTarea).
    estado: str
    # Estado crudo de Celery, para diagnóstico.
    estado_crudo: str
    terminada: bool
    mensaje: str
    # Cuerpo crudo de la tarea: trae cosas puntuales como `drive_url`.
    resultado: Optional[dict] = None


class FacturaXmOut(BaseModel):
    """Una factura de XM ya procesada por la API."""

    id: int
    codigo: Optional[str] = None
    nombre: Optional[str] = None
    agente: Optional[str] = None
    mes: Optional[int] = None
    mes_nombre: Optional[str] = None
    anio: Optional[int] = None
    version: Optional[str] = None
    periodo_inicio: Optional[str] = None
    periodo_fin: Optional[str] = None
    vencimiento: Optional[str] = None
    procesada_el: Optional[str] = None
    estado_procesamiento: Optional[str] = None
    error: Optional[str] = None
    valor_total: Optional[float] = None
    total_declarado: Optional[float] = None
    total_valido: Optional[bool] = None
    campos_extraidos: Optional[int] = None


class FacturasXmReadinessOut(BaseModel):
    """Precondición de §4.6: si no está lista, ``bloqueos`` dice qué falta."""

    lista_para_repartir: bool = False
    total: int = 0
    completadas: int = 0
    tiene_factura_generador: bool = False
    tiene_factura_comercializador: bool = False
    bloqueos: list[str] = []
    sin_completar: list[dict] = []
    totales_invalidos: list[dict] = []


class FacturasXmOut(BaseModel):
    """Listado de facturas de un período junto con su estado de alistamiento."""

    count: int
    readiness: FacturasXmReadinessOut
    results: list[FacturaXmOut]


class SubidaFacturasXmOut(BaseModel):
    """Confirmación de la subida: el procesamiento sigue en una tarea asíncrona."""

    task_id: Optional[str] = None
    invoice_ids: list[int] = []
    files_queued: int = 0


# ── Ciclo mensual ────────────────────────────────────────────────────────────

class PeriodoIn(BaseModel):
    """Período del ciclo. La versión sale de VersionLiquidacion."""

    month: int
    year: int
    version: str = "txf"


class IppOut(BaseModel):
    """IPP del DANE para el período. Síncrono."""

    month: int
    year: int
    ipp: float


class TareaLanzadaOut(BaseModel):
    """Tarea recién disparada: se sondea con GET /liquidaciones-api/tareas/{id}."""

    task_id: str


class RepartoIn(PeriodoIn):
    """Reparto de las facturas de XM (§4.6)."""

    total_ac_power: float
    # 🔴 Debe ir en True la primera corrida del período: con False y sin reparto
    # previo la API borra los costos XM y no crea nada, sin reportar error.
    override: bool = True
    last_version: Optional[str] = None


class DiagnosticoIn(PeriodoIn):
    """Diagnóstico «por qué este proyecto no sale en el ER» (§5.2)."""

    # Tópico del proyecto en la API externa (proyectos.sub_project).
    project: str


# ── Despachos liquidados ─────────────────────────────────────────────────────

class DespachoLiquidadoOut(BaseModel):
    """Un despacho liquidado: un día, un contrato, un tipo de dato."""

    id: Optional[int] = None
    # Nombre de esta base; cae al tópico si el proyecto no cruza.
    proyecto: Optional[str] = None
    topico: Optional[str] = None
    fecha: Optional[str] = None
    # dispatch | purchase | dispatch_fazni
    tipo_dato: Optional[str] = None
    energia_kwh: Optional[float] = None
    valor: Optional[float] = None
    codigo_contrato: Optional[str] = None
    contrato_proyecto_id: Optional[int] = None
    version: Optional[str] = None


class DespachosLiquidadosOut(BaseModel):
    count: int
    results: list[DespachoLiquidadoOut]
    # Proyectos cuyas cifras están incompletas, con el motivo.
    avisos: list[dict] = []


# ── Consumo (energía contratada por hora) ────────────────────────────────────

class ConsumoDiaOut(BaseModel):
    """Las 24 horas de energía contratada de un proyecto en un día, en kWh."""

    id: Optional[int] = None
    proyecto: Optional[str] = None
    topico: Optional[str] = None
    fecha: Optional[str] = None
    version: Optional[str] = None
    # 24 valores, de la hora 1 a la 24. Puede haber huecos (None).
    horas: list[Optional[float]] = []
    # Calculado aquí: la API no expone un total.
    total_diario: Optional[float] = None


class ConsumoOut(BaseModel):
    count: int
    results: list[ConsumoDiaOut]


# ── IPP histórico ────────────────────────────────────────────────────────────

class IppHistoricoOut(BaseModel):
    """Un IPP consultado al DANE.

    Puede haber varias filas del mismo período: se guarda una por consulta, con
    la fecha en que se hizo. ``vigente`` marca la más reciente de cada mes.
    """

    id: Optional[int] = None
    anio: Optional[int] = None
    mes: Optional[int] = None
    ipp: Optional[float] = None
    consultado_el: Optional[str] = None
    vigente: bool = False


# ── Subproyectos e ids de Quoia ──────────────────────────────────────────────

class SubproyectoQuoiaOut(BaseModel):
    """Los tres ids de Quoia de un subproyecto, tal como los guarda la API."""

    topic: str
    name: Optional[str] = None
    quoia_report_gen_id: Optional[str] = None
    quoia_report_con_id: Optional[str] = None
    quoia_node_id: Optional[str] = None


class SubproyectoQuoiaUpdate(BaseModel):
    """PATCH parcial: lo que no se envía no se toca, y ``null`` **borra** el id."""

    # Máximo 4 caracteres los de reporte, 50 el del nodo (lo valida el servicio).
    quoia_report_gen_id: Optional[str] = None
    quoia_report_con_id: Optional[str] = None
    quoia_node_id: Optional[str] = None


# ── Costos e ingresos fijos ──────────────────────────────────────────────────

class CostoOut(BaseModel):
    id: int
    proyecto: Optional[str] = None
    tipo_pago: Optional[str] = None
    tipo_pago_nombre: Optional[str] = None
    grupo: Optional[str] = None
    valor: Optional[float] = None
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    frecuencia_pago: Optional[str] = None
    version: Optional[str] = None


class CostosOut(BaseModel):
    """Listado paginado: la tabla completa pasa de 10.000 filas."""

    total: int
    page: int
    size: int
    # Cuántos costos en cero quedaron fuera con los filtros actuales. Viaja
    # aunque se estén mostrando, para poder decir "N en cero ocultas" en vez de
    # que parezca que esos conceptos no existen.
    ocultos_en_cero: int = 0
    results: list[CostoOut]


# ── Contratos de energía ─────────────────────────────────────────────────────

class ContratoProyectoOut(BaseModel):
    id: int
    proyecto: Optional[str] = None
    precio_energia_id: Optional[int] = None
    precio_energia: Optional[str] = None
    # Un contrato PLC necesita un piso Y un techo; si falta alguno, liquidar falla.
    tiene_piso: bool = False
    tiene_techo: bool = False


class ContratoEnergiaOut(BaseModel):
    id: int
    fecha_desde: Optional[str] = None
    fecha_hasta: Optional[str] = None
    codigo: Optional[str] = None
    tipo_contrato: Optional[str] = None
    tipo_tarifa: Optional[str] = None
    porcentaje: Optional[float] = None
    empresa_id: Optional[int] = None
    empresa: Optional[str] = None
    proyectos: list[ContratoProyectoOut] = []


class ContratoProyectoIn(BaseModel):
    project: str
    energy_price: Optional[int] = None
    # 24 valores horarios en kWh, solo para contratos PLC.
    floor: Optional[list[float]] = None
    roof: Optional[list[float]] = None


class ContratoEnergiaIn(BaseModel):
    date_from: str
    date_to: str
    contract_type: str
    tariff_price_type: str
    code: Optional[str] = None
    company: Optional[int] = None
    # Fracción 0–1, no porcentaje. Solo PLG.
    percentage: Optional[float] = None
    proyectos: list[ContratoProyectoIn] = []


class CatalogosOut(BaseModel):
    """Catálogos de la API externa para resolver los selects."""

    empresas: list[dict] = []
    precios_energia: list[dict] = []
    tipos_costo: list[dict] = []


# ── AC Power del período ─────────────────────────────────────────────────────

class AcPowerGrupoOut(BaseModel):
    """Cuántos proyectos reciben un grupo de conceptos y cuánta potencia suman."""

    proyectos: int = 0
    ac_power: float = 0.0
    sin_ac_power: int = 0


class AcPowerTotalesOut(BaseModel):
    """Totales de AC Power tal como los ve la API de Liquidaciones.

    Se calculan sobre TODOS los proyectos de esa API, no solo los que cruzan con
    esta base: ``total_ac_power`` es el divisor de la prorrata del reparto, así
    que dejar fuera un proyecto le sube el costo a todos los demás.
    """

    generador: AcPowerGrupoOut
    comercializador: AcPowerGrupoOut
    # Tópicos que la API cobra pero que no existen en esta base: se listan para
    # que se note que falta emparejarlos, en vez de perderlos en silencio.
    topicos_sin_cruce: list[str] = []


# `ProyectoLiquidacionesOut` referencia `SubproyectoQuoiaOut`, que se define más
# abajo: hay que resolver la referencia adelantada antes de que FastAPI arme el
# esquema de respuesta.
ProyectoLiquidacionesOut.model_rebuild()
