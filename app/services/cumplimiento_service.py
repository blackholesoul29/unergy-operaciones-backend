"""Valoración del déficit de cumplimiento PPA.

Cuando un contrato genera menos de lo comprometido, el faltante hay que cubrirlo.
Hasta ahora el impacto siempre se estimaba a precio de bolsa, pero muchos PPA
traen una penalidad contractual por MWh no entregado: si esa penalidad supera el
precio de bolsa, valorar a bolsa subestima el golpe real. `tipo_precio_referencia`
del contrato decide qué precio manda.

UNIDADES (la trampa de este módulo): `precio_penalidad_mwh` está en COP/MWh, pero
`cumplimiento_mensual.precio_bolsa_promedio` (y todo lo que viene de XM) está en
COP/kWh. Comparar los dos crudos siempre elegiría la penalidad — es ~1000x más
grande por unidades, no por ser más cara. Todo se normaliza a COP/MWh antes de
comparar.
"""
from dataclasses import dataclass

# Fuente del precio finalmente aplicado (lo que la UI le muestra al usuario).
FUENTE_BOLSA = "BOLSA"
FUENTE_PENALIDAD = "PENALIDAD_CONTRACTUAL"

# Valores válidos de ppa_contratos.tipo_precio_referencia.
TIPO_HIBRIDO = "HIBRIDO"
TIPO_PENALIDAD = "PENALIDAD_CONTRACTUAL"
TIPO_BOLSA = "PRECIO_BOLSA"
TIPOS_PRECIO_REFERENCIA = (TIPO_HIBRIDO, TIPO_PENALIDAD, TIPO_BOLSA)

KWH_POR_MWH = 1000


@dataclass(frozen=True)
class ImpactoDeficit:
    """Impacto en COP del déficit y el precio con que se valoró."""
    impacto_cop: float | None
    precio_aplicado_mwh: float | None
    fuente_precio: str | None


def calcular_impacto_deficit(
    deficit_mwh: float | None,
    contrato,
    precio_bolsa_cop_kwh: float | None,
) -> ImpactoDeficit:
    """Valora un déficit de `deficit_mwh` MWh según el contrato PPA.

    `precio_bolsa_cop_kwh` viene en COP/kWh (unidad de XM y de
    `cumplimiento_mensual.precio_bolsa_promedio`); se normaliza a COP/MWh.

    Sin precio aplicable (p. ej. PENALIDAD_CONTRACTUAL sin penalidad cargada y
    sin bolsa) no se inventa un número: devuelve todo en None, igual que antes
    hacía la alerta cuando faltaba el precio de bolsa.
    """
    if deficit_mwh is None:
        return ImpactoDeficit(None, None, None)

    penalidad_mwh = _a_float(getattr(contrato, "precio_penalidad_mwh", None))
    bolsa_kwh = _a_float(precio_bolsa_cop_kwh)
    bolsa_mwh = bolsa_kwh * KWH_POR_MWH if bolsa_kwh is not None else None

    tipo = (getattr(contrato, "tipo_precio_referencia", None) or TIPO_HIBRIDO).upper()

    if tipo == TIPO_BOLSA:
        precio_mwh, fuente = bolsa_mwh, FUENTE_BOLSA
    elif tipo == TIPO_PENALIDAD:
        # Fallback a bolsa: un contrato marcado como penalidad pero sin el valor
        # cargado todavía no puede quedarse sin estimación.
        if penalidad_mwh is not None:
            precio_mwh, fuente = penalidad_mwh, FUENTE_PENALIDAD
        else:
            precio_mwh, fuente = bolsa_mwh, FUENTE_BOLSA
    else:
        # HIBRIDO (y cualquier valor desconocido, por seguridad): el que más duela.
        if penalidad_mwh is not None and bolsa_mwh is not None:
            usa_penalidad = penalidad_mwh >= bolsa_mwh
            precio_mwh = penalidad_mwh if usa_penalidad else bolsa_mwh
            fuente = FUENTE_PENALIDAD if usa_penalidad else FUENTE_BOLSA
        elif penalidad_mwh is not None:
            precio_mwh, fuente = penalidad_mwh, FUENTE_PENALIDAD
        else:
            precio_mwh, fuente = bolsa_mwh, FUENTE_BOLSA

    if precio_mwh is None:
        return ImpactoDeficit(None, None, None)

    return ImpactoDeficit(
        impacto_cop=round(deficit_mwh * precio_mwh, 0),
        precio_aplicado_mwh=precio_mwh,
        fuente_precio=fuente,
    )


def _a_float(valor) -> float | None:
    """Numeric de SQLAlchemy llega como Decimal; None se propaga."""
    return float(valor) if valor is not None else None
