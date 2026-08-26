from datetime import date, datetime

from pydantic import BaseModel


class FronteraReporteItem(BaseModel):
    """Una fila de la lista priorizada (Revisión de hoy)."""
    frontera_id: int
    proyecto_id: int | None
    nombre_proyecto: str
    tipo: str  # "generacion" | "consumo"
    caso: str  # int como str para Generación, texto para Consumo
    medidor_usado: str | None
    energia_final_kwh: float | None
    revisar_manualmente: bool
    editado_manualmente: bool
    nota_solenium: str | None = None

    class Config:
        from_attributes = True


class ResumenReporteEnergia(BaseModel):
    fecha: date
    total: int
    revisar: int
    corregido_automatico: int
    confiado: int
    puede_enviar: bool  # False si queda algún 'revisar_manualmente' pendiente


class SerieFuente(BaseModel):
    nombre: str
    curva: list[float | None]


class DetalleFronteraReporte(BaseModel):
    frontera_id: int
    proyecto_id: int | None
    nombre_proyecto: str
    tipo: str
    fecha: date
    caso: str
    medidor_usado: str | None
    energia_final_kwh: float | None
    curva_final: list[float | None]
    fp: float | None = None
    fp_calculada: float | None = None
    error_final_pct: float | None = None
    energia_cgm_kwh: float | None = None
    estado_reporte: str | None = None
    energia_solenium_kwh: float | None = None
    solenium_completo: bool | None = None
    nota_solenium: str | None = None
    horas_rellenadas_reconectador: list[int] | None = None
    horas_rellenadas_solenium: list[int] | None = None
    horas_rellenadas_historico: list[int] | None = None
    # Horas rellenadas con el otro medidor (el que no ganó como fuente) --
    # Generación y Consumo -- dato real de un medidor, no una estimación.
    horas_rellenadas_medidor_cruzado: list[int] | None = None
    recuperacion_datos: str | None = None
    revisar_manualmente: bool
    editado_manualmente: bool
    error_clasificacion: str | None = None
    enviado_quoia_en: datetime | None = None
    enviado_quoia_ok: bool | None = None
    enviado_quoia_error: str | None = None
    # Curvas de referencia -- siempre presentes cuando existan, sin importar
    # qué Caso ganó (para comparar visualmente).
    curva_medidor_principal: list[float | None] | None = None
    curva_medidor_respaldo: list[float | None] | None = None
    curva_solenium: list[float | None] | None = None
    # A diferencia de las de arriba, casi siempre viene en null -- solo se
    # llenó si el reconectador se consultó ese día (medidor+inversores ya
    # dejaron huecos sin cubrir). Solo aplica a Generación.
    curva_reconectador: list[float | None] | None = None
    # True si el valor EN VIVO de Quoia de ESE medidor ya difiere del que
    # quedó guardado al momento de clasificar -- señal de que conviene
    # recuperar/revisar (ver MGS 0032 El Paso Norte 2026-08-05). Por
    # medidor, no solo el que ganó como medidor_usado (2026-08-20): si el
    # clasificador usó 'Histórico' porque el medidor estaba mal, y luego se
    # recupera el medidor, esto tiene que poder avisarlo igual. None-safe:
    # si la fila es de antes de este fix (sin curva persistida), no hay
    # base de comparación y queda en False.
    principal_actualizado_en_quoia: bool = False
    respaldo_actualizado_en_quoia: bool = False
    # Total y curva EN VIVO de cada medidor -- solo presentes cuando su
    # *_actualizado_en_quoia=True. *_energia_actual_kwh alimenta el aviso
    # "X kWh ahora vs Y kWh al momento de clasificar"; *_curva_actual
    # permite reportar directamente con ese valor desde "Reportar con otra
    # fuente" (front), sin importar cuál medidor esté en uso hoy.
    principal_energia_actual_kwh: float | None = None
    principal_curva_actual: list[float | None] | None = None
    respaldo_energia_actual_kwh: float | None = None
    respaldo_curva_actual: list[float | None] | None = None
    # Curva 'Backup' del Excel de terceros (FRONTERAS_TERCEROS) -- distinta
    # de curva_medidor_respaldo (esa es telemetría en vivo del medidor de
    # nodo, que para estas fronteras no existe).
    curva_respaldo_terceros: list[float | None] | None = None
    # Lo que /enviar realmente manda como "Backup" a Quoia -- mismo cálculo
    # que curva_respaldo_a_reportar() (utils.py), para que esto se vea ANTES
    # de enviar, no solo después. origen: 'terceros' | 'medidor' (dato real
    # del medidor de respaldo, auto-detectado) | 'manual' (columna Respaldo
    # de la tabla de corrección, confirmada a mano) | 'estimado' (±1%).
    # Solo Generación.
    #
    # EXCEPCIÓN -- medidor_usado == 'cgm' (Caso 1): acá NADA se manda a
    # Quoia (_reporte_ya_valido() salta el envío entero -- el reporte
    # automático de Quoia ya es válido, y Quoia calcula su propio Backup
    # por su cuenta, que nunca vemos ni tocamos). Estos dos campos SÍ se
    # calculan igual para 'cgm' (ampliado 2026-08-26, por consistencia
    # visual con Principal en el detalle/tabla) pero ahí son puramente
    # informativos -- "así se vería si se enviara", no "esto se va a
    # enviar".
    curva_respaldo_reportada: list[float | None] | None = None
    respaldo_reportado_origen: str | None = None
    # Capacidad efectiva de la frontera (MW) -- referencia visual en el chart
    # para confirmar que la curva de generación nunca la supera.
    capacidad_efectiva_mw: float | None = None


