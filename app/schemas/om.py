"""Schemas Pydantic para el panel O&M."""
from __future__ import annotations
from pydantic import BaseModel, Field
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
    tasa:       float = Field(ge=-1.0, le=1.0)   # fracción: -100%..100% (tope de sanidad)
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
    valor_calculado:        Optional[int]
    editado_manual:         bool
    valor_facturado_congelado: Optional[int] = None   # #4: valor fijo cuando el mes está facturado
    aplica_este_mes:        bool = True   # False = no le toca cobro este mes (por periodicidad)
    valor_manual_desactualizado: bool = False   # el override ya no coincide con el valor recalculado
    historial_indexaciones: str
    ipc_incompleto:         bool = False   # algún aniversario cayó en un año sin tasa IPC cargada
    documento_disponible:   bool = False   # PDF individual disponible para este proyecto
    documento_nombre:       Optional[str] = None   # nombre del archivo renombrado


class OMCalculoResponse(BaseModel):
    periodo:            str
    filas:              list[OMCalculoFila]
    total_seleccionado: int


# ── Selección mensual ────────────────────────────────────────────────────────

class OMSeleccionItem(BaseModel):
    contrato_id:  int
    incluido:     bool
    valor_manual: Optional[float] = None
    motivo_exclusion: Optional[str] = None   # #6: requerido por la UI al excluir uno que aplica


class OMSeleccionGuardar(BaseModel):
    items: list[OMSeleccionItem]


class OMSeleccionOut(BaseModel):
    id:          int
    contrato_id: int
    periodo:     str
    incluido:    bool
    facturado:    bool
    valor_manual: Optional[float] = None
    motivo_exclusion: Optional[str] = None
    updated_at:   datetime
    model_config = {"from_attributes": True}


# ── Páginas sin match (asignación manual) ───────────────────────────────────

class OMPaginaSinMatchOut(BaseModel):
    id:              int
    periodo:         str
    pagina:          int
    nombre_extraido: Optional[str] = None
    estrategia:      Optional[str] = None
    razon:           str
    numero_factura:  Optional[str] = None
    muestra_texto:   Optional[str] = None
    origen:          str
    model_config = {"from_attributes": True}


class OMSinMatchAsignar(BaseModel):
    contrato_id: int


# ── Notificaciones IPC ───────────────────────────────────────────────────────

class OMNotificacionIPC(BaseModel):
    """Notificación de cambio de valor por nueva tasa IPC."""
    año_nuevo:  int
    tasa_nueva: float
    afectados:  list[dict]
