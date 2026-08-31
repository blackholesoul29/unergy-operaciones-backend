from datetime import date
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict

EstadoItem = Literal["aprobado", "pendiente"]


class ItemChecklist(BaseModel):
    """Ítem de checklist genérico: estado + nota (motivo si quedó pendiente)."""
    estado: Optional[EstadoItem] = None
    nota: Optional[str] = None


class ItemChecklistConEvidencia(ItemChecklist):
    evidencia: list[Any] = []


class InversorLimitado(BaseModel):
    id: Optional[int] = None
    nombre: Optional[str] = None
    limitado: bool = False
    motivo_limitacion: Optional[str] = None


class ChecklistFusionSolar(BaseModel):
    starlink: ItemChecklistConEvidencia = ItemChecklistConEvidencia()
    datos_coherentes: ItemChecklist = ItemChecklist()
    evidencia: list[Any] = []
    nota: Optional[str] = None
    inversores: list[InversorLimitado] = []


class ChecklistFrontera(BaseModel):
    principal: ItemChecklistConEvidencia = ItemChecklistConEvidencia()
    respaldo: ItemChecklistConEvidencia = ItemChecklistConEvidencia()


class ChecklistEstacionMeteo(BaseModel):
    instalacion: ItemChecklist = ItemChecklist()
    en_plataforma: ItemChecklist = ItemChecklist()
    reporta_datos: ItemChecklistConEvidencia = ItemChecklistConEvidencia()
    poa: ItemChecklist = ItemChecklist()
    temperatura_ambiente: ItemChecklist = ItemChecklist()
    velocidad_viento: ItemChecklist = ItemChecklist()
    direccion_viento: ItemChecklist = ItemChecklist()


class ChecklistReconectador(BaseModel):
    tiene: Optional[bool] = None
    en_plataforma: ItemChecklist = ItemChecklist()
    calidad_datos: ItemChecklist = ItemChecklist()
    evidencia: list[Any] = []
    nota: Optional[str] = None


# ── Pendiente ──────────────────────────────────────────────────────────────

class PendienteItem(BaseModel):
    descripcion: Optional[str] = None
    responsable: Optional[str] = None
    fecha_compromiso: Optional[str] = None
    clasificacion: Optional[str] = None
    estado: Optional[str] = None
    observaciones: Optional[str] = None


# ── Ficha (editable de punta a punta en un solo PUT) ────────────────────────

class InformeOMFicha(BaseModel):
    """Ficha completa de Puesta en Marcha -- checklist de comisionamiento +
    contenido del informe formal, todo en un solo modelo desde la fusión
    2026-08-31 (ver docstring de ProyectoInformeOM)."""
    version: Optional[str] = None
    elaborado_por: Optional[str] = None
    actividad: Optional[str] = None
    estado: Literal["borrador", "en_revision", "aprobado"] = "borrador"

    empresa_contratista: Optional[str] = None
    fecha_energizacion: Optional[date] = None
    fecha_inicio_operacion: Optional[date] = None
    pendientes: list[PendienteItem] = []

    checklist_fusion_solar: ChecklistFusionSolar = ChecklistFusionSolar()
    checklist_frontera: ChecklistFrontera = ChecklistFrontera()
    checklist_estacion_meteo: ChecklistEstacionMeteo = ChecklistEstacionMeteo()
    checklist_reconectador: ChecklistReconectador = ChecklistReconectador()

    objetivo_alcance: dict[str, Any] = {}
    datos_generales: dict[str, Any] = {}
    arquitectura_comunicacion: dict[str, Any] = {}
    equipos: list[Any] = []
    variables_monitoreadas: list[Any] = []
    configuracion_monitoreo: dict[str, Any] = {}
    protocolo_pruebas: list[Any] = []
    eventos_operativos: list[Any] = []
    observaciones: dict[str, Any] = {}
    recomendaciones: list[Any] = []
    conclusion: Optional[str] = None
    firmas: list[Any] = []
    evidencia_arquitectura: list[Any] = []


class InformeOMProyecto(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_comercial: str
    sub_project: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    direccion_vereda: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    fecha_entrada_operacion: Optional[date] = None


class InformeOMKpis(BaseModel):
    """Calculados sobre protocolo_pruebas/eventos_operativos + los 4
    checklist de comisionamiento, no se guardan."""
    pruebas_ejecutadas: int = 0
    pruebas_conformes: int = 0
    pruebas_no_conformes: int = 0
    eventos_total: int = 0
    eventos_cerrados: int = 0
    eventos_en_gestion: int = 0
    checklist_aprobados: int = 0
    checklist_total: int = 4
    estado_global: str = "operativo"  # "operativo" | "atencion"


class InformeOMDetail(BaseModel):
    proyecto: InformeOMProyecto
    ficha: InformeOMFicha
    kpis: InformeOMKpis

    # Leído en vivo de Solenium/Gaia -- solo lectura acá, no se guarda:
    inversores: list[Any] = []
    fusion_solar_estado: Optional[str] = None
    frontera_estado: Optional[str] = None
    estacion_meteo_estado: Optional[str] = None
    reconectador_estado: Optional[str] = None
    frontera_live: dict[str, Any] = {}
    # Evidencia ya subida en los 4 checklist + Arquitectura de este informe:
    evidencia_relacionada: list[Any] = []


class InformeOMListItem(BaseModel):
    id: int
    nombre_comercial: str
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    tiene_ficha: bool = False
    estado_global: str = "operativo"
