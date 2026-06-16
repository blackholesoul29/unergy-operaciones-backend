"""Esquemas para el motor de indexación de tarifas PPA.

El cálculo es determinista a partir de las reglas del contrato
(`PPAContrato.indice_indexacion`, `periodicidad_indexacion`,
`periodo_indexacion_base`, `valor_indexacion_base`, `tarifa_base`).

Nota: la persistencia usa `PPATarifa` (columnas año/mes/tarifa); `currency` y
`applied_index` son metadatos de respuesta, no se almacenan.
"""
from __future__ import annotations

import enum
import re

from pydantic import BaseModel, Field, field_validator

_PERIODO_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class IndexType(str, enum.Enum):
    """Índices de indexación soportados.

    IPC usa el historial real (`om_ipc_tasas`). USD/DIPREM/IPP quedan como
    placeholders hasta tener su serie histórica; FIJO no indexa.
    """
    IPC = "IPC"
    IPP = "IPP"
    USD = "USD"
    DIPREM = "DIPREM"
    FIJO = "FIJO"


# Valores que en el contrato significan "sin indexación".
_FIJO_ALIASES = {"", "FIJO", "NINGUNO", "NINGUNA", "N/A", "NA", "SIN", "SIN INDEXACION"}


def normalize_index_type(raw: str | None) -> IndexType:
    """Normaliza el string libre del contrato a un `IndexType` conocido.

    Cualquier valor no reconocido se reporta como tal para que el servicio lo
    trate como placeholder (factor 1.0 + nota), sin romper el cálculo.
    """
    if raw is None:
        return IndexType.FIJO
    key = raw.strip().upper()
    if key in _FIJO_ALIASES:
        return IndexType.FIJO
    for it in IndexType:
        if it.value == key:
            return it
    # Heurísticas sobre el texto libre
    if "IPC" in key:
        return IndexType.IPC
    if "USD" in key or "DOLAR" in key or "DÓLAR" in key:
        return IndexType.USD
    if "DIPREM" in key:
        return IndexType.DIPREM
    if "IPP" in key:
        return IndexType.IPP
    raise ValueError(f"Índice de indexación no soportado: {raw!r}")


class Frequency(str, enum.Enum):
    mensual = "mensual"
    bimestral = "bimestral"
    trimestral = "trimestral"
    anual = "anual"


def normalize_frequency(raw: str | None) -> Frequency:
    if raw is None:
        return Frequency.anual
    key = raw.strip().lower()
    for f in Frequency:
        if f.value == key:
            return f
    return Frequency.anual


class IndexationRule(BaseModel):
    """Reglas de indexación derivadas de un `PPAContrato`."""
    contrato_id: int
    base_rate: float | None = Field(None, description="tarifa_base del contrato")
    index_type: IndexType = IndexType.FIJO
    frequency: Frequency = Frequency.anual
    base_period: str | None = Field(None, description="Periodo base YYYY-MM")
    base_index_value: float | None = Field(
        None, description="Valor del índice en el periodo base (series tipo USD/DIPREM)"
    )
    currency: str = "COP"
    fecha_inicio: object | None = None  # datetime.date — se valida en el servicio
    fecha_fin: object | None = None

    model_config = {"arbitrary_types_allowed": True}

    @field_validator("base_period")
    @classmethod
    def _validate_periodo(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not _PERIODO_RE.match(v.strip()):
            raise ValueError(f"base_period debe ser YYYY-MM, recibido {v!r}")
        return v.strip()

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in {"COP", "USD"}:
            raise ValueError(f"currency debe ser COP o USD, recibido {v!r}")
        return v


class TariffCalculationResult(BaseModel):
    """Una tarifa calculada para un periodo (año, mes)."""
    año: int
    mes: int
    base_rate: float
    applied_index: float | None = Field(
        None, description="Factor acumulado o valor del índice aplicado"
    )
    final_rate: float
    currency: str = "COP"
    nota: str | None = None
    degraded: bool = Field(
        False,
        description=(
            "True cuando la tarifa NO refleja una indexación completa con datos "
            "reales: falta una tasa IPC certificada de un año requerido, o el "
            "índice de serie (USD/IPP/DIPREM) aún no tiene fuente integrada y se "
            "devolvió la tarifa base. Una tarifa degraded NO debe facturarse como "
            "oficial: el motor no la persiste."
        ),
    )

    model_config = {"from_attributes": True}


class IndexationSummary(BaseModel):
    """Resultado completo de una corrida de indexación de un contrato."""
    contrato_id: int
    index_type: IndexType
    frequency: Frequency
    currency: str
    base_rate: float | None
    base_period: str | None
    periodo_desde: str | None = None
    periodo_hasta: str | None = None
    total: int = 0
    persisted: bool = False
    created: int = 0
    updated: int = 0
    degraded: bool = Field(
        False,
        description="True si AL MENOS un periodo quedó degradado (sin indexación real).",
    )
    degraded_count: int = Field(
        0, description="Número de periodos degradados (no facturables / no persistidos)."
    )
    skipped_degraded: int = Field(
        0, description="Periodos degradados que NO se persistieron en una corrida con persistencia."
    )
    tarifas: list[TariffCalculationResult] = []
