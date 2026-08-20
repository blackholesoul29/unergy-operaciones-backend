"""MGS polling scheduler — runs alarm evaluation every 15 min."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from threading import Lock, Thread

import pytz
from sqlalchemy import or_, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.mgs.alarm_engine import AlarmEngine, Alarm, AlarmType, Severity
from app.services.mgs.quoia_client import QuoiaClient
from app.services.mgs.solenium_client import SoleniumClient
from app.services.mgs.solenium_checker import SoleniumChecker

logger = logging.getLogger("mgs.scheduler")

_engine = AlarmEngine()
_quoia = QuoiaClient()
_solenium = SoleniumClient()
_solenium_checker = SoleniumChecker(_solenium)
_write_lock = Lock()

_last_nodes: list[dict] = []
_last_alarms: list[Alarm] = []
_last_poll_time: datetime | None = None
_last_inverter_obs: dict[str, str] = {}
_poll_running = False


def poll_once():
    global _last_nodes, _last_alarms, _last_poll_time, _last_inverter_obs, _poll_running

    if not _quoia.enabled:
        logger.warning("QUOIA_API_TOKEN not set — MGS polling disabled")
        return

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

        nodes = _quoia.get_all_nodes()
        if not nodes:
            logger.warning("Quoia returned empty node list")
            return

        alarms = _engine.evaluate(nodes)
        poll_time = datetime.now(pytz.timezone(settings.TIMEZONE))

        project_names = [p["name"] for p in _engine.get_summary(nodes).get("projects", [])]
        try:
            inverter_obs = _solenium_checker.get_inverter_observations(project_names)
        except Exception:
            logger.exception("Solenium inverter check failed — continuing without")
            inverter_obs = {}

        for alarm in alarms:
            inv_note = inverter_obs.get(alarm.node_name)
            if inv_note and alarm.alarm_type.value != "RECUPERACION":
                alarm.details += f" | Inversores: {inv_note}"

        with _write_lock:
            _last_nodes = nodes
            _last_alarms = alarms
            _last_poll_time = poll_time
            _last_inverter_obs = inverter_obs

        _persist_alarms(alarms)

        logger.info(
            "MGS poll complete: %d nodes, %d alarms, %d inverter observations",
            len(nodes), len(alarms), len(inverter_obs),
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


def _persist_alarms(alarms: list[Alarm]):
    if not alarms:
        return
    alarm_ids: list[tuple[Alarm, int]] = []
    db = SessionLocal()
    try:
        for alarm in alarms:
            result = db.execute(text("""
                INSERT INTO alarmas_monitoreo
                    (proyecto_nombre, severity, alarm_type, details, source_data, created_at)
                VALUES (:nombre, :severity, :alarm_type, :details, :source_data, :ts)
                RETURNING id
            """), {
                "nombre": alarm.node_name,
                "severity": alarm.severity.value,
                "alarm_type": alarm.alarm_type.value,
                "details": alarm.details,
                "source_data": json.dumps(asdict(alarm), default=str),
                "ts": alarm.timestamp,
            })
            alarm_db_id = result.scalar()
            alarm_ids.append((alarm, alarm_db_id))
        db.commit()

        _auto_create_fallas(db, alarm_ids)
        _auto_close_fallas(db, alarm_ids)

    except Exception:
        db.rollback()
        logger.exception("Failed to persist alarms")
    finally:
        db.close()

    if alarm_ids:
        try:
            _send_alarm_notifications_safe(alarm_ids)
        except Exception:
            logger.exception("Failed to send alarm notifications")


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

        try:
            # Resolve project by name
            proyecto = db.execute(text("""
                SELECT id FROM proyectos
                WHERE deleted_at IS NULL
                  AND (nombre_comercial = :name
                       OR nombre_comercial ILIKE :pattern)
                LIMIT 1
            """), {
                "name": alarm.node_name,
                "pattern": f"%{alarm.node_name}%",
            }).mappings().first()

            if not proyecto:
                logger.debug("No project found for alarm node '%s' — skipping falla creation", alarm.node_name)
                continue

            proyecto_id = proyecto["id"]

            # Check for existing open falla with same alarm_type for this project
            existing = db.execute(text("""
                SELECT f.id FROM fallas f
                JOIN fallas_cat_estados e ON f.estado_id = e.id
                WHERE f.proyecto_id = :pid
                  AND f.alarma_monitoreo_id IS NOT NULL
                  AND e.es_estado_final = FALSE
                  AND f.deleted_at IS NULL
                  AND f.descripcion ILIKE :alarm_pattern
                LIMIT 1
            """), {
                "pid": proyecto_id,
                "alarm_pattern": f"%{alarm.alarm_type.value}%",
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

            # Generate codigo_interno
            max_id = db.execute(text("SELECT COALESCE(MAX(id), 0) FROM fallas")).scalar()
            year = alarm.timestamp.year
            codigo = f"FAL-{year}-{max_id + 1:05d}"

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

            db.execute(text("""
                INSERT INTO fallas
                    (codigo_interno, proyecto_id, tipo_id, estado_id, prioridad_id,
                     registrado_por_id, descripcion, fecha_identificacion,
                     sla_limite_horas, alarma_monitoreo_id, centinela)
                VALUES
                    (:codigo, :pid, :tipo_id, :estado_id, :prioridad_id,
                     :reg_id, :desc, :fecha, :sla, :alarm_id, 'MGS_AUTO')
            """), {
                "codigo": codigo,
                "pid": proyecto_id,
                "tipo_id": tipo_row["id"],
                "estado_id": estado_row["id"],
                "prioridad_id": prioridad_row["id"],
                "reg_id": registrado_por["id"],
                "desc": f"[{alarm.alarm_type.value}] {alarm.details}",
                "fecha": alarm.timestamp.date(),
                "sla": sla_hours,
                "alarm_id": alarm_db_id,
            })
            db.commit()
            logger.info("Auto-created falla %s for alarm %d (%s — %s)",
                        codigo, alarm_db_id, alarm.node_name, alarm.alarm_type.value)

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
    verificación y deben seguir abiertas. Se identifican por el mismo prefijo
    que ya usa _auto_create_fallas al crearlas (descripcion = "[TIPO] ...").
    Se cierran (no se borran ni se ocultan): quedan con una nota automática,
    editable, y se notifica por correo a los contactos operacionales del
    proyecto para que no pase desapercibido -- cualquiera puede entrar
    después a comentar o documentar la causa raíz."""
    from app.models import Falla, FallaCatEstado, FallaSeguimiento
    from app.api.v1.fallas import _sincronizar_resolucion, _enviar_notificacion

    _TIPOS_CONECTIVIDAD = (AlarmType.PLANTA_CAIDA, AlarmType.CORTE_ZONA)

    for alarm, alarm_db_id in alarm_ids:
        if alarm.alarm_type != AlarmType.RECUPERACION:
            continue

        try:
            proyecto = db.execute(text("""
                SELECT id FROM proyectos
                WHERE deleted_at IS NULL
                  AND (nombre_comercial = :name
                       OR nombre_comercial ILIKE :pattern)
                LIMIT 1
            """), {
                "name": alarm.node_name,
                "pattern": f"%{alarm.node_name}%",
            }).mappings().first()
            if not proyecto:
                continue

            filtro_tipo = or_(*[
                Falla.descripcion.ilike(f"%[{t.value}]%") for t in _TIPOS_CONECTIVIDAD
            ])
            abiertas = (
                db.query(Falla)
                .join(FallaCatEstado, Falla.estado_id == FallaCatEstado.id)
                .filter(
                    Falla.proyecto_id == proyecto["id"],
                    Falla.alarma_monitoreo_id.isnot(None),
                    FallaCatEstado.es_estado_final.is_(False),
                    Falla.deleted_at.is_(None),
                    filtro_tipo,
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
                            falla.codigo_interno, alarm.node_name)
                try:
                    _enviar_notificacion(falla, accion="cerrada", usuario_nombre="Sistema (auto-cierre MGS)", db=db)
                except Exception:
                    logger.exception("No se pudo notificar el auto-cierre de %s", falla.codigo_interno)

        except Exception:
            db.rollback()
            logger.exception("Failed to auto-close fallas for recovery alarm %d", alarm_db_id)


def _send_alarm_notifications_safe(alarm_ids: list[tuple[Alarm, int]]):
    """Send email notifications in a separate DB session so failures don't affect persistence."""
    from app.services.email_service import send_alarm_notification_email
    from app.services.contactos import get_contactos

    notifiable_severities = {Severity.CRITICAL, Severity.WARNING}
    to_notify = [
        (alarm, aid) for alarm, aid in alarm_ids
        if alarm.severity in notifiable_severities and alarm.alarm_type != AlarmType.RECUPERACION
    ]
    if not to_notify:
        return

    db = SessionLocal()
    try:
        for alarm, alarm_db_id in to_notify:
            try:
                # Resolver el proyecto real por nombre/alias (mismo criterio que
                # _auto_create_fallas) en vez de emparejar directamente contra la
                # tabla de contactos por nombre -- así get_contactos() resuelve
                # correctamente el puntero de área / inversionistas por FK.
                proyecto = db.execute(text("""
                    SELECT id FROM proyectos
                    WHERE deleted_at IS NULL
                      AND (nombre_comercial = :name
                           OR nombre_comercial ILIKE :pattern)
                    LIMIT 1
                """), {
                    "name": alarm.node_name,
                    "pattern": f"%{alarm.node_name}%",
                }).mappings().first()

                if not proyecto:
                    logger.debug("No project found for alarm node '%s' — skipping notification", alarm.node_name)
                    continue

                emails = get_contactos(db, "operacional", proyecto_id=proyecto["id"])
                if not emails:
                    continue

                send_alarm_notification_email(
                    to_emails=emails,
                    proyecto_nombre=alarm.node_name,
                    alarm_type=alarm.alarm_type.value,
                    severity=alarm.severity.value,
                    details=alarm.details,
                )
            except Exception:
                logger.exception("Failed to send alarm notification for '%s'", alarm.node_name)
    finally:
        db.close()


def get_status() -> dict:
    nodes = _last_nodes
    alarms = _last_alarms
    poll_time = _last_poll_time
    inv_obs = _last_inverter_obs

    summary = _engine.get_summary(nodes) if nodes else {}
    active = [
        {
            "severity": a.severity.value,
            "alarm_type": a.alarm_type.value,
            "node_name": a.node_name,
            "details": a.details,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in alarms
    ]
    return {
        "last_poll": poll_time.isoformat() if poll_time else None,
        "poll_running": _poll_running,
        "summary": summary,
        "active_alarms": active,
        "inverter_observations": inv_obs,
    }


def get_plants() -> list[dict]:
    nodes = _last_nodes
    inv_obs = _last_inverter_obs

    if not nodes:
        return []
    summary = _engine.get_summary(nodes)
    plants = summary.get("projects", [])
    for p in plants:
        p["inverter_obs"] = inv_obs.get(p["name"])
    return plants
