"""Mapeo de precios de bolsa (`precios_bolsa_diario`) para liquidaciones automáticas.

La tabla `precios_bolsa_diario` guarda el precio promedio diario del mercado en
COP/kWh (columna `precio_promedio`, poblada por el proxy EVO — ver
`app/api/v1/evo_proxy.py`). Este módulo resuelve el precio a aplicar para una
fecha o mes con una cadena de *fallback*:

    precio del día  →  último precio disponible anterior  →  precio base de contrato

y expone la fuente elegida para dar trazabilidad (transparencia requerida por los
socios GEO) al valor liquidado.

Nota de diseño: no se usa `functools.lru_cache` porque enlazarlo a métodos de
instancia mantiene vivas las sesiones de BD y comparte caché entre sesiones. En
su lugar cada `XMPriceMapper` lleva un caché de instancia (dict) que evita
consultas SQL redundantes durante el cálculo de liquidaciones masivas y muere
con la instancia.
"""
from __future__ import annotations

from decimal import Decimal
from typing import NamedTuple, Optional

from sqlalchemy import text

# Fuentes posibles del precio aplicado (para trazabilidad)
FUENTE_DIARIO = "bolsa_diario"      # precio de bolsa del día exacto
FUENTE_FALLBACK = "bolsa_fallback"  # último precio de bolsa anterior disponible
FUENTE_MES = "bolsa_mes"            # promedio mensual de bolsa
FUENTE_BASE = "contrato_base"       # precio base de contrato (parámetro)
FUENTE_NINGUNA = "sin_precio"       # no se pudo resolver ningún precio


class PrecioResuelto(NamedTuple):
    precio: Optional[Decimal]
    fuente: str


def _a_decimal_positivo(valor) -> Optional[Decimal]:
    """Normaliza a Decimal solo si es un precio válido (> 0); si no, None."""
    if valor is None:
        return None
    try:
        dec = Decimal(str(valor))
    except (ArithmeticError, ValueError):
        return None
    return dec if dec > 0 else None


def seleccionar_precio(precio_dia, precio_anterior, precio_base) -> PrecioResuelto:
    """Elige precio + fuente dada la cadena de candidatos (función pura, testeable).

    Cada candidato se descarta si es None o <= 0. Devuelve el primero válido en
    orden de prioridad (día → anterior → base), o (None, FUENTE_NINGUNA).
    """
    for valor, fuente in (
        (precio_dia, FUENTE_DIARIO),
        (precio_anterior, FUENTE_FALLBACK),
        (precio_base, FUENTE_BASE),
    ):
        dec = _a_decimal_positivo(valor)
        if dec is not None:
            return PrecioResuelto(dec, fuente)
    return PrecioResuelto(None, FUENTE_NINGUNA)


class XMPriceMapper:
    """Recupera precios de bolsa desde `precios_bolsa_diario` con fallback y caché.

    Args:
        db: sesión SQLAlchemy activa.
        precio_base: precio de contrato a usar como último recurso (COP/kWh).
    """

    def __init__(self, db, precio_base: Optional[float] = None):
        self._db = db
        self._precio_base = precio_base
        self._cache: dict = {}

    # ── Consultas SQL (aisladas para poder probar la lógica por separado) ──────
    def _precio_exacto(self, fecha):
        row = self._db.execute(
            text(
                """
                SELECT precio_promedio FROM precios_bolsa_diario
                WHERE fecha = :fecha AND precio_promedio IS NOT NULL
                LIMIT 1
                """
            ),
            {"fecha": fecha},
        ).first()
        return row.precio_promedio if row else None

    def _precio_anterior(self, fecha):
        row = self._db.execute(
            text(
                """
                SELECT precio_promedio FROM precios_bolsa_diario
                WHERE fecha <= :fecha AND precio_promedio IS NOT NULL
                ORDER BY fecha DESC LIMIT 1
                """
            ),
            {"fecha": fecha},
        ).first()
        return row.precio_promedio if row else None

    def _promedio_mes(self, year, month):
        row = self._db.execute(
            text(
                """
                SELECT AVG(precio_promedio) AS avg_precio FROM precios_bolsa_diario
                WHERE EXTRACT(YEAR FROM fecha) = :year
                  AND EXTRACT(MONTH FROM fecha) = :month
                  AND precio_promedio IS NOT NULL
                """
            ),
            {"year": year, "month": month},
        ).first()
        return row.avg_precio if row else None

    # ── API pública ──────────────────────────────────────────────────────────
    def get_price_for_date(self, fecha, plant_id=None) -> PrecioResuelto:
        """Precio de bolsa (COP/kWh) para una fecha, con fallback y trazabilidad.

        `plant_id` se acepta por compatibilidad de firma; el precio de bolsa es
        del sistema (no por planta), por lo que no altera el resultado.
        """
        key = ("d", fecha)
        if key in self._cache:
            return self._cache[key]
        resultado = seleccionar_precio(
            self._precio_exacto(fecha),
            self._precio_anterior(fecha),
            self._precio_base,
        )
        self._cache[key] = resultado
        return resultado

    def get_month_average(self, year, month, plant_id=None) -> PrecioResuelto:
        """Promedio mensual de bolsa (COP/kWh) con fallback al precio base.

        Es el valor usado por las liquidaciones (cuyo período es mensual).
        """
        key = ("m", year, month)
        if key in self._cache:
            return self._cache[key]
        avg = _a_decimal_positivo(self._promedio_mes(year, month))
        if avg is not None:
            resultado = PrecioResuelto(avg, FUENTE_MES)
        else:
            base = _a_decimal_positivo(self._precio_base)
            resultado = (
                PrecioResuelto(base, FUENTE_BASE)
                if base is not None
                else PrecioResuelto(None, FUENTE_NINGUNA)
            )
        self._cache[key] = resultado
        return resultado
