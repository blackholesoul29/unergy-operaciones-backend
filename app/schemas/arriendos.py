"""Schemas Pydantic para el panel de Arriendos."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class ArrIPCOut(BaseModel):
    id: int; año: int; tasa: float; confirmado: bool
    fuente: Optional[str] = None
    created_at: datetime; updated_at: datetime
    model_config = {"from_attributes": True}


class ArrIPCUpsert(BaseModel):
    tasa: float; confirmado: bool = False; fuente: Optional[str] = None


class ArrProyectoIn(BaseModel):
    nombre: str
    codigo: Optional[str] = None
    fecha_firma_contrato: Optional[date] = None
    valor_base: Optional[float] = None
    activo: bool = True


class ArrProyectoOut(ArrProyectoIn):
    id: int
    model_config = {"from_attributes": True}


class ArrArrendadorIn(BaseModel):
    nombre: str
    valor_base: Optional[float] = None
    responsable_iva: bool = False
    activo: bool = True


class ArrArrendadorOut(ArrArrendadorIn):
    id: int
    contrato_id: int
    model_config = {"from_attributes": True}


class ArrCalculoFila(BaseModel):
    id: int
    proyecto: str
    codigo: Optional[str] = None
    nombre_arrendador: Optional[str] = None
    periodo: str
    mes_año: str
    habilitado: bool
    incluido: bool
    facturado: bool
    valor_base: Optional[float]
    n_indexaciones: int
    factor_acumulado: float
    valor_anual_indexado: Optional[int]
    canon_calculado: Optional[int]
    canon_a_facturar: Optional[int]
    iva_calculado: Optional[int] = None
    valor_facturado_congelado: Optional[int] = None
    ipc_incompleto: bool = False
    aplica_este_mes: bool = True
    periodicidad: Optional[str] = None
    tipo_proyecto: Optional[str] = None
    estado_contrato: str = "con_contrato"
    motivo_exclusion: Optional[str] = None
    proyecto_id: Optional[int] = None
    historial_texto: str
    historial_detalle: str


class ArrCalculoResponse(BaseModel):
    periodo: str
    filas: list[ArrCalculoFila]
    total_seleccionado: int


class ArrSeleccionItem(BaseModel):
    proyecto_id: int
    incluido: bool
    motivo_exclusion: Optional[str] = None
    arr_arrendador_id: Optional[int] = None


class ArrSeleccionGuardar(BaseModel):
    items: list[ArrSeleccionItem]


class ArrSeleccionOut(BaseModel):
    id: int
    arr_proyecto_id: Optional[int] = None
    periodo: str
    incluido: bool
    facturado: bool
    valor_facturado_congelado: Optional[int] = None
    motivo_exclusion: Optional[str] = None
    arr_arrendador_id: Optional[int] = None
    updated_at: datetime
    model_config = {"from_attributes": True}
