"""Agregados de Monitoreo Solar: ranking y comparación XM vs. interno."""

from collections import defaultdict

from apps.energia.services import xm_solar
from apps.proyectos import models as py_models


def build_ranking(filas: list[dict], top: int) -> list[dict]:
    """Los `top` proyectos con más generación en el período filtrado.

    El promedio diario se divide por los días CON DATO, no por los del rango: un
    proyecto que reportó tres de treinta días no debe salir con un promedio
    diez veces menor que su generación real.
    """
    por_sic: dict[str, dict] = {}
    for fila in filas:
        acumulado = por_sic.setdefault(fila["sic"], {
            "sic": fila["sic"], "nombre": fila["nombre"],
            "municipio": fila["municipio"], "departamento": fila["departamento"],
            "kwh_total": 0.0, "dias": set(),
        })
        acumulado["kwh_total"] += fila["kwh"]
        acumulado["dias"].add(fila["fecha"])

    mejores = sorted(
        por_sic.values(), key=lambda a: a["kwh_total"], reverse=True
    )[:top]
    salida = []
    for acumulado in mejores:
        dias = len(acumulado["dias"])
        salida.append({
            "sic": acumulado["sic"],
            "nombre": acumulado["nombre"],
            "municipio": acumulado["municipio"],
            "departamento": acumulado["departamento"],
            "kwh_total": round(acumulado["kwh_total"], 2),
            "dias": dias,
            "kwh_dia_prom": (
                round(acumulado["kwh_total"] / dias, 2) if dias else 0.0
            ),
        })
    return salida


def build_comparacion(
    sics: str | None, ids_internos: str | None,
    fecha_ini: str | None, fecha_fin: str | None,
) -> dict:
    """Series diarias de proyectos nacionales (Excel XM) y propios (base)."""
    return {
        "nacionales": _series_nacionales(sics, fecha_ini, fecha_fin),
        "internos": _series_internas(ids_internos, fecha_ini, fecha_fin),
    }


def _series_nacionales(sics, fecha_ini, fecha_fin) -> list[dict]:
    if not sics:
        return []
    pedidos = {s.strip() for s in sics.split(",") if s.strip()}
    filas = xm_solar.filtrar_generacion(
        xm_solar.datos()["generacion"], fecha_ini=fecha_ini, fecha_fin=fecha_fin
    )

    por_sic: dict[str, dict] = {}
    for fila in filas:
        if fila["sic"] not in pedidos:
            continue
        entrada = por_sic.setdefault(
            fila["sic"], {"nombre": fila["nombre"], "diario": defaultdict(float)}
        )
        entrada["diario"][fila["fecha"]] += fila["kwh"]

    return [
        {
            "sic": sic,
            "nombre": por_sic[sic]["nombre"],
            "daily": [
                {"fecha": f, "kwh": round(v, 2)}
                for f, v in sorted(por_sic[sic]["diario"].items())
            ],
        }
        for sic in pedidos if sic in por_sic
    ]


def _series_internas(ids_internos, fecha_ini, fecha_fin) -> list[dict]:
    if not ids_internos:
        return []
    salida = []
    for crudo in ids_internos.split(","):
        crudo = crudo.strip()
        # Un id no numérico se ignora en silencio, como hoy: la lista viene de
        # una query string y un valor suelto no debe tumbar la comparación.
        if not crudo.isdigit():
            continue
        proyecto = py_models.Proyecto.objects.filter(pk=int(crudo)).first()
        if proyecto is None:
            continue

        consulta = py_models.GeneracionDiaria.objects.filter(proyecto=proyecto)
        if fecha_ini:
            consulta = consulta.filter(fecha__gte=fecha_ini)
        if fecha_fin:
            consulta = consulta.filter(fecha__lte=fecha_fin)

        salida.append({
            "id": proyecto.id,
            "nombre": proyecto.nombre_comercial,
            "daily": [
                {"fecha": str(g.fecha), "kwh": float(g.kwh_real or 0)}
                for g in consulta.order_by("fecha")
            ],
        })
    return salida
