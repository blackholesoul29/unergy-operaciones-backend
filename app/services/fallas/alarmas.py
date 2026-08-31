"""Alarmas de comunicación derivadas del reporte estructurado de fallas.

Reglas (extensibles sin tocar la clasificación de fallas):
  - Pérdida de comunicación de la frontera        → ``comunicacion_frontera``
  - Pérdida de comunicación de ≥1 inversor         → ``comunicacion_inversores``
  - Ambas simultáneas (en la misma falla o en fallas activas del mismo proyecto)
                                                   → ``comunicacion_total`` (CRÍTICA:
    posible pérdida total de comunicaciones del proyecto).

Entrega: notificaciones in-app (campana) a roles admin/operaciones/monitoreo, con
anti-spam vía la tabla ``alarma_estado(proyecto_id, categoria)`` (mismo mecanismo que
las alarmas de desconexión MGS, ver app.services.alarmas.estado). El hook en
``POST /fallas`` va envuelto en try/except: nunca debe romper la creación de la falla.

Evalúa las 3 categorías en CADA llamada (activas y ya resueltas), no solo las que
están activas ahora mismo -- necesario para poder escribir el estado 'ok' de vuelta
cuando una alarma se resuelve. Sin eso (versión anterior, hasta 2026-08-31), una
alarma que se resolvía y volvía a activarse el mismo día quedaba en silencio: la
fila en alarma_estado seguía diciendo estado='activa', dia=hoy de la primera vez,
y el re-aviso diario no dispara dos veces el mismo día.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.notificaciones import TipoNotificacionEnum
from app.services.alarmas.estado import (
    cargar_estados, decidir_notificar, guardar_estados, usuarios_notificables, notificar,
)

CATEGORIAS_COMUNICACION = ("comunicacion_frontera", "comunicacion_inversores", "comunicacion_total")


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
        TipoNotificacionEnum.alerta,
        "📡 Pérdida de comunicación — frontera",
        "{n}: la frontera reporta pérdida de comunicación (conectividad de datos).",
    ),
    "comunicacion_inversores": (
        TipoNotificacionEnum.alerta,
        "📡 Pérdida de comunicación — inversores",
        "{n}: uno o varios inversores reportan pérdida de comunicación (internet).",
    ),
    "comunicacion_total": (
        TipoNotificacionEnum.alerta,
        "🚨 Posible pérdida total de comunicaciones",
        "{n}: pérdida de comunicación simultánea en frontera e inversores. Revisar de inmediato.",
    ),
}

_ETIQUETAS_RECUPERACION = {
    "comunicacion_frontera": "frontera",
    "comunicacion_inversores": "inversores",
    "comunicacion_total": "frontera e inversores",
}


def _col_today():
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _proyecto_comunicacion_state(db: Session, proyecto_id: int) -> tuple[bool, bool]:
    """Estado de comunicación del proyecto evaluando TODAS sus fallas activas
    (no finales, no borradas): ¿hay pérdida en frontera? ¿en inversores?

    Permite la regla "ambas simultáneas" aunque vengan en fallas separadas.
    """
    row = db.execute(text("""
        SELECT
            COALESCE(bool_or(f.frontera_perdida_comunicacion), false) AS frontera,
            COALESCE(bool_or(f.inversores_perdida_comunicacion), false) AS inversores
        FROM fallas f
        JOIN fallas_cat_estados e ON e.id = f.estado_id
        WHERE f.proyecto_id = :p
          AND f.deleted_at IS NULL
          AND e.es_estado_final = false
    """), {"p": proyecto_id}).fetchone()
    if not row:
        return False, False
    return bool(row.frontera), bool(row.inversores)


def evaluar_alarmas_falla(db: Session, falla) -> list[str]:
    """Tras crear/actualizar una falla, evalúa las 3 categorías de alarma de
    comunicación del proyecto (activas y resueltas) y emite/actualiza según
    corresponda. Devuelve la lista de categorías efectivamente notificadas
    (incluye recuperaciones).

    Envolver en try/except en el caller: nunca debe romper el flujo de la falla.
    """
    proyecto_id = falla.proyecto_id
    frontera_com, inversores_com = _proyecto_comunicacion_state(db, proyecto_id)
    activas = set(decidir_alarmas(frontera_com, inversores_com))

    cache = cargar_estados(db, [proyecto_id])
    pending: list[dict] = []
    hoy = _col_today()
    nombre = falla.proyecto.nombre_comercial if getattr(falla, "proyecto", None) else f"Proyecto {proyecto_id}"
    link = f"/proyectos/{proyecto_id}"
    usuarios = None  # perezoso -- solo se pide si de verdad hay algo que notificar
    emitidas: list[str] = []

    for cat in CATEGORIAS_COMUNICACION:
        row = cache.get((proyecto_id, cat))
        if cat in activas:
            estado_nuevo = "activa"
        elif row is not None and row[0] == "activa":
            estado_nuevo = "ok"  # se resolvió -- avisar recuperación
        else:
            continue  # nunca estuvo activa, nada que evaluar

        notify, recovery = decidir_notificar(cache, pending, proyecto_id, cat, estado_nuevo, hoy)
        if not notify:
            continue
        if usuarios is None:
            usuarios = usuarios_notificables(db)
        if recovery:
            notificar(db, usuarios, TipoNotificacionEnum.info, "✅ Comunicación recuperada",
                      f"{nombre}: se restableció la comunicación ({_ETIQUETAS_RECUPERACION[cat]}).", link)
        else:
            tipo, titulo, plantilla = _MENSAJES[cat]
            notificar(db, usuarios, tipo, titulo, plantilla.format(n=nombre), link)
        emitidas.append(cat)

    guardar_estados(db, pending)
    return emitidas
