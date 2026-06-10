"""
Motor de alarmas para minigranjas solares Unergy.

Adapted from mgs_alarms/alarm_engine.py for sync operation inside
the operations backend (Railway).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import pytz

from app.core.config import settings

tz = pytz.timezone(settings.TIMEZONE)

SOLAR_START_HOUR = 6
SOLAR_END_HOUR = 18

_MGS_EXTRA_PREFIXES = (
    "El Molino", "La Mesa", "Los Bongos", "Chiriguaná",
    "La Catedral", "San Pelayo", "Sol y Cielo", "Yuan Solar",
    "Agustín", "SIRIUS",
)

DEBOUNCE_POLLS = 4


def is_minigranja(node: dict) -> bool:
    cat = node.get("category", "")
    if cat not in ("ELECTRICAL_GENERATION", "BORDER"):
        return False
    name = node.get("name", "")
    if name.startswith("Minigranja") or name.startswith("MGS"):
        return True
    return any(name.startswith(p) for p in _MGS_EXTRA_PREFIXES)


def project_name(node_name: str) -> str:
    name = node_name
    for prefix in ("Minigranja Solar ", "Minigranja ", "MGS "):
        name = name.replace(prefix, "")
    name = re.sub(r"^\d{4}\s*-\s*", "", name)
    for suffix in (" Principal", " Respaldo", " principal", " respaldo", " Repaldo"):
        name = name.replace(suffix, "")
    name = name.strip()
    if name and name[0].islower():
        name = name[0].upper() + name[1:]
    return name


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class AlarmType(str, Enum):
    PLANTA_CAIDA = "PLANTA_CAIDA"
    SIN_GENERACION = "SIN_GENERACION"
    CORTE_ZONA = "CORTE_ZONA"
    INVERSORES_DEGRADADOS = "INVERSORES_DEGRADADOS"
    RECUPERACION = "RECUPERACION"


@dataclass
class Alarm:
    severity: Severity
    alarm_type: AlarmType
    node_name: str
    node_id: int
    category: str
    details: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz))


_STATUS_PRIORITY = {"OK": 0, "WARNING": 1, "ERROR": 2, "NO_DATA": 3}


def _group_by_project(nodes: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for node in nodes:
        if not is_minigranja(node):
            continue
        proj = project_name(node.get("name", ""))
        groups.setdefault(proj, []).append(node)

    virtual: list[dict] = []
    for proj, members in groups.items():
        best_status = "UNKNOWN"
        best_priority = 999
        max_eae = 0
        for m in members:
            s = m.get("status", "UNKNOWN")
            p = _STATUS_PRIORITY.get(s, 999)
            if p < best_priority:
                best_priority = p
                best_status = s
            eae = m.get("eae") or 0
            if eae > max_eae:
                max_eae = eae
        virtual.append({
            "name": proj, "id": 0, "status": best_status,
            "category": "ELECTRICAL_GENERATION", "eae": max_eae,
            "_project_key": proj, "_members": members,
        })
    return virtual


class AlarmEngine:
    def __init__(self):
        self.previous_states: dict[str, str] = {}
        self.bad_streak: dict[str, int] = {}
        self.active_alarms: dict[str, set[AlarmType]] = {}
        self.daily_stats: dict[str, int] = {
            "critical": 0, "warning": 0, "recoveries": 0,
        }
        self.no_gen_nodes: set[str] = set()

    def reset_daily_stats(self):
        self.daily_stats = {"critical": 0, "warning": 0, "recoveries": 0}
        self.no_gen_nodes.clear()

    def evaluate(self, nodes: list[dict]) -> list[Alarm]:
        alarms: list[Alarm] = []
        now = datetime.now(tz)
        is_solar = SOLAR_START_HOUR <= now.hour < SOLAR_END_HOUR

        projects = _group_by_project(nodes)

        if not is_solar:
            for proj in projects:
                key = proj["_project_key"]
                self.previous_states[key] = proj.get("status", "UNKNOWN")
                self.bad_streak.pop(key, None)
            return alarms

        fell_this_poll: list[dict] = []

        for proj in projects:
            key = proj["_project_key"]
            name = proj["name"]
            status = proj.get("status", "UNKNOWN")
            category = proj.get("category", "")
            prev = self.previous_states.get(key)
            proj_alarms = self.active_alarms.setdefault(key, set())
            is_bad = status in ("NO_DATA", "ERROR")

            if is_bad:
                self.bad_streak[key] = self.bad_streak.get(key, 0) + 1
            else:
                self.bad_streak.pop(key, None)

            # >= (no ==): si un sondeo se salta y el contador pasa de DEBOUNCE_POLLS
            # sin caer justo en el valor exacto, con == la alarma NUNCA dispararía
            # para una planta realmente caída. El guard `not in proj_alarms` de abajo
            # ya evita disparos duplicados, así que >= es seguro.
            if is_bad and self.bad_streak.get(key, 0) >= DEBOUNCE_POLLS:
                if AlarmType.PLANTA_CAIDA not in proj_alarms:
                    alarms.append(Alarm(
                        severity=Severity.CRITICAL,
                        alarm_type=AlarmType.PLANTA_CAIDA,
                        node_name=name, node_id=0, category=category,
                        details=f"Proyecto sin datos hace ~30 min (estado: {status})",
                    ))
                    proj_alarms.add(AlarmType.PLANTA_CAIDA)
                    self.daily_stats["critical"] += 1
                    fell_this_poll.append(proj)
            elif not is_bad:
                proj_alarms.discard(AlarmType.PLANTA_CAIDA)

            if status == "OK" and (proj.get("eae") or 0) == 0:
                if AlarmType.SIN_GENERACION not in proj_alarms:
                    alarms.append(Alarm(
                        severity=Severity.WARNING,
                        alarm_type=AlarmType.SIN_GENERACION,
                        node_name=name, node_id=0, category=category,
                        details=f"Medidor conectado pero sin generacion a las {now.strftime('%I:%M %p')}",
                    ))
                    proj_alarms.add(AlarmType.SIN_GENERACION)
                    self.daily_stats["warning"] += 1
                    self.no_gen_nodes.add(name)
            else:
                proj_alarms.discard(AlarmType.SIN_GENERACION)

            if prev in ("NO_DATA", "ERROR") and status in ("OK", "WARNING"):
                if AlarmType.PLANTA_CAIDA in proj_alarms or AlarmType.RECUPERACION not in proj_alarms:
                    alarms.append(Alarm(
                        severity=Severity.INFO,
                        alarm_type=AlarmType.RECUPERACION,
                        node_name=name, node_id=0, category=category,
                        details=f"Nuevamente operativo ({prev} -> {status})",
                    ))
                    proj_alarms.discard(AlarmType.PLANTA_CAIDA)
                    self.daily_stats["recoveries"] += 1

            self.previous_states[key] = status

        if len(fell_this_poll) >= 2:
            self._detect_zone_outage(alarms, fell_this_poll, projects)

        return alarms

    def _detect_zone_outage(
        self, alarms: list[Alarm], fell_nodes: list[dict], all_projects: list[dict],
    ):
        from app.services.mgs.grid_map import group_by_grid

        fell_proj_names = sorted({n["name"] for n in fell_nodes})
        all_proj_names = [p["name"] for p in all_projects]
        ok_proj_names = {
            p["name"] for p in all_projects
            if p.get("status") in ("OK", "WARNING")
        }
        already_grouped: set[str] = set()

        for level in ("circuito", "subestacion", "or"):
            all_groups = group_by_grid(all_proj_names, level)
            fell_groups = group_by_grid(fell_proj_names, level)

            for key, fell_members in fell_groups.items():
                if key == "?" or len(fell_members) < 2:
                    continue
                remaining = [m for m in fell_members if m not in already_grouped]
                if len(remaining) < 2:
                    continue
                neighbors = set(all_groups.get(key, []))
                if neighbors & ok_proj_names:
                    continue

                level_label = {
                    "circuito": "circuito", "subestacion": "subestacion",
                    "or": "operador de red",
                }[level]

                alarms[:] = [
                    a for a in alarms
                    if a.alarm_type != AlarmType.PLANTA_CAIDA or a.node_name not in remaining
                ]
                alarms.append(Alarm(
                    severity=Severity.CRITICAL,
                    alarm_type=AlarmType.CORTE_ZONA,
                    node_name=", ".join(remaining), node_id=0,
                    category="ELECTRICAL_GENERATION",
                    details=f"Posible corte de {level_label} '{key}': {len(remaining)} proyectos fuera de operacion",
                ))
                already_grouped.update(remaining)

    def get_summary(self, nodes: list[dict]) -> dict:
        projects = _group_by_project(nodes)
        counts = {"OK": 0, "WARNING": 0, "NO_DATA": 0, "ERROR": 0}
        project_list: list[dict] = []
        for proj in projects:
            s = proj.get("status", "UNKNOWN")
            if s in counts:
                counts[s] += 1
            project_list.append({
                "name": proj["name"], "status": s,
                "kwh": round(proj.get("eae") or 0),
            })
        return {
            "date": datetime.now(tz).strftime("%Y-%m-%d"),
            "time": datetime.now(tz).strftime("%I:%M %p"),
            "status_counts": counts,
            "projects": project_list,
            "total_projects": len(projects),
            "daily_critical": self.daily_stats["critical"],
            "daily_warning": self.daily_stats["warning"],
            "daily_recoveries": self.daily_stats["recoveries"],
        }
