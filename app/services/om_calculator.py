"""
Lógica de cálculo O&M — pura, sin dependencias de DB ni FastAPI.
Todas las funciones son deterministas dado el mismo input.

Indexación IPC (regla vigente):
- La tabla IPC se indexa por AÑO DE APLICACIÓN directo: ipc_tasas = {año: tasa}.
  La tasa del año N se aplica a la facturación del año N.
- fecha_base = max(fecha_firma_contrato, fecha_inicio_om) si hay inicio de operación;
  si no, fecha_firma_contrato.
- añoBase = fecha_base.year, salvo la excepción de primer aniversario.
- factor = ∏ (1 + tasa) para cada año IPC tal que añoBase < año <= añoFacturación.
- Excepción primer aniversario: si fecha_firma_contrato > 1-ene-añoFacturación
  el contrato aún no cumple un año → añoBase = añoFacturación → factor = 1.0.
"""
from __future__ import annotations
import calendar
from datetime import date
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
    año_base: int,
    año_periodo: int,
    ipc_tasas: dict[int, float],
) -> float:
    """
    Producto de (1 + tasa) para cada año IPC tal que año_base < año <= año_periodo.

    Las tasas se indexan por AÑO DE APLICACIÓN directo (no por año DANE - 1).
    Ejemplo — año_base 2023, periodo 2026, tasas {2024: 0.0928, 2025: 0.052, 2026: 0.051}:
      años aplicables: 2024, 2025, 2026
      factor = 1.0928 × 1.052 × 1.051 = 1.208257
    Si año_base >= año_periodo → no hay años aplicables → factor = 1.0.
    """
    factor = 1.0
    for año, tasa in ipc_tasas.items():
        if año_base < año <= año_periodo:
            factor *= (1.0 + tasa)
    return factor


def _n_indexaciones(año_base: int, año_periodo: int, ipc_tasas: dict[int, float]) -> int:
    return sum(1 for año in ipc_tasas if año_base < año <= año_periodo)


# ── Historial de indexaciones ────────────────────────────────────────────────

def historial_indexaciones(
    año_base: int,
    año_periodo: int,
    ipc_tasas: dict[int, float],
) -> str:
    """
    String legible del historial de IPC aplicados.

    Ejemplo: "IPC 2025: 5.20% → IPC 2026: 5.10% | Acum: 10.57%"
    Si no hay indexación: "Sin indexación (aún no cumple un año)"
    """
    años = sorted(a for a in ipc_tasas if año_base < a <= año_periodo)
    if not años:
        return "Sin indexación (aún no cumple un año)"
    pasos = [f"IPC {a}: {ipc_tasas[a] * 100:.2f}%" for a in años]
    factor = factor_acumulado(año_base, año_periodo, ipc_tasas)
    return " → ".join(pasos) + f" | Acum: {(factor - 1.0) * 100:.2f}%"


# ── Prorrateo primer mes ──────────────────────────────────────────────────────

def calcular_prorrateo(
    fecha_operacion: date,
    periodo: str,
) -> tuple[str, float]:
    """
    Determina si el mes se cobra completo, parcial o no se cobra, según la
    fecha de inicio de operación.

    Reglas:
    - Si el período es posterior al mes de inicio → mes completo (1.0).
    - Si el período es el mes de inicio:
        * dias_operados = días desde fecha_operacion hasta fin de mes (inclusive)
        * Si dias_operados <= 15 → "No se factura" (0.0)
        * Si dias_operados > 15  → "X/Y días" (X/Y)

    Returns:
        (label, factor) donde factor ∈ [0.0, 1.0]
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    ultimo = _ultimo_dia_mes(año_periodo, mes_periodo)
    primer_dia_periodo = date(año_periodo, mes_periodo, 1)

    # Periodo posterior al mes de inicio → completo
    if primer_dia_periodo > date(fecha_operacion.year, fecha_operacion.month, 1):
        return "Completo", 1.0

    # Mismo mes que el inicio
    if (fecha_operacion.year, fecha_operacion.month) == (año_periodo, mes_periodo):
        dias_operados = ultimo - fecha_operacion.day + 1
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
    fecha_firma_contrato: date | None,
    fecha_inicio_om: date | None,
    valor_base_anual: float | None,
    periodo: str,
    ipc_tasas: dict[int, float],
    incluido: bool = True,
    facturado: bool = False,
    valor_manual: float | None = None,
) -> dict:
    """
    Calcula todos los campos de la fila O&M para un contrato en un período.

    Requiere `valor_base_anual` y `fecha_firma_contrato`; si falta alguno, la fila
    se marca deshabilitada (advertencia en UI) y no se factura.
    """
    año_periodo, mes_periodo = _parse_periodo(periodo)
    mes_label = _mes_nombre(mes_periodo)

    def _deshabilitada(historial: str) -> dict:
        return {
            "contrato_id": contrato_id,
            "nombre_proyecto": nombre_proyecto,
            "periodo": periodo,
            "mes_año": f"{mes_label} {año_periodo}",
            "habilitado": False,
            "incluido": False,
            "facturado": facturado,
            "valor_base_anual": valor_base_anual,
            "n_indexaciones": 0,
            "factor_acumulado": 1.0,
            "valor_anual_indexado": None,
            "valor_mes_completo": None,
            "prorrateo_label": "—",
            "prorrateo_factor": 0.0,
            "valor_calculado": None,
            "editado_manual": False,
            "valor_a_facturar": None,
            "historial_indexaciones": historial,
        }

    tiene_valor = bool(valor_base_anual and valor_base_anual > 0)
    if not tiene_valor:
        return _deshabilitada("Sin valor base")
    if fecha_firma_contrato is None:
        return _deshabilitada("Sin fecha de suscripción")

    # ── Fecha base ────────────────────────────────────────────────────────────
    if fecha_inicio_om is not None:
        fecha_base = max(fecha_firma_contrato, fecha_inicio_om)
    else:
        fecha_base = fecha_firma_contrato

    # Excepción primer aniversario: si la firma es posterior al 1-ene del año de
    # facturación, el contrato aún no cumple un año → no se indexa este año.
    primer_dia_año = date(año_periodo, 1, 1)
    no_ha_cumplido_un_año = fecha_firma_contrato > primer_dia_año
    año_base = año_periodo if no_ha_cumplido_un_año else fecha_base.year

    factor = factor_acumulado(año_base, año_periodo, ipc_tasas)
    n_idx = _n_indexaciones(año_base, año_periodo, ipc_tasas)

    valor_anual_indexado = valor_base_anual * factor
    valor_mes_completo = valor_anual_indexado / 12

    # Prorrateo sobre el inicio de operación real (si existe), si no la firma.
    fecha_operacion = fecha_inicio_om if fecha_inicio_om is not None else fecha_firma_contrato
    prorrateo_label, prorrateo_factor = calcular_prorrateo(fecha_operacion, periodo)

    valor_calculado = _redondear(valor_mes_completo * prorrateo_factor)
    editado_manual = valor_manual is not None
    valor_a_facturar = _redondear(float(valor_manual)) if editado_manual else valor_calculado

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
        "valor_calculado":      valor_calculado,
        "editado_manual":       editado_manual,
        "valor_a_facturar":     valor_a_facturar,
        "historial_indexaciones": historial_indexaciones(año_base, año_periodo, ipc_tasas),
    }


# ── Utilidades ────────────────────────────────────────────────────────────────

def _redondear(v: float) -> int:
    """Redondea al entero más cercano (COP no tiene decimales)."""
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _mes_nombre(mes: int) -> str:
    MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    return MESES[mes - 1]
