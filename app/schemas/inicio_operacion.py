from datetime import date
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict


class InicioOperacionFicha(BaseModel):
    """Datos editables de la ficha de inicio de operación."""
    empresa_contratista: Optional[str] = None
    fecha_energizacion: Optional[date] = None
    fecha_inicio_operacion: Optional[date] = None
    checklist: dict[str, Any] = {}
    pruebas: dict[str, Any] = {}
    documentos: dict[str, Any] = {}
    pendientes: list[Any] = []


class InicioOperacionProyecto(BaseModel):
    """Datos del proyecto mostrados en el encabezado de la ficha."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_comercial: str
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    direccion_vereda: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    fecha_entrada_operacion: Optional[date] = None


class InicioOperacionInversor(BaseModel):
    """Inversor del proyecto según la API de Solenium (fuente en vivo, no la
    tabla proyecto_inversores). potencia_nominal_kw es una aproximación leída
    del nombre del dispositivo -- Solenium no expone un campo de capacidad
    nominal explícito. power_kw/state son telemetría en vivo. La revisión de
    strings vive en `checklist.inversores.items`."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: Optional[str] = None
    potencia_nominal_kw: Optional[float] = None
    power_kw: Optional[float] = None
    state: Optional[str] = None


class InicioOperacionDetail(BaseModel):
    proyecto: InicioOperacionProyecto
    ficha: InicioOperacionFicha
    inversores: list[InicioOperacionInversor] = []
    # Calculados a partir del checklist, no se guardan directamente:
    fusion_solar_estado: Optional[str] = None
    frontera_estado: Optional[str] = None
    estacion_meteo_estado: Optional[str] = None
    reconectador_estado: Optional[str] = None
    progreso_pct: int = 0
    # Telemetría en vivo (Solenium / Gaia), informativa -- no se guarda:
    reconectador_live: Optional[dict[str, Any]] = None
    frontera_live: dict[str, Any] = {}


class InicioOperacionListItem(BaseModel):
    id: int
    nombre_comercial: str
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    fecha_entrada_operacion: Optional[date] = None
    tiene_ficha: bool = False
    progreso_pct: int = 0
