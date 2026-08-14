from datetime import date
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class InformeOMFicha(BaseModel):
    """Datos editables propios del Informe de Puesta en Marcha / O&M.

    Lo que ya vive en Inicio de Operación (fechas, inversores, frontera,
    reconectador, estación meteo, monitoreo, pendientes) NO se repite aquí;
    se lee en vivo y se expone en `InformeOMDetail`."""
    version: Optional[str] = None
    elaborado_por: Optional[str] = None
    actividad: Optional[str] = None
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
    nombre_clientes: Optional[str] = None
    sub_project: Optional[str] = None
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    direccion_vereda: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    fecha_entrada_operacion: Optional[date] = None


class InformeOMKpis(BaseModel):
    """Calculados sobre protocolo_pruebas / eventos_operativos, no se guardan."""
    pruebas_ejecutadas: int = 0
    pruebas_conformes: int = 0
    pruebas_no_conformes: int = 0
    eventos_total: int = 0
    eventos_cerrados: int = 0
    eventos_en_gestion: int = 0
    estado_global: str = "operativo"  # "operativo" | "atencion"


class InformeOMDetail(BaseModel):
    proyecto: InformeOMProyecto
    ficha: InformeOMFicha
    kpis: InformeOMKpis

    # Leído en vivo de Inicio de Operación / Solenium / Gaia -- solo lectura aquí:
    fecha_energizacion: Optional[str] = None
    fecha_inicio_operacion: Optional[str] = None
    empresa_contratista: Optional[str] = None
    inversores: list[Any] = []
    pendientes: list[Any] = []
    fusion_solar_estado: Optional[str] = None
    frontera_estado: Optional[str] = None
    estacion_meteo_estado: Optional[str] = None
    reconectador_estado: Optional[str] = None
    reconectador_live: Optional[dict[str, Any]] = None
    frontera_live: dict[str, Any] = {}
    # Evidencia ya subida en Inicio de Operación + Arquitectura de este informe:
    evidencia_relacionada: list[Any] = []


class InformeOMListItem(BaseModel):
    id: int
    nombre_comercial: str
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    tiene_ficha: bool = False
    estado_global: str = "operativo"
