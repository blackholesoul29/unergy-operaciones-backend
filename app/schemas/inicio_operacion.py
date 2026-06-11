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


class InicioOperacionDetail(BaseModel):
    proyecto: InicioOperacionProyecto
    ficha: InicioOperacionFicha


class InicioOperacionListItem(BaseModel):
    id: int
    nombre_comercial: str
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    potencia_instalada_kwp: Optional[float] = None
    fecha_entrada_operacion: Optional[date] = None
    tiene_ficha: bool = False
    progreso_pct: int = 0
