"""Traduce `income_statement_data` al formato que consume el Panel Contable.

El Panel se arma con ``_guardar_panel(..., parsed, ...)``, donde ``parsed`` es el
dict que hasta ahora producía ``parsear_er()`` leyendo el Excel. Este módulo
produce ese mismo dict desde la API, para que nada aguas abajo -- el reparto por
inversionista, los costos de módulos, los impuestos -- tenga que enterarse de
cuál de los dos se usó.

Es lógica pura a propósito, sin BD ni HTTP: aquí viven las reglas de negocio y
conviene poder probarlas con diccionarios.

NEU y Nitro no pasan por aquí. Su dato en la API está malo y siguen cargando el
Excel; ver ``docs/superpowers/specs/2026-08-25-panel-contable-desde-api-design.md``.
"""
from __future__ import annotations

from typing import Any

# Tópicos que legítimamente compran energía. En cualquier otro proyecto una línea
# `purchase` es un contrato mal clasificado del lado de la API: se ha visto cubrir
# exactamente los mismos kWh que la venta, dejando el ingreso bruto en negativo
# (La Paz Verso en 2026-07, ya corregido; GD Agustín 1 sigue así).
#
# Ojo con los parecidos: `delta_2`, `naos2`, `naos3` y `polaris_2` NO compran.
# Verificado contra la API el 2026-08-25.
TOPICOS_QUE_COMPRAN = frozenset({
    "naos1", "delta_1", "polaris_1", "baraya", "jerico_el_son",
    "ibirico", "mapale", "cacica", "piloneras",
})

# Tipos de línea de ingreso que suman. `purchase` se trata aparte.
TIPOS_VENTA = ("dispatch", "dispatch_fazni")


def _comercializacion(proyecto: dict[str, Any]) -> list[dict[str, Any]]:
    """Los costos de XM que reparte la API, en negativo como el resto de costos.

    Incluye ``fazni_generador`` y ``cargo_confiabilidad_generador``, que el Excel
    no trae y que en julio de 2026 suman 10,5 M de costo real. La API a veces no
    logra crear esas dos filas -- lo avisa en ``warnings``, y por eso los warnings
    se conservan tal cual: un cero ahí no significa que el cargo no exista, sino
    que no se pudo calcular.
    """
    return [
        {
            "concepto": c.get("concepto"),
            "valor": -abs(float(c.get("valor") or 0)),
            "hoja": None,
            "celda": None,
        }
        for c in (proyecto.get("comercializacion") or [])
    ]


def construir_parsed(proyecto: dict[str, Any]) -> dict[str, Any]:
    """El ``parsed`` del Panel a partir de un proyecto de ``income_statement_data``.

    ``proyecto`` es un elemento de ``results``. La estructura devuelta es la misma
    que produce ``er_loader.parsear_er``.
    """
    topico = proyecto.get("project") or ""
    detalle = proyecto.get("ingresos_detalle") or []
    avisos: list[str] = []

    ventas = [d for d in detalle if d.get("data_type") in TIPOS_VENTA]
    compras = [d for d in detalle if d.get("data_type") == "purchase"]

    # Una compra en un proyecto que no compra es un contrato mal clasificado. Se
    # deja fuera del cálculo -- restarla bajaría la administración sin que nadie
    # se entere -- pero se avisa, para que el error salga a la luz en vez de
    # quedar enterrado en un total que parece razonable.
    if compras and topico not in TOPICOS_QUE_COMPRAN:
        total_compra = sum(abs(float(d.get("valor") or 0)) for d in compras)
        avisos.append(
            f"La API reporta {len(compras)} compra(s) por {total_compra:,.0f} en un "
            f"proyecto que no compra energía. Se excluyeron del ingreso: revisar la "
            f"clasificación del contrato en la API."
        )
        compras = []

    lineas = ventas + compras
    total_ingresos = round(sum(float(d.get("valor") or 0) for d in lineas), 2)

    return {
        "tipo": "normal",
        "comercializador": (proyecto.get("comercializadores") or [None])[0],
        "tiene_bolsa": bool(proyecto.get("tiene_bolsa")),
        "ingreso_bruto": total_ingresos,
        "total_ingresos": total_ingresos,
        "ingresos_detalle": [
            {"concepto": d.get("concepto"), "valor": float(d.get("valor") or 0),
             "hoja": None, "celda": None}
            for d in lineas
        ],
        "comercializacion": _comercializacion(proyecto),
        # Los costos operativos y las facturas de Unergy los pone el Panel desde
        # nuestros módulos, no la API: ver `services/costos_panel.py`.
        "costos": [],
        "facturas": [],
        # Un cero haría que Representación y CGM se calcularan en cero; None los
        # deja sin tocar, que es lo correcto cuando no hay dato de generación.
        "kwh": float(proyecto.get("generacion_kwh") or 0) or None,
        # El snapshot son celdas del Excel: desde la API no aplica.
        "snapshot": {},
        "warnings": avisos + [str(w) for w in (proyecto.get("warnings") or [])],
    }
