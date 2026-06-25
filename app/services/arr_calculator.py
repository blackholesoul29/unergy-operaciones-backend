"""
Cálculo de Arriendos — puro, sin DB ni FastAPI. Conserva la fórmula actual del
frontend: base mensual indexada por IPC con convención DANE (ipc[añoC-1]), desde
fecha_firma+1 hasta el año del período. Canon mostrado = canon_archivo ?? calculado.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
         "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _redondear(v: float) -> int:
    return int(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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
            "canon_archivo": canon_archivo, "canon_a_facturar": None,
            "difiere_archivo": False,
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
    detalle = [f"Base {año_firma}: {valor_base}"]
    for añoC in range(año_firma + 1, año_periodo + 1):
        ipc = ipc_tasas.get(añoC - 1)
        if ipc is None:
            detalle.append(f"Ene {añoC}: IPC dic {añoC - 1} no disponible")
            break
        factor *= (1.0 + ipc)
        n += 1
        pasos.append(f"IPC dic {añoC - 1}: {ipc * 100:.2f}%")
        detalle.append(f"Ene {añoC} (IPC dic {añoC - 1}: {ipc * 100:.2f}%)")

    canon_calculado = _redondear(valor_base * factor)
    canon_a_facturar = _redondear(float(canon_archivo)) if canon_archivo is not None else canon_calculado
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
        "historial_texto": " → ".join(pasos) if pasos else f"Sin indexaciones (base: {valor_base})",
        "historial_detalle": "\n".join(detalle),
    }
