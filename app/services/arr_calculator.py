"""
Cálculo de Arriendos — puro, sin DB ni FastAPI. Base mensual indexada por IPC
con convención DANE (ipc[año-1]), aplicada en el ANIVERSARIO real del contrato
(no cada enero calendario): en el aniversario del año Y se aplica ipc[Y-1], y un
aniversario solo cuenta si ya ocurrió al último día del período facturado.
Canon mostrado = canon_archivo ?? calculado.
"""
from __future__ import annotations
import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _redondear(v: float) -> int:
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ultimo_dia_mes(año: int, mes: int) -> int:
    return calendar.monthrange(año, mes)[1]


def _fecha_aniversario(fecha_base: date, k: int) -> date:
    """k-ésimo aniversario de fecha_base (mismo mes/día; clamp 29-feb → 28-feb)."""
    año = fecha_base.year + k
    mes = fecha_base.month
    dia = min(fecha_base.day, _ultimo_dia_mes(año, mes))
    return date(año, mes, dia)


def _aniversarios_cumplidos(fecha_base: date, año_periodo: int, mes_periodo: int) -> list[date]:
    """Aniversarios (fecha_base + k años) ya alcanzados al último día del período."""
    ultimo_dia_periodo = date(año_periodo, mes_periodo, _ultimo_dia_mes(año_periodo, mes_periodo))
    aniversarios: list[date] = []
    k = 1
    while True:
        fecha_aniv = _fecha_aniversario(fecha_base, k)
        if fecha_aniv > ultimo_dia_periodo:
            return aniversarios
        aniversarios.append(fecha_aniv)
        k += 1


def calcular_arriendo(
    *,
    proyecto_id: int,
    nombre: str,
    codigo: str | None,
    fecha_firma_contrato: date | None,
    valor_base: float | None,
    canon_archivo: float | None,
    periodo: str,
    ipc_tasas: dict[int, float],
    incluido: bool = True,
    facturado: bool = False,
    valor_congelado: int | None = None,
) -> dict:
    año_periodo = int(periodo.split("-")[0])
    mes = int(periodo.split("-")[1])
    mes_label = MESES[mes - 1]

    def deshabilitada(historial: str) -> dict:
        return {
            "id": proyecto_id, "proyecto": nombre, "codigo": codigo,
            "periodo": periodo, "mes_año": f"{mes_label} {año_periodo}",
            "habilitado": False, "incluido": False, "facturado": facturado,
            "valor_base": valor_base, "n_indexaciones": 0, "factor_acumulado": 1.0,
            "valor_anual_indexado": None, "canon_calculado": None,
            "canon_archivo": _redondear(float(canon_archivo)) if canon_archivo is not None else None,
            "canon_a_facturar": None,
            "difiere_archivo": False,
            "valor_facturado_congelado": int(valor_congelado) if valor_congelado is not None else None,
            "ipc_incompleto": False,
            "historial_texto": historial, "historial_detalle": historial,
        }

    if not (valor_base and valor_base > 0):
        return deshabilitada("Sin valor base")
    if fecha_firma_contrato is None:
        return deshabilitada("Sin fecha de firma")

    año_firma = fecha_firma_contrato.year
    factor = 1.0
    n = 0
    pasos = []
    ipc_incompleto = False
    detalle = [f"Base {año_firma}: {valor_base}"]
    # Indexar en cada aniversario cumplido del contrato (no cada enero calendario).
    # Convención DANE: en el aniversario del año Y se aplica ipc[Y-1].
    for fecha_aniv in _aniversarios_cumplidos(fecha_firma_contrato, año_periodo, mes):
        año_aniv = fecha_aniv.year
        ipc = ipc_tasas.get(año_aniv - 1)
        if ipc is None:
            # Falta la tasa de ese año: se marca la fila como incompleta (aviso en UI).
            # Se detiene aquí para no aplicar años posteriores sin la tasa intermedia.
            ipc_incompleto = True
            detalle.append(f"Aniversario {año_aniv}: IPC dic {año_aniv - 1} no disponible")
            break
        factor *= (1.0 + ipc)
        n += 1
        pasos.append(f"IPC dic {año_aniv - 1}: {ipc * 100:.2f}%")
        detalle.append(f"Aniversario {fecha_aniv.isoformat()} (IPC dic {año_aniv - 1}: {ipc * 100:.2f}%)")

    canon_calculado = _redondear(valor_base * factor)
    canon_a_facturar = _redondear(float(canon_archivo)) if canon_archivo is not None else canon_calculado
    if valor_congelado is not None:
        canon_a_facturar = int(valor_congelado)   # mes ya facturado → canon congelado
    difiere = (
        canon_archivo is not None
        and abs(canon_calculado - float(canon_archivo)) / max(abs(float(canon_archivo)), 1) > 0.001
    )

    return {
        "id": proyecto_id, "proyecto": nombre, "codigo": codigo,
        "periodo": periodo, "mes_año": f"{mes_label} {año_periodo}",
        "habilitado": True, "incluido": incluido, "facturado": facturado,
        "valor_base": valor_base, "n_indexaciones": n,
        "factor_acumulado": round(factor, 6),
        "valor_anual_indexado": _redondear(canon_calculado * 12),
        "canon_calculado": canon_calculado,
        "canon_archivo": _redondear(float(canon_archivo)) if canon_archivo is not None else None,
        "canon_a_facturar": canon_a_facturar,
        "difiere_archivo": difiere,
        "valor_facturado_congelado": int(valor_congelado) if valor_congelado is not None else None,
        "ipc_incompleto": ipc_incompleto,
        "historial_texto": " → ".join(pasos) if pasos else f"Sin indexaciones (base: {valor_base})",
        "historial_detalle": "\n".join(detalle),
    }
