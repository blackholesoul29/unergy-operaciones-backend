"""Alarmas de comunicación derivadas del reporte estructurado de fallas.

Puerto de `app/services/fallas/alarmas.py`.

Reglas (extensibles sin tocar la clasificación de fallas):

  - Pérdida de comunicación de la frontera   → `comunicacion_frontera`
  - Pérdida de comunicación de ≥1 inversor   → `comunicacion_inversores`
  - Ambas simultáneas —en la misma falla o en fallas activas del mismo
    proyecto—                                → `comunicacion_total` (crítica)

Entrega: notificaciones in-app a los roles admin/operaciones/monitoreo, con
anti-spam vía `alarma_estado` (ver `apps/monitoreo/services/alarmas/estado.py`).
El hook en `POST /fallas` va envuelto en try/except: nunca debe romper la
creación de la falla.

**Evalúa las 3 categorías en CADA llamada**, activas y ya resueltas, no solo las
activas ahora: hace falta para poder escribir el estado `ok` de vuelta cuando una
alarma se resuelve. Sin eso (versión anterior, hasta 2026-08-31), una alarma que
se resolvía y volvía a activarse el mismo día quedaba en silencio — la fila en
`alarma_estado` seguía diciendo `activa` con el día de la primera vez, y el
re-aviso diario no dispara dos veces el mismo día.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.db.models import Q

from apps.monitoreo.models import Falla
from apps.monitoreo.services.alarmas.estado import (
    cargar_estados, decidir_notificar, guardar_estados, notificar,
    usuarios_notificables,
)
from apps.plataforma.services.fechas import hoy_col

CATEGORIAS_COMUNICACION = (
    "comunicacion_frontera", "comunicacion_inversores", "comunicacion_total",
)


def decidir_alarmas(frontera_com: bool, inversores_com: bool) -> list[str]:
    """Decide qué alarmas de comunicación aplican. Función PURA → testeable.

    >>> decidir_alarmas(False, False)
    []
    >>> decidir_alarmas(True, False)
    ['comunicacion_frontera']
    >>> decidir_alarmas(False, True)
    ['comunicacion_inversores']
    >>> decidir_alarmas(True, True)
    ['comunicacion_frontera', 'comunicacion_inversores', 'comunicacion_total']
    """
    alarmas: list[str] = []
    if frontera_com:
        alarmas.append("comunicacion_frontera")
    if inversores_com:
        alarmas.append("comunicacion_inversores")
    if frontera_com and inversores_com:
        alarmas.append("comunicacion_total")
    return alarmas


_MENSAJES = {
    "comunicacion_frontera": (
        "alerta",
        "📡 Pérdida de comunicación — frontera",
        "{n}: la frontera reporta pérdida de comunicación (conectividad de datos).",
    ),
    "comunicacion_inversores": (
        "alerta",
        "📡 Pérdida de comunicación — inversores",
        "{n}: uno o varios inversores reportan pérdida de comunicación (internet).",
    ),
    "comunicacion_total": (
        "alerta",
        "🚨 Posible pérdida total de comunicaciones",
        "{n}: pérdida de comunicación simultánea en frontera e inversores. Revisar de inmediato.",
    ),
}

_ETIQUETAS_RECUPERACION = {
    "comunicacion_frontera": "frontera",
    "comunicacion_inversores": "inversores",
    "comunicacion_total": "frontera e inversores",
}


def _estado_comunicacion(proyecto_id: int) -> tuple[bool, bool]:
    """`(hay pérdida en frontera?, hay pérdida en inversores?)` evaluando TODAS
    las fallas activas del proyecto — no finales, no borradas.

    Es lo que permite la regla "ambas simultáneas" aunque vengan en fallas
    separadas.
    """
    activas = Falla.objects.filter(
        proyecto_id=proyecto_id,
        deleted_at__isnull=True,
        estado__es_estado_final=False,
    )
    return (
        activas.filter(frontera_perdida_comunicacion=True).exists(),
        activas.filter(inversores_perdida_comunicacion=True).exists(),
    )


def evaluar_alarmas_falla(falla) -> list[str]:
    """Tras crear o actualizar una falla, evalúa las 3 categorías de alarma del
    proyecto y emite o actualiza según corresponda.

    Devuelve las categorías efectivamente notificadas, incluidas las
    recuperaciones. Envolver en try/except en el llamador: nunca debe romper el
    flujo de la falla.
    """
    proyecto_id = falla.proyecto_id
    frontera_com, inversores_com = _estado_comunicacion(proyecto_id)
    activas = set(decidir_alarmas(frontera_com, inversores_com))

    cache = cargar_estados([proyecto_id])
    pendientes: list[dict] = []
    hoy = hoy_col()
    nombre = (
        falla.proyecto.nombre_comercial if falla.proyecto_id
        else f"Proyecto {proyecto_id}"
    )
    usuarios = None   # perezoso: solo se piden si de verdad hay algo que notificar
    emitidas: list[str] = []

    for cat in CATEGORIAS_COMUNICACION:
        fila = cache.get((proyecto_id, cat))
        if cat in activas:
            estado_nuevo = "activa"
        elif fila is not None and fila[0] == "activa":
            estado_nuevo = "ok"     # se resolvió: avisar recuperación
        else:
            continue                # nunca estuvo activa, nada que evaluar

        avisar, recuperacion = decidir_notificar(
            cache, pendientes, proyecto_id, cat, estado_nuevo, hoy
        )
        if not avisar:
            continue
        if usuarios is None:
            usuarios = usuarios_notificables()
        if recuperacion:
            notificar(
                usuarios, "info", "✅ Comunicación recuperada",
                f"{nombre}: se restableció la comunicación "
                f"({_ETIQUETAS_RECUPERACION[cat]}).",
            )
        else:
            tipo, titulo, plantilla = _MENSAJES[cat]
            notificar(usuarios, tipo, titulo, plantilla.format(n=nombre))
        emitidas.append(cat)

    guardar_estados(pendientes)
    return emitidas
