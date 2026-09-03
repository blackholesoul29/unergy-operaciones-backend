"""MGS polling scheduler — runs alarm evaluation every 15 min."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from threading import Thread

import pytz
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.services.mgs.alarm_engine import AlarmEngine, Alarm, AlarmType
from app.services.mgs.gaia_client import GaiaClient, build_db_proyecto_frt_map, find_gaia_node_pair
from app.services.mgs.solenium_client import SoleniumClient
from app.services.mgs.solenium_checker import SoleniumChecker

logger = logging.getLogger("mgs.scheduler")

_engine = AlarmEngine()
_solenium = SoleniumClient()
_solenium_checker = SoleniumChecker(_solenium)

_poll_running = False


def _resolver_mapa_proyectos(gaia: GaiaClient) -> tuple[dict[int, int], dict[int, str]]:
    """Resuelve, para cada minigranja/GD en operación, sus nodos Quoia reales
    (Principal/Respaldo) vía fronteras.proyecto_id -> codigo_frontera -- la
    misma fuente de verdad que ya usa desconexion.py (ver
    gaia_client._resolve_frt_and_pair), en vez de adivinar por nombre
    (project_name() + ILIKE contra proyectos.nombre_comercial), que fallaba
    en silencio cuando el nombre del nodo no calzaba con el patrón esperado
    (auditoría alarmas_monitoreo 2026-08-31).

    Devuelve (node_id -> proyecto_id, proyecto_id -> nombre_comercial). Los
    proyectos sin frontera de generación vinculada quedan fuera y se reportan
    por separado (antes: sin ningún aviso)."""
    db = SessionLocal()
    try:
        proyectos = db.query(Proyecto.id, Proyecto.nombre_comercial).filter(
            Proyecto.estado == "en_operacion",
            Proyecto.deleted_at.is_(None),
            Proyecto.tipo_proyecto.in_([TipoProyectoEnum.minigranja, TipoProyectoEnum.gd]),
            # Solo plantas con servicio de operación contratado -- decision de
            # negocio 2026-09-01: antes entraba cualquier minigranja/GD activa
            # sin importar si Unergy la opera, generando alarmas/fallas para
            # plantas fuera de alcance.
            Proyecto.srv_operacion.is_(True),
        ).all()
        fronteras = db.query(Frontera.proyecto_id, Frontera.codigo_frontera).filter(
            Frontera.tipo_frontera.in_([TipoFronteraEnum.generacion, TipoFronteraEnum.generacion_consumo]),
            Frontera.codigo_frontera.isnot(None),
        ).all()
        db_proyecto_frt_map = build_db_proyecto_frt_map(list(fronteras))

        node_to_proyecto: dict[int, int] = {}
        proyecto_nombres: dict[int, str] = {}
        sin_vinculo: list[str] = []
        for pid, nombre in proyectos:
            node_p, node_r = find_gaia_node_pair(
                gaia=gaia, proyecto_id=pid, db_proyecto_frt_map=db_proyecto_frt_map,
            )
            if node_p is None and node_r is None:
                sin_vinculo.append(nombre)
                continue
            proyecto_nombres[pid] = nombre
            for nid in (node_p, node_r):
                if nid is not None:
                    node_to_proyecto[nid] = pid

        if sin_vinculo:
            logger.warning(
                "%d proyectos en_operacion sin frontera de generación vinculada -- "
                "sin monitoreo MGS este ciclo: %s",
                len(sin_vinculo), ", ".join(sin_vinculo),
            )
        return node_to_proyecto, proyecto_nombres
    finally:
        db.close()


def poll_once():
    global _poll_running

    if _poll_running:
        logger.info("Poll already in progress — skipping")
        return

    _poll_running = True
    try:
        # Alarmas de desconexión (inversores vs medidor) — aislado, no debe romper MGS
        try:
            from app.services.alarmas.desconexion import evaluar_desconexiones
            evaluar_desconexiones()
        except Exception:
            logger.exception("evaluar_desconexiones falló (no afecta MGS)")

        gaia = GaiaClient()
        if not gaia.enabled:
            logger.warning("GAIA_USER/GAIA_PASS not set — MGS polling disabled")
            return

        node_to_proyecto, proyecto_nombres = _resolver_mapa_proyectos(gaia)
        if not node_to_proyecto:
            logger.warning("Sin proyectos resueltos a nodos Quoia — se omite el ciclo MGS")
            return

        nodes = gaia.get_all_nodes()
        if not nodes:
            logger.warning("Gaia returned empty node list")
            return

        # Snapshot pre-evaluate() para poder cerrar en BD (resolved_at) los tipos
        # que el motor descarta internamente sin emitir una Alarm explícita
        # (ver _resolver_alarmas_superadas).
        prev_active = {k: set(v) for k, v in _engine.active_alarms.items()}
        alarms = _engine.evaluate(nodes, node_to_proyecto, proyecto_nombres)

        summary = _engine.get_summary(nodes, node_to_proyecto, proyecto_nombres)
        project_names = [p["name"] for p in summary.get("projects", [])]
        try:
            inverter_obs = _solenium_checker.get_inverter_observations(project_names)
        except Exception:
            logger.exception("Solenium inverter check failed — continuing without")
            inverter_obs = {}

        for alarm in alarms:
            inv_note = inverter_obs.get(alarm.proyecto_nombre)
            if inv_note and alarm.alarm_type.value != "RECUPERACION":
                alarm.details += f" | Inversores: {inv_note}"

        _persist_alarms(alarms, prev_active, proyecto_nombres)

        logger.info(
            "MGS poll complete: %d nodes, %d proyectos, %d alarms, %d inverter observations",
            len(nodes), len(proyecto_nombres), len(alarms), len(inverter_obs),
        )

    except Exception:
        logger.exception("MGS poll failed")
    finally:
        _poll_running = False


def poll_once_async():
    """Run poll_once in a background thread (non-blocking for API callers)."""
    if _poll_running:
        return False
    t = Thread(target=poll_once, daemon=True)
    t.start()
    return True


def _persist_alarms(
    alarms: list[Alarm],
    prev_active: dict[int, set] | None = None,
    proyecto_nombres: dict[int, str] | None = None,
):
    if not alarms and not prev_active:
        return
    alarm_ids: list[tuple[Alarm, int]] = []
    db = SessionLocal()
    try:
        for alarm in alarms:
            # RECUPERACION es un evento puntual ("volvió la conectividad"), no una
            # condición en curso -- se guarda ya resuelta para que no cuente como
            # "activa" en el conteo del dashboard (ver auditoría alarmas_monitoreo
            # 2026-08-31: antes ninguna fila fijaba resolved_at, así que el conteo
            # de "alarmas activas" solo crecía y nunca reflejaba el estado real).
            resolved_at = alarm.timestamp if alarm.alarm_type == AlarmType.RECUPERACION else None
            result = db.execute(text("""
                INSERT INTO alarmas_monitoreo
                    (proyecto_nombre, severity, alarm_type, details, source_data, created_at, resolved_at)
                VALUES (:nombre, :severity, :alarm_type, :details, :source_data, :ts, :resolved_at)
                RETURNING id
            """), {
                "nombre": alarm.proyecto_nombre,
                "severity": alarm.severity.value,
                "alarm_type": alarm.alarm_type.value,
                "details": alarm.details,
                "source_data": json.dumps(asdict(alarm), default=str),
                "ts": alarm.timestamp,
                "resolved_at": resolved_at,
            })
            alarm_db_id = result.scalar()
            alarm_ids.append((alarm, alarm_db_id))
        db.commit()

        if prev_active is not None:
            try:
                _resolver_alarmas_superadas(
                    db, prev_active, _engine.active_alarms, _engine.previous_states,
                    proyecto_nombres or {},
                )
            except Exception:
                db.rollback()
                logger.exception("Failed to resolve cleared alarms")

        # Acá se llamaba a _auto_create_fallas/_auto_close_fallas -- eliminados
        # 2026-09-02 (ver el comentario al final del archivo). Las alarmas se
        # siguen guardando y resolviendo; ya no generan ni cierran fallas.

    except Exception:
        db.rollback()
        logger.exception("Failed to persist alarms")
    finally:
        db.close()

    # Envío automático a clientes DESACTIVADO (2026-09-01, pedido explícito de
    # negocio: "no quiero que se haga el envío automático de clientes, no
    # tengo control"). Se disparaba sin ningún filtro para toda alarma
    # CRITICAL/WARNING -- expuesto recién hoy porque `_resolver_mapa_proyectos`
    # (c6577fb) amplió el monitoreo a proyectos que antes quedaban fuera por
    # matching de nombre, mandando correos a clientes de plantas que nunca
    # antes habían disparado una alarma. Las alarmas/fallas se siguen
    # creando y viendo en Gestión de Fallas -- solo se apagó el correo
    # automático a los contactos operacionales del cliente. El wrapper que
    # hacía este envío (`_send_alarm_notifications_safe`) se eliminó de este
    # archivo el mismo día (quedaba como código muerto, riesgo de reactivarse
    # sin este contexto) -- si se retoma con un control real (ej. opt-in por
    # proyecto o un digest en vez de correo por alarma), reconstruir sobre
    # `send_alarm_notification_email` (app/services/email_service.py) y
    # `get_contactos(db, "operacional", proyecto_id=...)`
    # (app/services/contactos.py), que siguen disponibles.


def _tipos_superados(
    prev_active: dict[int, set], curr_active: dict[int, set],
) -> dict[int, set]:
    """Función pura: para cada proyecto (por proyecto_id), qué tipos de
    alarma estaban activos antes de evaluate() y ya no lo están después -- la
    condición se superó aunque el motor no haya emitido una Alarm explícita
    para avisarlo (pasa con SIN_GENERACION: el motor solo hace
    `proj_alarms.discard(...)` cuando vuelve a generar, sin crear ningún
    evento de recuperación)."""
    superados: dict[int, set] = {}
    for key, before in prev_active.items():
        cleared = before - curr_active.get(key, set())
        if cleared:
            superados[key] = cleared
    return superados


def _resolver_alarmas_superadas(
    db,
    prev_active: dict[int, set],
    curr_active: dict[int, set],
    previous_states: dict[int, str],
    proyecto_nombres: dict[int, str],
):
    """Cierra en `alarmas_monitoreo` (resolved_at) las condiciones que ya no
    están activas en el motor, para que el conteo de "alarmas activas" del
    dashboard refleje el estado real y no solo crezca para siempre.

    `alarmas_monitoreo` solo guarda `proyecto_nombre` (no proyecto_id), así
    que acá se traduce el proyecto_id que usa el motor de vuelta al nombre
    con el que se persistió esa fila."""
    now = datetime.now(pytz.timezone(settings.TIMEZONE))

    for pid, tipos in _tipos_superados(prev_active, curr_active).items():
        nombre = proyecto_nombres.get(pid)
        if nombre is None:
            continue
        db.execute(text("""
            UPDATE alarmas_monitoreo
            SET resolved_at = :now
            WHERE proyecto_nombre = :nombre
              AND alarm_type = ANY(:tipos)
              AND resolved_at IS NULL
        """), {"now": now, "nombre": nombre, "tipos": [t.value for t in tipos]})

    # CORTE_ZONA no vive en active_alarms (es un evento derivado que agrupa
    # varios proyectos a la vez, no el estado de uno solo) -- se cierra cuando
    # ninguno de los proyectos listados en su nombre (join por coma, ver
    # _detect_zone_outage) sigue en NO_DATA/ERROR. previous_states está
    # indexado por proyecto_id, así que se arma un mapa por nombre acá.
    estado_por_nombre = {
        proyecto_nombres[pid]: previous_states.get(pid)
        for pid in proyecto_nombres
    }
    abiertas_zona = db.execute(text("""
        SELECT id, proyecto_nombre FROM alarmas_monitoreo
        WHERE alarm_type = 'CORTE_ZONA' AND resolved_at IS NULL
    """)).mappings().all()
    for row in abiertas_zona:
        miembros = [m.strip() for m in row["proyecto_nombre"].split(",")]
        if any(estado_por_nombre.get(m) in ("NO_DATA", "ERROR") for m in miembros):
            continue
        db.execute(text(
            "UPDATE alarmas_monitoreo SET resolved_at = :now WHERE id = :id"
        ), {"now": now, "id": row["id"]})

    db.commit()


# ── Creación/cierre automático de fallas: ELIMINADO (2026-09-02) ─────────────
# Decisión de negocio de Laura: las fallas se registran solo de dos formas --
# a mano desde la plataforma, o por el integrador externo vía POST /fallas.
# El motor de monitoreo ya no las crea ni las cierra solo.
#
# Lo que había acá y se quitó:
#   · `_auto_create_fallas()` -- creaba una falla por cada alarma PLANTA_CAIDA
#     o SIN_GENERACION (una por proyecto+tipo, sin duplicar si ya había una
#     abierta), con prioridad crítica/grave según severidad y ligada a la
#     alarma que la originó (`fallas.alarma_monitoreo_id`).
#   · `_auto_close_fallas()` -- al llegar una alarma RECUPERACION, cerraba las
#     fallas de conectividad (PLANTA_CAIDA/CORTE_ZONA) que ese mismo motor
#     había creado para el proyecto, sellando fecha_resolucion/sla_cumplido y
#     dejando una nota de seguimiento automática.
#   · `_ALARM_TYPE_TO_FALLA_TIPO` -- el mapeo alarma -> tipo de catálogo que
#     usaba la creación.
#
# El monitoreo NO se tocó: las alarmas se siguen detectando, guardando en
# `alarmas_monitoreo`, resolviendo (`resolved_at`) y mostrando en el dashboard.
# Lo único que se cortó es el puente alarma -> falla.
#
# `fallas.alarma_monitoreo_id` se conserva: es el dato que distingue las fallas
# históricas creadas por este motor (y la única señal no falsificable de
# "origen automático", ver la auditoría de `centinela`). Las fallas
# auto-creadas que quedaron abiertas hay que cerrarlas a mano -- ya no se
# cierran solas.
#
# Si algún día se retoma, el punto de enganche era `_persist_alarms()`, que ya
# tiene a mano la lista `(Alarm, id_en_alarmas_monitoreo)` de cada ciclo.
