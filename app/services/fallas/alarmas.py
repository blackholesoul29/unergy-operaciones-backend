"""Alarmas de comunicación derivadas del reporte estructurado de fallas.

Reglas (extensibles sin tocar la clasificación de fallas):
  - Pérdida de comunicación de la frontera        → ``comunicacion_frontera``
  - Pérdida de comunicación de ≥1 inversor         → ``comunicacion_inversores``
  - Ambas simultáneas (en la misma falla o en fallas activas del mismo proyecto)
                                                   → ``comunicacion_total`` (CRÍTICA:
    posible pérdida total de comunicaciones del proyecto).

Entrega: notificaciones in-app (campana) a roles admin/operaciones/monitoreo, con
anti-spam vía la tabla ``alarma_estado(proyecto_id, categoria)`` (mismo mecanismo que
las alarmas de desconexión MGS). El hook en ``POST /fallas`` va envuelto en try/except:
nunca debe romper la creación de la falla.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.usuarios import Usuario, RolEnum
from app.models.notificaciones import Notificacion, TipoNotificacionEnum

logger = logging.getLogger("alarmas.fallas")

ROLES_NOTIF = (RolEnum.admin, RolEnum.operaciones, RolEnum.monitoreo)


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


def _col_today():
    return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _notificar(db: Session, categoria: str, nombre: str, link: str):
    tipo, titulo, plantilla = _MENSAJES[categoria]
    usuarios = db.query(Usuario).filter(
        Usuario.activo == True,  # noqa: E712
        Usuario.rol.in_(list(ROLES_NOTIF)),
    ).all()
    mensaje = plantilla.format(n=nombre)
    for u in usuarios:
        db.add(Notificacion(usuario_id=u.id, tipo=tipo, titulo=titulo, mensaje=mensaje, link=link))


def _emitir_con_antispam(db: Session, proyecto_id: int, categoria: str, nombre: str, link: str):
    """Emite la alarma `categoria` para el proyecto solo si cambió de estado o
    si persiste y no se ha avisado hoy. Reusa la tabla alarma_estado."""
    today = _col_today()
    row = db.execute(
        text("SELECT estado, dia FROM alarma_estado WHERE proyecto_id=:p AND categoria=:c"),
        {"p": proyecto_id, "c": categoria},
    ).fetchone()

    notify = False
    if row is None:
        notify = True
    elif row.estado != "activa":
        notify = True
    elif row.dia is None or row.dia < today:
        notify = True  # re-aviso diario mientras persista

    if not notify:
        return False

    db.execute(text("""
        INSERT INTO alarma_estado (proyecto_id, categoria, estado, dia, updated_at)
        VALUES (:p, :c, 'activa', :d, now())
        ON CONFLICT (proyecto_id, categoria)
        DO UPDATE SET estado='activa', dia=:d, updated_at=now()
    """), {"p": proyecto_id, "c": categoria, "d": today})
    _notificar(db, categoria, nombre, link)
    return True


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
    """Tras crear/actualizar una falla, evalúa y emite las alarmas de comunicación
    del proyecto. Devuelve la lista de categorías efectivamente notificadas.

    Envolver en try/except en el caller: nunca debe romper el flujo de la falla.
    """
    proyecto_id = falla.proyecto_id
    frontera_com, inversores_com = _proyecto_comunicacion_state(db, proyecto_id)
    categorias = decidir_alarmas(frontera_com, inversores_com)
    if not categorias:
        return []

    nombre = falla.proyecto.nombre_comercial if getattr(falla, "proyecto", None) else f"Proyecto {proyecto_id}"
    link = f"/proyectos/{proyecto_id}"
    emitidas = []
    for cat in categorias:
        if _emitir_con_antispam(db, proyecto_id, cat, nombre, link):
            emitidas.append(cat)
    return emitidas
