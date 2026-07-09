"""Schemas del módulo Balance Energético.

Consolida, por mes, la energía generada, el compromiso PPA (mínimo contractual),
el consumo de clientes y la posición neta en bolsa, y deriva el superávit/déficit
de energía del portafolio.

Nota de unidades: todas las cifras de energía se exponen en MWh. El precio de
bolsa se expone en las unidades de ``precios_bolsa_diario.precio_promedio``
(COP/kWh, misma fuente que /cumplimiento y /dashboard).
"""
from datetime import date
from pydantic import BaseModel, Field


class BalanceMensual(BaseModel):
    """Balance energético consolidado de un mes."""
    anio: int
    mes: int = Field(..., ge=1, le=12)
    # True si el mes tiene algún dato REAL (generación/consumo/bolsa/precio). Un mes
    # futuro o sin lecturas es False y sale con estado "SIN_DATOS" — no es déficit.
    realizado: bool
    # Fuentes (MWh)
    generacion_real_mwh: float
    compromiso_ppa_mwh: float
    consumo_clientes_mwh: float
    # Posición neta en bolsa = exportado − importado en fronteras de generación.
    venta_bolsa_mwh: float
    # Precio de bolsa promedio en COP/kWh (fuente precios_bolsa_diario, igual que
    # /cumplimiento y /dashboard).
    precio_bolsa_promedio_cop_kwh: float | None = None
    # Derivados
    superavit_mwh: float
    estado: str  # "SUPERAVIT" | "DEFICIT" | "NEUTRO" | "SIN_DATOS"


class BalanceResumen(BaseModel):
    """Totales acumulados año-a-fecha (solo meses realizados con dato real)."""
    generacion_total_mwh: float
    compromiso_ppa_total_mwh: float
    consumo_clientes_total_mwh: float
    venta_bolsa_total_mwh: float
    balance_acumulado_mwh: float
    # Proyección lineal a fin de año a partir del balance mensual promedio YTD.
    proyeccion_fin_anio_mwh: float | None = None
    meses_con_datos: int


class BalanceResponse(BaseModel):
    """Respuesta principal de GET /balance."""
    start_date: date
    end_date: date
    resumen: BalanceResumen
    meses: list[BalanceMensual]