class EditarCurvaRequest(BaseModel):
    curva_final: list[float | None]
    nota: str | None = None
    # Cuál opción de "Reportar con otra fuente" se usó para llenar el editor
    # (si alguna) -- para que 'Fuente usada' refleje la fuente real elegida
    # en vez de un genérico "editado manualmente". None si la persona editó
    # celdas a mano sin pasar por ese desplegable.
    fuente: str | None = None
    # Respaldo confirmado a mano (columna nueva de la tabla de corrección,
    # solo Generación) -- si viene, se guarda tal cual como dato real
    # ('manual'), sin pasar por curva_respaldo_a_reportar(). None (no solo
    # todo-en-null) significa "la persona no tocó esta columna": se recalcula
    # con la lógica automática de siempre (real del medidor si aplica, si no
    # ±1%). Distinto de "24 valores en null", que SÍ es una confirmación
    # explícita (sin dato real de respaldo para reportar).
    curva_respaldo_final: list[float | None] | None = None


class ValidarResponse(BaseModel):
    frontera_id: int
    fecha: date
    revisar_manualmente: bool


class EjecutarDiaResponse(BaseModel):
    """La clasificación corre en segundo plano (ver orquestador.ejecutar_dia_background)
    -- este response solo confirma que arrancó, no incluye los conteos finales."""
    fecha: date
    status: str


class EnviarReporteEnergiaResponse(BaseModel):
    fecha: date
    enviados: int
    fallidos: list[str]
    bloqueado: bool
    motivo_bloqueo: str | None = None


class EstadoXMFrontera(BaseModel):
    """Una fila enviada que XM ya resolvió con error -- para poder ir
    directo a esa frontera desde el contador."""
    frontera_id: int
    nombre_proyecto: str
    tipo: str  # "generacion" | "consumo"


class EstadoXMResponse(BaseModel):
    """Resultado de revisar en Quoia si XM ya resolvió los reportes
    enviados ese día -- distinto de EnviarReporteEnergiaResponse (que es
    sobre si el POST a Quoia salió bien, no sobre la aprobación de XM)."""
    fecha: date
    total: int
    en_espera: int
    exitoso: int
    exitoso_con_alerta: int
    error: int
    fallidas: list[EstadoXMFrontera]


