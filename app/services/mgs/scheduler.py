"""MGS polling scheduler — runs alarm evaluation every 15 min."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from threading import Lock

import pytz
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.mgs.alarm_engine import AlarmEngine, Alarm
from app.services.mgs.quoia_client import QuoiaClient
from app.services.mgs.solenium_client import SoleniumClient
from app.services.mgs.solenium_checker import SoleniumChecker

logger = logging.getLogger("mgs.scheduler")

_engine = AlarmEngine()
_quoia = QuoiaClient()
_solenium = SoleniumClient()
_solenium_checker = SoleniumChecker(_solenium)
_lock = Lock()

_last_nodes: list[dict] = []
_last_alarms: list[Alarm] = []
_last_poll_time: datetime | None = None
_last_inverter_obs: dict[str, str] = {}


def poll_once():
    global _last_nodes, _last_alarms, _last_poll_time, _last_inverter_obs

    if not _quoia.enabled:
        logger.warning("QUOIA_API_TOKEN not set — MGS polling disabled")
        return

    with _lock:
        try:
            nodes = _quoia.get_all_nodes()
            if not nodes:
                logger.warning("Quoia returned empty node list")
                return

            _last_nodes = nodes
            _last_alarms = _engine.evaluate(nodes)
            _last_poll_time = datetime.now(pytz.timezone(settings.TIMEZONE))

            project_names = [p["name"] for p in _engine.get_summary(nodes).get("projects", [])]
            _last_inverter_obs = _solenium_checker.get_inverter_observations(project_names)

            for alarm in _last_alarms:
                inv_note = _last_inverter_obs.get(alarm.node_name)
                if inv_note and alarm.alarm_type.value != "RECUPERACION":
                    alarm.details += f" | Inversores: {inv_note}"

            _persist_alarms(_last_alarms)

            logger.info(
                "MGS poll complete: %d nodes, %d alarms, %d inverter observations",
                len(nodes), len(_last_alarms), len(_last_inverter_obs),
            )

        except Exception:
            logger.exception("MGS poll failed")


def _persist_alarms(alarms: list[Alarm]):
    if not alarms:
        return
    db = SessionLocal()
    try:
        for alarm in alarms:
            db.execute(text("""
                INSERT INTO alarmas_monitoreo
                    (proyecto_nombre, severity, alarm_type, details, source_data, created_at)
                VALUES (:nombre, :severity, :alarm_type, :details, :source_data, :ts)
            """), {
                "nombre": alarm.node_name,
                "severity": alarm.severity.value,
                "alarm_type": alarm.alarm_type.value,
                "details": alarm.details,
                "source_data": json.dumps(asdict(alarm), default=str),
                "ts": alarm.timestamp,
            })
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist alarms")
    finally:
        db.close()


def get_status() -> dict:
    with _lock:
        summary = _engine.get_summary(_last_nodes) if _last_nodes else {}
        active = [
            {
                "severity": a.severity.value,
                "alarm_type": a.alarm_type.value,
                "node_name": a.node_name,
                "details": a.details,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in _last_alarms
        ]
        return {
            "last_poll": _last_poll_time.isoformat() if _last_poll_time else None,
            "summary": summary,
            "active_alarms": active,
            "inverter_observations": _last_inverter_obs,
        }


def get_plants() -> list[dict]:
    with _lock:
        if not _last_nodes:
            return []
        summary = _engine.get_summary(_last_nodes)
        plants = summary.get("projects", [])
        for p in plants:
            p["inverter_obs"] = _last_inverter_obs.get(p["name"])
        return plants
