"""
Motor de cálculo de liquidaciones — puro, sin dependencias de DB ni FastAPI.
Todas las funciones son deterministas dado el mismo input.

Regla de tarifa (la que aplica el auto-poblado de datos XM):
- tipo_venta == "ppa" y hay tarifa PPA vigente para el período → se usa la tarifa PPA.
- En cualquier otro caso (bolsa/interno/autoconsumo, o PPA sin tarifa cargada para
  ese mes) → se usa el promedio del precio de bolsa del período.
- Si no hay ninguna de las dos, NO hay tarifa: el llamador debe abortar en vez de
  liquidar a $0 (ver `TarifaNoResuelta`).

Unidades: energía en kWh, tarifa en COP/kWh, valor en COP.
`precios_bolsa_diario.precio_promedio` ya está en COP/kWh (igual que lo expone
dashboard como `precio_bolsa_cop_kwh`), así que no hay conversión MWh→kWh aquí.
"""
from __future__ import annotations
from dataclasses import dataclass


class TarifaNoResuelta(Exception):
    """No hay tarifa PPA ni precio de bolsa para el período: no se puede liquidar."""


@dataclass(frozen=True)
class CalculoXM:
    energia_kwh: float
    tarifa_kwh: float
    origen_tarifa: str  # "ppa" | "bolsa"
    valor_bruto_cop: float


def resolver_tarifa(
    tipo_venta: str | None,
    tarifa_ppa: float | None,
    precio_bolsa: float | None,
) -> tuple[float, str]:
    """Decide qué tarifa (COP/kWh) aplica y de dónde salió.

    Una tarifa de 0 se trata como "no hay tarifa": liquidar energía a $0 sería un
    dato financiero silenciosamente incorrecto, no un caso válido.
    """
    if tipo_venta == "ppa" and tarifa_ppa:
        return float(tarifa_ppa), "ppa"
    if precio_bolsa:
        return float(precio_bolsa), "bolsa"
    raise TarifaNoResuelta(
        "No hay tarifa PPA cargada para el período ni precio de bolsa registrado; "
        "cargue la tarifa del contrato PPA o los precios de bolsa del mes."
    )


def calcular_xm(
    energia_kwh: float,
    tipo_venta: str | None,
    tarifa_ppa: float | None = None,
    precio_bolsa: float | None = None,
) -> CalculoXM:
    """Calcula el dato XM de una liquidación: energía × tarifa = valor bruto.

    Redondeos alineados con las columnas de `liquidacion_xm_datos`:
    energia_kwh Numeric(14,3), tarifa_aplicada_kwh Numeric(12,6), valor_bruto_cop Numeric(18,2).
    """
    tarifa, origen = resolver_tarifa(tipo_venta, tarifa_ppa, precio_bolsa)
    return CalculoXM(
        energia_kwh=round(float(energia_kwh), 3),
        tarifa_kwh=round(tarifa, 6),
        origen_tarifa=origen,
        valor_bruto_cop=round(float(energia_kwh) * tarifa, 2),
    )