class DistribucionFuenteItem(BaseModel):
    """Cuántas veces se usó cada fuente en el rango -- 'etiqueta' es
    medidor_usado (Generación) o caso (Consumo); los vocabularios de los
    dos árboles no son comparables 1:1, por eso van en listas separadas."""
    etiqueta: str
    total: int


class RankingIncompletoItem(BaseModel):
    """Solo Generación -- Consumo no tiene medidor_principal_completo/
    respaldo_completo/solenium_completo (no hay inversores contra qué
    comparar)."""
    frontera_id: int
    nombre_proyecto: str
    veces_medidor_principal_incompleto: int
    veces_medidor_respaldo_incompleto: int
    veces_solenium_incompleto: int
    dias_con_fila: int


class DesgloseFuenteItem(BaseModel):
    """Una fuente cruda (ej. 'Inversores × FP') y cuántos días aportó --
    el detalle detrás del número agrupado de una tarjeta KPI."""
    etiqueta: str
    dias: int


class DetalleFuenteFronteraItem(BaseModel):
    """Una fila del drill-down por frontera al hacer clic en una tarjeta
    KPI de distribución de fuente -- 'grupo' es el mismo agrupado
    (Medidor/Inversor/Estimación/Sin fuente) que la tarjeta."""
    frontera_id: int
    nombre_proyecto: str
    grupo: str
    dias_totales: int
    dias_grupo: int
    desglose: list[DesgloseFuenteItem]


class ResumenCallout(BaseModel):
    """Una métrica de una sola línea para mostrar arriba de una tabla de
    ranking (ej. '9 fronteras con datos incompletos') -- 'valor' ya viene
    formateado (número o porcentaje) para que el frontend no tenga que
    decidir el formato caso por caso."""
    valor: str
    etiqueta: str


class ResumenHistoricoResponse(BaseModel):
    desde: date
    hasta: date
    distribucion_fuente_generacion: list[DistribucionFuenteItem]
    distribucion_fuente_consumo: list[DistribucionFuenteItem]
    detalle_fuente_generacion: list[DetalleFuenteFronteraItem]
    detalle_fuente_consumo: list[DetalleFuenteFronteraItem]
    incompletos: list[RankingIncompletoItem]
    incompletos_callouts: list[ResumenCallout]


class EstadoCorridaResponse(BaseModel):
    """Resultado de la última vez que se corrió /ejecutar para esta fecha --
    null (terminado_en=None) si nunca se ha corrido o todavía está en curso."""
    fecha: date
    terminado_en: datetime | None = None
    fallidas: list[str] = []
    omitidas: list[str] = []
    error_general: str | None = None
    cancelado: bool = False


class CancelarCorridaResponse(BaseModel):
    fecha: date
    solicitado: bool


class CrearExclusionRequest(BaseModel):
    frontera_id: int
    motivo: str
    fecha_inicio: date
    fecha_fin_estimada: date | None = None


class EditarExclusionRequest(BaseModel):
    motivo: str
    fecha_fin_estimada: date | None = None


class CurvaTipicaResponse(BaseModel):
    """Mediana x forma horaria de los últimos días confiables (mismo
    mecanismo que ya alimenta el relleno histórico) -- para el botón
    "Curva Típica" en Corrección manual."""
    curva: list[float | None]
    energia_total_kwh: float
    dias_usados: int


class CargaExcelTercerosResponse(BaseModel):
    """Resultado de subir el Excel de una empresa tercera (FRONTERAS_TERCEROS,
    ej. Cedillanos) -- una fecha por cada día con fila 'Primary' en el archivo."""
    frontera_id: int
    fechas_cargadas: list[date]


class ExclusionOut(BaseModel):
    id: int
    frontera_id: int
    nombre_frontera: str | None = None
    motivo: str
    fecha_inicio: date
    fecha_fin_estimada: date | None
    creado_por: str | None
    resuelta_en: datetime | None
    created_at: datetime
