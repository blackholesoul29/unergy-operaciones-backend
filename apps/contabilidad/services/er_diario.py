"""La tabla día por día del Estado de Resultados.

El ER no es un resumen: arranca con una fila por día -- generación, importación y
venta -- y de ahí salen los totales. Se arma cruzando dos históricos de la API:

* ``market_settlements`` da la generación y la venta de cada día.
* ``disp_contracts_ftp_xm`` da el consumo por hora; la importación del día es la
  suma de sus 24 horas. Verificado contra ``agustin_2`` en 2026-07: sus 31 días
  suman 621,66, exactamente el ``importacion_kwh`` mensual que reporta la API.

Lógica pura: recibe las listas ya traídas y devuelve las filas.
"""
from __future__ import annotations

from typing import Any

TIPOS_VENTA = ("dispatch", "dispatch_fazni")


def construir_tabla_diaria(despachos: list[dict[str, Any]],
                           consumos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por día, ordenadas por fecha.

    Un día aparece si tiene generación **o** consumo: si solo se tomaran los días
    con despacho, una planta parada se vería sin importación cuando en realidad
    siguió consumiendo de la red.
    """
    filas: dict[str, dict[str, Any]] = {}

    def _fila(fecha: str) -> dict[str, Any]:
        return filas.setdefault(fecha, {
            "fecha": fecha, "generacion_kwh": 0.0,
            "importacion_kwh": 0.0, "venta_kwh": 0.0, "venta_cop": 0.0,
        })

    for d in despachos:
        # Las compras no son generación ni venta: entran al ingreso por otro lado.
        if d.get("data_type") not in TIPOS_VENTA:
            continue
        f = _fila(str(d.get("date") or "")[:10])
        energia = float(d.get("energy") or 0)
        f["generacion_kwh"] = round(f["generacion_kwh"] + energia, 2)
        f["venta_kwh"] = round(f["venta_kwh"] + energia, 2)
        f["venta_cop"] = round(f["venta_cop"] + float(d.get("price") or 0), 2)

    for c in consumos:
        f = _fila(str(c.get("date") or "")[:10])
        horas = sum(float(c.get(f"con_hour{h:02d}") or 0) for h in range(1, 25))
        f["importacion_kwh"] = round(f["importacion_kwh"] + horas, 2)

    return [filas[k] for k in sorted(filas)]
