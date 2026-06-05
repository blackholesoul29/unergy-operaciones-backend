"""Schemas Pydantic para el panel O&M."""
from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


# ── IPC ──────────────────────────────────────────────────────────────────────

class IPCTasaOut(BaseModel):
    id:         int
    año:        int
    tasa:       float
    confirmado: bool
    fuente:     Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class IPCTasaUpsert(BaseModel):
    tasa:       float
    confirmado: bool = False
    fuente:     Optional[str] = None


# ── Proyectos O&M ────────────────────────────────────────────────────────────

class OMContratoOut(BaseModel):
    """Contrato de mantenimiento con datos suficientes para el panel."""
    contrato_id:      int
    proyecto_id:      Optional[int]
    nombre_proyecto:  str
    fecha_inicio:     Optional[date]
    valor_base_anual: Optional[float]
    estado:           str


# ── Cálculo mensual ──────────────────────────────────────────────────────────

class OMCalculoFila(BaseModel):
    """Una fila de la tabla Operaciones para un período."""
    contrato_id:            int
    nombre_proyecto:        str
    periodo:                str
    mes_año:                str
    habilitado:             bool
    incluido:               bool
    facturado:              bool
    valor_base_anual:       Optional[float]
    n_indexaciones:         int
    factor_acumulado:       float
    valor_anual_indexado:   Optional[int]
    valor_mes_completo:     Optional[int]
    prorrateo_label:        str
    prorrateo_factor:       float
    valor_a_facturar:       Optional[int]
    historial_indexaciones: str


class OMCalculoResponse(BaseModel):
    periodo:            str
    filas:              list[OMCalculoFila]
    total_seleccionado: int


# ── Selección mensual ────────────────────────────────────────────────────────

class OMSeleccionItem(BaseModel):
    contrato_id: int
    incluido:    bool


class OMSeleccionGuardar(BaseModel):
    items: list[OMSeleccionItem]


class OMSeleccionOut(BaseModel):
    id:          int
    contrato_id: int
    periodo:     str
    incluido:    bool
    facturado:   bool
    updated_at:  datetime
    model_config = {"from_attributes": True}


# ── Notificaciones IPC ───────────────────────────────────────────────────────

class OMNotificacionIPC(BaseModel):
    """Notificación de cambio de valor por nueva tasa IPC."""
    año_nuevo:  int
    tasa_nueva: float
    afectados:  list[dict]
