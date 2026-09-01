"""MGS polling scheduler — runs alarm evaluation every 15 min."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime
from threading import Thread

import pytz
from sqlalchemy import bindparam, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.services.mgs.alarm_engine import AlarmEngine, Alarm, AlarmType, Severity
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

        _auto_create_fallas(db, alarm_ids)
        _auto_close_fallas(db, alarm_ids)

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


# Mapping alarm types to falla catalog tipo codes
_ALARM_TYPE_TO_FALLA_TIPO = {
    AlarmType.PLANTA_CAIDA: "9.1",       # Sin Suministro Electrico
    AlarmType.SIN_GENERACION: "4.6",     # Inversor con derating o eficiencia reducida
    AlarmType.CORTE_ZONA: "9.1",         # Sin Suministro Electrico
}


def _auto_create_fallas(db, alarm_ids: list[tuple[Alarm, int]]):
    """Auto-create Falla records for critical/warning alarms (PLANTA_CAIDA, SIN_GENERACION).
    Skips if an open falla already exists for the same project+alarm_type."""
    critical_types = {AlarmType.PLANTA_CAIDA, AlarmType.SIN_GENERACION}

    for alarm, alarm_db_id in alarm_ids:
        if alarm.alarm_type not in critical_types:
            continue
        if alarm.proyecto_id is None:
            continue

        try:
            proyecto_id = alarm.proyecto_id

            # Check for existing open falla with same alarm_type for this project.
            # Se compara contra alarmas_monitoreo.alarm_type (la alarma original
            # que la creó, vía alarma_monitoreo_id) en vez de parsear el prefijo
            # "[TIPO] ..." de descripcion -- si alguien edita la descripcion a
            # mano (soportado por PATCH /fallas/{id}), el match por ILIKE se
            # rompe en silencio y este guard dejaba de encontrar la falla
            # abierta, creando duplicados (auditoría 2026-09-01).
            existing = db.execute(text("""
                SELECT f.id FROM fallas f
                JOIN fallas_cat_estados e ON f.estado_id = e.id
                JOIN alarmas_monitoreo am ON am.id = f.alarma_monitoreo_id
                WHERE f.proyecto_id = :pid
                  AND e.es_estado_final = FALSE
                  AND f.deleted_at IS NULL
                  AND am.alarm_type = :alarm_type
                LIMIT 1
            """), {
                "pid": proyecto_id,
                "alarm_type": alarm.alarm_type.value,
            }).mappings().first()

            if existing:
                logger.debug("Open falla already exists for project %d alarm %s — skipping", proyecto_id, alarm.alarm_type.value)
                continue

            # Look up catalog IDs
            tipo_code = _ALARM_TYPE_TO_FALLA_TIPO.get(alarm.alarm_type, "9.1")
            tipo_row = db.execute(text(
                "SELECT id FROM fallas_cat_tipos WHERE codigo = :c AND activa = TRUE LIMIT 1"
            ), {"c": tipo_code}).mappings().first()

            estado_row = db.execute(text(
                "SELECT id FROM fallas_cat_estados WHERE codigo = 'abierta' LIMIT 1"
            )).mappings().first()
            if not estado_row:
                estado_row = db.execute(text(
                    "SELECT id FROM fallas_cat_estados WHERE es_estado_final = FALSE ORDER BY orden LIMIT 1"
                )).mappings().first()

            prioridad_code = "critica" if alarm.severity == Severity.CRITICAL else "alta"
            prioridad_row = db.execute(text(
                "SELECT id FROM fallas_cat_prioridades WHERE codigo = :c LIMIT 1"
            ), {"c": prioridad_code}).mappings().first()

            if not tipo_row or not estado_row or not prioridad_row:
                logger.warning("Missing falla catalog data — cannot auto-create falla for alarm %d", alarm_db_id)
                continue

            # Find the first admin/operaciones user as registrado_por
            registrado_por = db.execute(text(
                "SELECT id FROM usuarios WHERE activo = TRUE AND rol IN ('admin', 'operaciones') ORDER BY id LIMIT 1"
            )).mappings().first()
            if not registrado_por:
                registrado_por = db.execute(text(
                    "SELECT id FROM usuarios WHERE activo = TRUE ORDER BY id LIMIT 1"
                )).mappings().first()

            if not registrado_por:
                logger.warning("No active user found — cannot auto-create falla")
                continue

            # Set SLA based on severity
            sla_hours = 8 if alarm.severity == Severity.CRITICAL else 24

            # codigo_interno: placeholder -> INSERT -> renombrar con el id real
            # asignado por la BD (RETURNING id), igual que create_falla() en
            # api/v1/fallas.py. Antes se adivinaba con MAX(id)+1 calculado
            # ANTES del insert -- si dos fallas se crean casi al mismo tiempo,
            # ambas podian calcular el mismo numero y chocar contra el
            # unique=True de codigo_interno, tumbando el INSERT entero
            # (auditoria 2026-09-02).
            placeholder = f"TMP-{uuid.uuid4().hex[:12]}"
            nuevo_id = db.execute(text("""
                INSERT INTO fallas
                    (codigo_interno, proyecto_id, tipo_id, estado_id, prioridad_id,
                     registrado_por_id, descripcion, fecha_identificacion,
                     sla_limite_horas, alarma_monitoreo_id, centinela)
                VALUES
                    (:codigo, :pid, :tipo_id, :estado_id, :prioridad_id,
                     :reg_id, :desc, :fecha, :sla, :alarm_id, 'MGS_AUTO')
                RETURNING id
            """), {
                "codigo": placeholder,
                "pid": proyecto_id,
                "tipo_id": tipo_row["id"],
                "estado_id": estado_row["id"],
                "prioridad_id": prioridad_row["id"],
                "reg_id": registrado_por["id"],
                "desc": f"[{alarm.alarm_type.value}] {alarm.details}",
                "fecha": alarm.timestamp.date(),
                "sla": sla_hours,
                "alarm_id": alarm_db_id,
            }).scalar()

            codigo = f"FAL-{alarm.timestamp.year}-{nuevo_id:05d}"
            db.execute(text("UPDATE fallas SET codigo_interno = :codigo WHERE id = :id"),
                       {"codigo": codigo, "id": nuevo_id})
            db.commit()
            logger.info("Auto-created falla %s for alarm %d (%s — %s)",
                        codigo, alarm_db_id, alarm.proyecto_nombre, alarm.alarm_type.value)

        except Exception:
            db.rollback()
            logger.exception("Failed to auto-create falla for alarm %d", alarm_db_id)


def _auto_close_fallas(db, alarm_ids: list[tuple[Alarm, int]]):
    """Cuando llega una alarma de RECUPERACION, cierra las fallas que el
    propio sistema creó por pérdida de conectividad (PLANTA_CAIDA/CORTE_ZONA)
    para ese proyecto -- si no, quedan abiertas para siempre aunque el
    problema físico ya se resolvió solo. RECUPERACION solo significa "volvió
    la conectividad" (ver alarm_engine.py: se dispara cuando el estado pasa
    de NO_DATA/ERROR a OK/WARNING) -- NO significa "ya está generando
    normal", así que NO toca las fallas de SIN_GENERACION (conectado pero
    sin generar, ej. un inversor dañado): esas requieren su propia
    verificación y deben seguir abiertas. Se identifican por el alarm_type de
    la alarma original que las creó (alarmas_monitoreo, vía
    Falla.alarma_monitoreo_id) -- NO por el prefijo "[TIPO] ..." que
    _auto_create_fallas escribe en descripcion, porque ese texto es editable
    a mano (PATCH /fallas/{id}) y si alguien lo borra, el match por ILIKE
    dejaba la falla abierta para siempre pese a que el sistema sí detectó la
    recuperación (auditoría 2026-09-01).
    Se cierran (no se borran ni se ocultan): quedan con una nota automática,
    editable -- el correo automático a los contactos operacionales del
    cliente se apagó 2026-09-01 (mismo criterio que el envío por alarma
    nueva, ver _persist_alarms más abajo: "no quiero que se haga el envío
    automático de clientes, no tengo control"). El cierre sigue siendo
    visible en Gestión de Fallas; el aviso manual sigue disponible desde ahí."""
    from app.models import Falla, FallaCatEstado, FallaSeguimiento
    from app.api.v1.fallas import _sincronizar_resolucion

    _TIPOS_CONECTIVIDAD = (AlarmType.PLANTA_CAIDA, AlarmType.CORTE_ZONA)

    for alarm, alarm_db_id in alarm_ids:
        if alarm.alarm_type != AlarmType.RECUPERACION:
            continue
        if alarm.proyecto_id is None:
            continue

        try:
            ids_conectividad = db.execute(
                text("SELECT id FROM alarmas_monitoreo WHERE alarm_type IN :tipos").bindparams(
                    bindparam("tipos", expanding=True)
                ),
                {"tipos": [t.value for t in _TIPOS_CONECTIVIDAD]},
            ).scalars().all()

            abiertas = (
                db.query(Falla)
                .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
                .filter(
                    Falla.proyecto_id == alarm.proyecto_id,
                    Falla.alarma_monitoreo_id.in_(ids_conectividad),
                    FallaCatEstado.es_estado_final.is_(False),
                    Falla.deleted_at.is_(None),
                )
                .all()
            )
            if not abiertas:
                continue

            estado_final = (
                db.query(FallaCatEstado)
                .filter(FallaCatEstado.es_estado_final.is_(True))
                .order_by(FallaCatEstado.orden)
                .first()
            )
            if not estado_final:
                logger.warning("No hay estado final en el catálogo — no se puede auto-cerrar")
                continue

            for falla in abiertas:
                _sincronizar_resolucion(falla, estado_final)
                falla.estado_id = estado_final.id
                db.add(FallaSeguimiento(
                    falla_id=falla.id,
                    usuario_id=falla.registrado_por_id,
                    nota="Cerrada automáticamente: el proyecto volvió a reportar (recuperación de alarma MGS).",
                    estado_nuevo_id=estado_final.id,
                ))
                db.commit()
                logger.info("Auto-cerrada falla %s tras recuperación de alarma (%s)",
                            falla.codigo_interno, alarm.proyecto_nombre)

        except Exception:
            db.rollback()
            logger.exception("Failed to auto-close fallas for recovery alarm %d", alarm_db_id)

