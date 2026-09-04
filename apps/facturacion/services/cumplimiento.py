"""Compromiso del PPA contra la energía realmente despachada.

Por contrato marco (PPA) se suma el despacho de TODOS sus contratos SIC y se
compara con el mínimo y el máximo del mes (`ppa_compromisos_energia`, en MWh).
El despacho viene en kWh, así que se convierte.

La energía sin PPA (bolsa / UNGC) no entra: no tiene contrato marco contra el
que comparar.
"""

from apps.ppa import models as ppa_models

# Orden en que se muestran los estados: primero lo que hay que atender.
ORDEN_ESTADO = {
    "bajo_minimo": 0, "sobre_maximo": 1, "sin_compromiso": 2, "cumple": 3,
}

# Si el despachado y el mínimo difieren en más de este factor, casi seguro que
# alguien cargó kWh donde iban MWh (o al revés). Se marca en vez de callarlo.
FACTOR_SOSPECHA = 50


def build(datos_facturacion: dict, anio: int, mes: int) -> dict:
    compromisos = {
        c.contrato_id: (
            float(c.energia_minima) if c.energia_minima is not None else None,
            float(c.energia_maxima) if c.energia_maxima is not None else None,
        )
        for c in ppa_models.PpaCompromisoEnergia.objects.filter(
            **{"año": anio, "mes": mes}
        )
    }

    grupos: dict = {}
    for linea in datos_facturacion["lineas"]:
        ppa_id = linea.get("ppa_id")
        if not ppa_id:
            continue
        grupo = grupos.setdefault(ppa_id, {
            "ppa": linea["ppa"], "numero_contrato": linea["numero_contrato"],
            "compradores": set(), "proyectos": set(), "kwh": 0.0, "contratos": 0,
        })
        grupo["kwh"] += linea["kwh"]
        grupo["contratos"] += 1
        if linea["comprador"]:
            grupo["compradores"].add(linea["comprador"])
        if linea["proyecto"]:
            grupo["proyectos"].add(linea["proyecto"])

    filas, cumplen, por_debajo = [], 0, 0
    faltante_mwh = faltante_kwh = 0.0

    for ppa_id, grupo in grupos.items():
        minimo, maximo = compromisos.get(ppa_id, (None, None))
        if minimo is None:
            continue                     # solo los PPA con mínimo cargado
        despachado = round(grupo["kwh"] / 1000.0, 2)

        if maximo and maximo > 0 and despachado > maximo:
            estado = "sobre_maximo"
        elif despachado >= minimo:
            estado = "cumple"
        else:
            estado = "bajo_minimo"
            faltante_mwh += minimo - despachado
            # El faltante en kWh se calcula exacto, no desde el MWh redondeado.
            faltante_kwh += minimo * 1000.0 - grupo["kwh"]

        if estado in ("cumple", "sobre_maximo"):
            cumplen += 1
        else:
            por_debajo += 1

        filas.append({
            "ppa": grupo["ppa"],
            "numero_contrato": grupo["numero_contrato"],
            "comprador": ", ".join(sorted(grupo["compradores"])) or None,
            "proyecto": ", ".join(sorted(grupo["proyectos"])) or None,
            "contratos": grupo["contratos"],
            "minimo_mwh": minimo,
            "maximo_mwh": maximo,
            "despachado_mwh": despachado,
            "pct": round(despachado / minimo * 100, 1) if minimo else None,
            "diferencia_mwh": round(despachado - minimo, 2),
            "faltante_kwh": (
                round(minimo * 1000.0 - grupo["kwh"], 2)
                if estado == "bajo_minimo" else 0.0
            ),
            "estado": estado,
            "unidad_sospechosa": bool(
                minimo > 0
                and (
                    despachado > minimo * FACTOR_SOSPECHA
                    or despachado < minimo / FACTOR_SOSPECHA
                )
            ),
        })

    filas.sort(
        key=lambda f: (
            ORDEN_ESTADO.get(f["estado"], 9), -(f["despachado_mwh"] or 0)
        )
    )
    return {
        "periodo": datos_facturacion["periodo"],
        "resumen": {
            "cumplen": cumplen,
            "bajo_minimo": por_debajo,
            "faltante_mwh": round(faltante_mwh, 1),
            "faltante_kwh": round(faltante_kwh, 2),
            "ppas": len(filas),
        },
        "filas": filas,
    }
