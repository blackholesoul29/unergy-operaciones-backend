"""Generación diaria traída de Solenium a `generacion_diaria`.

Puerto de `_scheduled_generation_sync` de `app/main.py`, que estaba escrito
entero dentro del registro del scheduler. Corre dos veces al día (7am y 7pm).

**Ventana de 8 días y no solo ayer.** Solenium corrige hacia atrás: un día que
llegó incompleto se completa en una corrida posterior sin que nadie intervenga.
El costo es una consulta por proyecto, con la misma ventana siempre.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

from django.db.models import Q

from apps.plataforma.services.fechas import hoy_col
from apps.proyectos.models import GeneracionDiaria, Proyecto

logger = logging.getLogger("operaciones.generacion_solenium")

DIAS_VENTANA = 7
FUENTE = "solenium"


def _dias_del_proyecto(datos: dict | None) -> list[tuple[str, float]]:
    """`[(fecha, kwh)]` de la respuesta de Solenium, ya en kWh.

    La unidad viene declarada en la respuesta y puede ser kWh o MWh: se lee, no
    se asume. Se descartan los días en cero — no distinguen "no generó" de "no
    reportó", y escribir un cero pisaría un dato bueno de otra fuente.
    """
    resultados = datos.get("results") if isinstance(datos, dict) else None
    puntos = resultados.get("points") if isinstance(resultados, dict) else None
    unidad = ((resultados.get("unit") or "kWh").strip().lower()
              if isinstance(resultados, dict) else "kwh")
    factor = 1000.0 if unidad == "mwh" else 1.0

    filas: list[tuple[str, float]] = []
    if not isinstance(puntos, list):
        return filas
    for item in puntos:
        if not isinstance(item, dict):
            continue
        dia = item.get("time") or item.get("date") or item.get("day")
        val = item.get("kwh")
        if val is None:
            val = item.get("value") or item.get("energy")
        if dia and val is not None:
            kwh = float(val) * factor
            if kwh > 0:
                filas.append((str(dia)[:10], round(kwh, 3)))
    return filas


def sincronizar() -> dict:
    """Trae la ventana y la persiste. Devuelve `{proyectos, filas}`."""
    if not os.environ.get("SOLENIUM_USER") or not os.environ.get("SOLENIUM_PASS"):
        logger.info("Solenium sin credenciales — sincronización omitida")
        return {"proyectos": 0, "filas": 0}

    from app.services.mgs.solenium_client import SoleniumClient

    cliente = SoleniumClient()
    if not cliente.enabled:
        return {"proyectos": 0, "filas": 0}

    proyectos = list(
        Proyecto.objects.filter(estado="en_operacion")
        .exclude(Q(project_id_solenium__isnull=True) | Q(project_id_solenium=""))
        .values_list("id", "project_id_solenium")
    )
    if not proyectos:
        logger.info("ningún proyecto en operación con id de Solenium")
        return {"proyectos": 0, "filas": 0}

    hasta = hoy_col()
    desde = hasta - timedelta(days=DIAS_VENTANA)
    total = 0

    for proyecto_id, sol_id in proyectos:
        try:
            sol_id_int = int(sol_id)
        except (ValueError, TypeError):
            logger.warning("project_id_solenium inválido proyecto_id=%s valor=%r",
                           proyecto_id, sol_id)
            continue

        try:
            datos = cliente.get_energy(
                sol_id_int, granularity="day",
                date_from=desde.isoformat(), date_to=hasta.isoformat(),
            )
        except Exception:
            logger.exception("Solenium falló para el proyecto %s", proyecto_id)
            continue

        dias = _dias_del_proyecto(datos)
        if not dias:
            continue

        try:
            total += _persistir(proyecto_id, dias)
        except Exception:
            logger.exception("no se pudo persistir el proyecto %s", proyecto_id)

    logger.info("generación de Solenium: %d días de %d proyectos", total, len(proyectos))
    return {"proyectos": len(proyectos), "filas": total}


def _persistir(proyecto_id: int, dias: list[tuple[str, float]]) -> int:
    """UPSERT de los días de un proyecto. Devuelve cuántos escribió.

    **Solo pisa lo que ya venía de Solenium.** Un valor cargado a mano o traído
    de otra fuente manda sobre este: la condición sobre `fuente` es lo que lo
    garantiza, y estaba en el `WHERE` del ON CONFLICT original.
    """
    fechas = [f for f, _ in dias]
    existentes = dict(
        GeneracionDiaria.objects.filter(proyecto_id=proyecto_id, fecha__in=fechas)
        .values_list("fecha", "fuente")
    )

    nuevas, actualizadas = [], []
    for fecha, kwh in dias:
        fuente_actual = existentes.get(_fecha(fecha))
        if fuente_actual is None:
            nuevas.append(GeneracionDiaria(
                proyecto_id=proyecto_id, fecha=fecha, kwh_real=kwh, fuente=FUENTE))
        elif fuente_actual == FUENTE:
            actualizadas.append((fecha, kwh))

    if nuevas:
        GeneracionDiaria.objects.bulk_create(nuevas, ignore_conflicts=True)
    for fecha, kwh in actualizadas:
        GeneracionDiaria.objects.filter(
            proyecto_id=proyecto_id, fecha=fecha, fuente=FUENTE,
        ).update(kwh_real=kwh)

    return len(nuevas) + len(actualizadas)


def _fecha(texto: str):
    from datetime import date

    return date.fromisoformat(texto)
