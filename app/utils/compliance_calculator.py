"""Cálculo de cumplimiento de generación y liquidación automática.

Regla de negocio:

    Valor Liquidación (COP) = Energía Generada (kWh) × Precio Bolsa (COP/kWh)

El precio se obtiene vía :class:`~app.utils.xm_price_mapper.XMPriceMapper`. El
umbral de cumplimiento es opcional: si el contrato define uno se compara contra
la energía; si no, se asume cumplimiento cuando hay generación (> 0). Sin
generación (o sin precio disponible) no se genera liquidación.

Unidades: se trabaja consistentemente en kWh y COP/kWh (las columnas reales de
`precios_bolsa_diario.precio_promedio` y `generacion_diaria.kwh_real`). Un valor
expresado en MWh × COP/MWh produce el mismo resultado numérico.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.utils.xm_price_mapper import FUENTE_NINGUNA, XMPriceMapper

# Estados de cumplimiento
CUMPLE = "cumple"
NO_CUMPLE = "no_cumple"
SIN_PRECIO = "sin_precio"


@dataclass
class ResultadoLiquidacion:
    """Detalle estructurado de una liquidación calculada automáticamente."""

    cumple: bool
    estado_cumplimiento: str
    energia_kwh: float
    precio_aplicado: Optional[float]
    fuente_precio: str
    valor_bruto_cop: float
    desglose: dict = field(default_factory=dict)


def calcular_liquidacion(
    energia_kwh,
    precio_cop_kwh,
    fuente_precio,
    umbral_kwh: float = 0.0,
) -> ResultadoLiquidacion:
    """Evalúa cumplimiento y calcula el valor bruto (función pura, testeable).

    - Sin generación (energía <= 0) → no cumple, valor 0.
    - Con umbral > 0 y energía < umbral → no cumple, valor 0.
    - Cumple pero sin precio válido → estado ``sin_precio``, valor 0.
    - Cumple con precio → valor = energía × precio.
    """
    energia = float(energia_kwh or 0.0)
    umbral = float(umbral_kwh or 0.0)

    if energia <= 0:
        return ResultadoLiquidacion(
            cumple=False,
            estado_cumplimiento=NO_CUMPLE,
            energia_kwh=round(energia, 3),
            precio_aplicado=None,
            fuente_precio=FUENTE_NINGUNA,
            valor_bruto_cop=0.0,
            desglose={"motivo": "sin_generacion", "umbral_kwh": umbral},
        )

    if umbral > 0 and energia < umbral:
        return ResultadoLiquidacion(
            cumple=False,
            estado_cumplimiento=NO_CUMPLE,
            energia_kwh=round(energia, 3),
            precio_aplicado=None,
            fuente_precio=FUENTE_NINGUNA,
            valor_bruto_cop=0.0,
            desglose={"motivo": "bajo_umbral", "umbral_kwh": umbral},
        )

    precio = None if precio_cop_kwh is None else float(precio_cop_kwh)
    if precio is None or precio <= 0:
        return ResultadoLiquidacion(
            cumple=True,
            estado_cumplimiento=SIN_PRECIO,
            energia_kwh=round(energia, 3),
            precio_aplicado=None,
            fuente_precio=fuente_precio or FUENTE_NINGUNA,
            valor_bruto_cop=0.0,
            desglose={"motivo": "precio_no_disponible", "umbral_kwh": umbral},
        )

    valor = round(energia * precio, 2)
    return ResultadoLiquidacion(
        cumple=True,
        estado_cumplimiento=CUMPLE,
        energia_kwh=round(energia, 3),
        precio_aplicado=round(precio, 6),
        fuente_precio=fuente_precio,
        valor_bruto_cop=valor,
        desglose={
            "formula": "energia_kwh * precio_cop_kwh",
            "energia_kwh": round(energia, 3),
            "precio_cop_kwh": round(precio, 6),
            "umbral_kwh": umbral,
        },
    )


class ComplianceCalculator:
    """Combina generación + :class:`XMPriceMapper` para liquidar automáticamente."""

    def __init__(self, price_mapper: XMPriceMapper):
        self._pm = price_mapper

    def evaluar_mes(
        self, energia_kwh, year, month, umbral_kwh: float = 0.0, plant_id=None
    ) -> ResultadoLiquidacion:
        precio, fuente = self._pm.get_month_average(year, month, plant_id=plant_id)
        return calcular_liquidacion(energia_kwh, precio, fuente, umbral_kwh)

    def evaluar_dia(
        self, energia_kwh, fecha, umbral_kwh: float = 0.0, plant_id=None
    ) -> ResultadoLiquidacion:
        precio, fuente = self._pm.get_price_for_date(fecha, plant_id=plant_id)
        return calcular_liquidacion(energia_kwh, precio, fuente, umbral_kwh)
