"""
Lógica de cálculo O&M — pura, sin dependencias de DB ni FastAPI.
Todas las funciones son deterministas dado el mismo input.
"""
from __future__ import annotations
import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_periodo(periodo: str) -> tuple[int, int]:
    """'2026-06' → (2026, 6)"""
    parts = periodo.split("-")
    return int(parts[0]), int(parts[1])


def _ultimo_dia_mes(año: int, mes: int) -> int:
    return calendar.monthrange(año, mes)[1]


# ── Factor acumulado IPC ──────────────────────────────────────────────────────

def factor_acumulado(
    año_inicio: int,
    año_periodo: int,
    ipc_tasas: dict[int, float],
) -> float:
    """
    Producto de (1 + IPC_dic[año-1]) para cada año desde año_inicio+1 hasta año_periodo.

    Las tasas se almacenan con clave = año de diciembre del DANE (N).
    El incremento de enero N+1 usa ipc_tasas[N].

    Ejemplo — inicio 2024, periodo 2026, tasas {2024: 0.052, 2025: 0.051}:
      año 2025 → ipc_tasas[2024] = 0.052  → ×1.052
      año 2026 → ipc_tasas[2025] = 0.051  → ×1.051
      factor = 1.052 × 1.051 = 1.105772
    Si año_inicio >= año_periodo → factor = 1.0 (año base, sin indexación).
    """
    factor = 1.0
    for año in range(año_inicio + 1, año_periodo + 1):
        ipc = ipc_tasas.get(año - 1, 0.0)   # IPC dic del año anterior
        factor *= (1.0 + ipc)
    return factor


# ── Historial de indexaciones ────────────────────────────────────────────────

def historial_indexaciones(
    año_inicio: int,
    año_periodo: int,
    ipc_tasas: dict[int, float],
) -> str:
    """
    Devuelve string legible del historial de IPC aplicados.

    Ejemplo: "IPC dic 2024: 5.20% → IPC dic 2025: 5.10% | Acum: 10.58%"
    Si no hay indexación: "Sin indexación (año inicio)"
    """
    pasos = []
    for año in range(año_inicio + 1, año_periodo + 1):
        ipc = ipc_tasas.get(año - 1, 0.0)   # IPC dic del año anterior
        pasos.append(f"IPC dic {año - 1}: {ipc * 100:.2f}%")

    if not pasos:
        return "Sin indexación (año inicio)"

    factor = factor_acumulado(año_inicio, año_periodo, ipc_tasas)
    acum_pct = (factor - 1.0) * 100
    return " → ".join(pasos) + f" | Acum: {acum_pct:.2f}%"


# ── Prorrateo primer mes ──────────────────────────────────────────────────────

def calcular_prorrateo(
    fecha_inicio: date,
    periodo: str,
) -> tuple[str, float]:
    """
    Determina si el primer mes se cobra completo, parcial o no se cobra.

    Reglas:
    - Si el período es posterior al mes de inicio → mes completo (1.0).
    - Si el período es el mes de inicio:
        * dias_operados = días desde fecha_inicio hasta fin de mes (inclusive)
        * Si dias_operados <= 15 → "No se factura" (0.0)
        * Si dias_operados > 15  → "X/Y días" (X/Y)

    Returns:
        (label, factor) donde factor ∈ [0.0, 1.0]
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    ultimo = _ultimo_dia_mes(año_periodo, mes_periodo)
    primer_dia_periodo = date(año_periodo, mes_periodo, 1)

    # Periodo posterior al mes de inicio → completo
    if primer_dia_periodo > date(fecha_inicio.year, fecha_inicio.month, 1):
        return "Completo", 1.0

    # Mismo mes que el inicio
    if (fecha_inicio.year, fecha_inicio.month) == (año_periodo, mes_periodo):
        dias_operados = ultimo - fecha_inicio.day + 1
        if dias_operados <= 15:
            return "No se factura", 0.0
        factor = round(dias_operados / ultimo, 6)
        return f"{dias_operados}/{ultimo} días", factor

    # Periodo anterior al mes de inicio
    return "No se factura", 0.0


# ── Cálculo principal ─────────────────────────────────────────────────────────

def calcular_proyecto(
    *,
    contrato_id: int,
    nombre_proyecto: str,
    fecha_inicio: date | None,
    valor_base_anual: float | None,
    periodo: str,
    ipc_tasas: dict[int, float],
    incluido: bool = True,
    facturado: bool = False,
) -> dict:
    """
    Calcula todos los campos de la fila O&M para un contrato en un período.
    Si valor_base_anual es None o 0, el contrato se marca como deshabilitado.
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    mes_label = _mes_nombre(mes_periodo)

    tiene_valor = bool(valor_base_anual and valor_base_anual > 0)
    tiene_fecha = fecha_inicio is not None

    if not tiene_valor:
        return {
            "contrato_id": contrato_id,
            "nombre_proyecto": nombre_proyecto,
            "periodo": periodo,
            "mes_año": f"{mes_label} {año_periodo}",
            "habilitado": False,
            "incluido": False,
            "facturado": facturado,
            "valor_base_anual": None,
            "n_indexaciones": 0,
            "factor_acumulado": 1.0,
            "valor_anual_indexado": None,
            "valor_mes_completo": None,
            "prorrateo_label": "—",
            "prorrateo_factor": 0.0,
            "valor_a_facturar": None,
            "historial_indexaciones": "Sin valor base",
        }

    año_inicio = fecha_inicio.year if tiene_fecha else año_periodo
    factor = factor_acumulado(año_inicio, año_periodo, ipc_tasas)
    n_idx = max(0, año_periodo - año_inicio)

    valor_anual_indexado = valor_base_anual * factor
    valor_mes_completo   = valor_anual_indexado / 12

    if tiene_fecha:
        prorrateo_label, prorrateo_factor = calcular_prorrateo(fecha_inicio, periodo)
    else:
        prorrateo_label, prorrateo_factor = "Completo", 1.0

    valor_a_facturar = _redondear(valor_mes_completo * prorrateo_factor)

    return {
        "contrato_id":          contrato_id,
        "nombre_proyecto":      nombre_proyecto,
        "periodo":              periodo,
        "mes_año":              f"{mes_label} {año_periodo}",
        "habilitado":           True,
        "incluido":             incluido,
        "facturado":            facturado,
        "valor_base_anual":     valor_base_anual,
        "n_indexaciones":       n_idx,
        "factor_acumulado":     round(factor, 6),
        "valor_anual_indexado": _redondear(valor_anual_indexado),
        "valor_mes_completo":   _redondear(valor_mes_completo),
        "prorrateo_label":      prorrateo_label,
        "prorrateo_factor":     prorrateo_factor,
        "valor_a_facturar":     valor_a_facturar,
        "historial_indexaciones": historial_indexaciones(año_inicio, año_periodo, ipc_tasas),
    }


# ── Utilidades ────────────────────────────────────────────────────────────────

def _redondear(v: float) -> int:
    """Redondea al entero más cercano (COP no tiene decimales)."""
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mes_nombre(mes: int) -> str:
    MESES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
             "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
    return MESES[mes - 1]
