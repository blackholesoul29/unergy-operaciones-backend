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

# Marca de origen de las líneas que produce este módulo. La vista muestra "ER"
# cuando la fuente viene vacía, así que sin esto los ingresos y la
# comercialización armados desde la API se veían como si salieran del Excel.
FUENTE = "api"

# La API y el Excel llaman distinto a lo mismo: "Energia en Bolsa (COP)
# (Generador)" contra "Energía en Bolsa (Gen)". Se conservan las etiquetas del
# Excel porque son las que contabilidad reconoce y las que muestra el espejo de
# Liquidaciones; cambiarlas sería ruido puro y además haría imposible contrastar
# un panel viejo contra uno nuevo.
#
# FAZNI y el cargo por confiabilidad no existen en el Excel: se nombran siguiendo
# la misma convención (Gen).
ETIQUETAS_COMERCIALIZACION = {
    "arranque_parada": "Arranque y parada",
    "arranque_parada_generador": "Arranque y parada (Gen)",
    "energia_bolsa": "Energía en Bolsa",
    "energia_bolsa_generador": "Energía en Bolsa (Gen)",
    "servicios_despacho": "Serv. Despacho CND",
    "servicios_despacho_generador": "Serv. Despacho CND (Gen)",
    "servicios_despacho_comercializador": "Serv. Despacho CND (Com)",
    "servicios_administracion": "Serv. Admin SIC",
    "servicios_administracion_generador": "Serv. Admin SIC (Gen)",
    "servicios_administracion_comercializador": "Serv. Admin SIC (Com)",
    "iva": "IVA",
    "iva_generador": "IVA Generador",
    "iva_comercializador": "IVA Comercializador",
    "fazni": "FAZNI",
    "fazni_generador": "FAZNI (Gen)",
    "cargo_confiabilidad": "Cargo por confiabilidad",
    "cargo_confiabilidad_generador": "Cargo por confiabilidad (Gen)",
    "valor_actualizacion": "Valor actualización",
}


def _etiqueta_ingreso(concepto: str, tipo: str) -> str:
    """La etiqueta del Excel para una línea de ingreso de la API.

    La API dice ``"UNERGY ENERGIA DIGITAL S.A.S ESP Venta"``; el Excel,
    ``"Ingreso Bruto Unergy Energia Digital S.A.S Esp"``. El sufijo dice el tipo
    y el resto es el comercializador, que el parser del ER capitaliza.
    """
    texto = (concepto or "").strip()
    for sufijo, plantilla in (
        (" Venta bolsa", "Venta en bolsa"),
        (" Compra", "Compra {}"),
        (" Venta", "Ingreso Bruto {}"),
    ):
        if texto.endswith(sufijo):
            comercializador = texto[: -len(sufijo)].strip().title()
            return plantilla.format(comercializador) if "{}" in plantilla else plantilla
    return texto


def _numerar_repetidos(etiquetas: list[str]) -> list[str]:
    """Numera las etiquetas que se repiten, como hace el Excel.

    Una planta con dos contratos del mismo comercializador sale en el ER como
    "Ingreso Bruto Terpel 1" y "Ingreso Bruto Terpel 2". Si solo hay una, no
    lleva número.
    """
    total: dict[str, int] = {}
    for e in etiquetas:
        total[e] = total.get(e, 0) + 1

    visto: dict[str, int] = {}
    salida = []
    for e in etiquetas:
        if total[e] == 1:
            salida.append(e)
            continue
        visto[e] = visto.get(e, 0) + 1
        salida.append(f"{e} {visto[e]}")
    return salida


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
            # Se usa la etiqueta del Excel; si aparece un concepto nuevo que no
            # esté en el mapa, se deja el nombre de la API para que se note.
            "concepto": ETIQUETAS_COMERCIALIZACION.get(
                c.get("name") or "", c.get("concepto")),
            "valor": -abs(float(c.get("valor") or 0)),
            "hoja": None,
            "celda": None,
            "fuente": FUENTE,
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

    # Base de las tarifas de servicio: la VENTA de energía, sin restar la compra.
    # `generacion_kwh` de la API viene NETA (`dispatch + dispatch_fazni − purchase`,
    # verificado al centavo en los 52 proyectos de 2026-07) y cobrar sobre ella
    # subcobraba Representación y CGM en los proyectos que compran -- 270.887 en
    # julio entre Delta 1, Naos 1 y Polaris 1. El ingreso bruto sí sigue neto: la
    # compra es plata que salió, y es lo que alimenta el espejo de Liquidaciones.
    base_kwh = round(sum(float(d.get("energia_kwh") or 0) for d in ventas), 2)
    base_cop = round(sum(float(d.get("valor") or 0) for d in ventas), 2)

    return {
        "tipo": "normal",
        "comercializador": (proyecto.get("comercializadores") or [None])[0],
        "tiene_bolsa": bool(proyecto.get("tiene_bolsa")),
        "ingreso_bruto": total_ingresos,
        "total_ingresos": total_ingresos,
        "ingresos_detalle": [
            {"concepto": etiqueta, "valor": float(d.get("valor") or 0),
             "hoja": None, "celda": None, "fuente": FUENTE}
            for d, etiqueta in zip(lineas, _numerar_repetidos(
                [_etiqueta_ingreso(d.get("concepto"), d.get("data_type")) for d in lineas]))
        ],
        "comercializacion": _comercializacion(proyecto),
        # Los costos operativos y las facturas de Unergy los pone el Panel desde
        # nuestros módulos, no la API: ver `services/costos_panel.py`.
        "costos": [],
        "facturas": [],
        # Un cero haría que Representación y CGM se calcularan en cero; None los
        # deja sin tocar, que es lo correcto cuando no hay dato de generación.
        "kwh": float(proyecto.get("generacion_kwh") or 0) or None,
        # Lo que se le cobra al proyecto sale de estas dos, no de `kwh` ni de
        # `total_ingresos`: Repre y CGM = tarifa × `base_tarifa_kwh`;
        # Administración = tarifa_admin × `base_tarifa_cop`.
        "base_tarifa_kwh": base_kwh or None,
        "base_tarifa_cop": base_cop or None,
        # El snapshot son celdas del Excel: desde la API no aplica.
        "snapshot": {},
        "warnings": avisos + [str(w) for w in (proyecto.get("warnings") or [])],
    }
