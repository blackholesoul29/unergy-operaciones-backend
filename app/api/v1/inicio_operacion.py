"""Este módulo YA NO expone una API propia -- la vista que la consumía se
retiró del frontend (commit 9ef45b1, 2026-08-21) y el router se desmontó de
app/api/v1/router.py (commit c5b00ca, mismo día). Se conserva solo por los
7 helpers que informe_om.py sí usa (los 4 semáforos derivados del checklist
de Inicio de Operación + los 3 de datos en vivo de Solenium/Gaia): borrar
este archivo tumbaría el arranque de la app. Ver también
app/models/inicio_operacion.py (ProyectoInicioOperacion se conserva por el
mismo motivo, con checklist/fecha_energizacion/fecha_inicio_operacion/
empresa_contratista/pendientes -- pruebas/documentos ya se eliminaron el
2026-08-27 por no tener ningún lector, ni aquí ni en informe_om.py)."""
import logging
import re
import time

from sqlalchemy.orm import Session

from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto
from app.services.mgs.gaia_client import (
    GaiaClient, build_db_proyecto_frt_map, find_gaia_node_pair,
)
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("inicio_operacion")

_METEO_KEYS = [
    "instalacion", "en_plataforma", "reporta_datos",
    "poa", "temperatura_ambiente", "velocidad_viento", "direccion_viento",
]


def _estado(item: dict | None) -> str | None:
    return (item or {}).get("estado")


def _fusion_solar_estado(checklist: dict | None) -> str:
    """Fusion Solar no se edita directo: aprueba solo si Starlink está aprobado,
    los datos se reportan coherentes, ningún inversor quedó marcado como
    limitado, y hay evidencia subida."""
    checklist = checklist or {}
    monitoreo = checklist.get("monitoreo") or {}
    fusion = monitoreo.get("fusion_solar") or {}
    starlink_aprobado = _estado(monitoreo.get("starlink")) == "aprobado"
    datos_coherentes_aprobado = _estado(fusion.get("datos_coherentes")) == "aprobado"
    inv_items = ((checklist.get("inversores") or {}).get("items") or {})
    algun_limitado = any((it or {}).get("limitado") for it in inv_items.values())
    tiene_evidencia = bool(fusion.get("evidencia"))
    if starlink_aprobado and datos_coherentes_aprobado and not algun_limitado and tiene_evidencia:
        return "aprobado"
    return "pendiente"


def _frontera_estado(checklist: dict | None) -> str:
    """Frontera aprueba solo si Medidor Principal Y Medidor Respaldo están
    aprobados, cada uno con su propia evidencia subida."""
    frontera = (checklist or {}).get("frontera") or {}

    def _medidor_ok(clave: str) -> bool:
        item = frontera.get(clave) or {}
        return item.get("estado") == "aprobado" and bool(item.get("evidencia"))

    return "aprobado" if (_medidor_ok("principal") and _medidor_ok("respaldo")) else "pendiente"


def _estacion_meteo_estado(checklist: dict | None) -> str:
    """Estación meteo aprueba solo si TODOS sus ítems (instalación, en
    plataforma, reporta datos + las 4 variables) están aprobados; "reporta
    datos" además necesita su propia evidencia subida."""
    meteo = (checklist or {}).get("estacion_meteo") or {}
    reporta = meteo.get("reporta_datos") or {}
    if reporta.get("estado") == "aprobado" and not reporta.get("evidencia"):
        return "pendiente"
    return "aprobado" if all(_estado(meteo.get(k)) == "aprobado" for k in _METEO_KEYS) else "pendiente"


def _reconectador_estado(checklist: dict | None) -> str:
    """Sin reconectador, siempre queda Pendiente. Con reconectador, aprueba
    solo si ambos ítems están aprobados y hay evidencia subida."""
    reconectador = (checklist or {}).get("reconectador") or {}
    if not reconectador.get("tiene"):
        return "pendiente"
    ok = (_estado(reconectador.get("en_plataforma")) == "aprobado"
          and _estado(reconectador.get("calidad_datos")) == "aprobado")
    return "aprobado" if (ok and bool(reconectador.get("evidencia"))) else "pendiente"


_solenium_client: SoleniumClient | None = None
_SOLENIUM_INV_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SOLENIUM_INV_TTL = 60  # segundos
_CAPACIDAD_DEV_NAME_RE = re.compile(r"^(\d+(?:\.\d+)?)")


def _get_solenium() -> SoleniumClient | None:
    global _solenium_client
    if _solenium_client is None:
        _solenium_client = SoleniumClient()
    return _solenium_client if _solenium_client.enabled else None


def _parse_capacidad_kw(dev_name: str | None) -> float | None:
    """Solenium no expone un campo de capacidad nominal — se aproxima leyendo
    el número inicial del nombre del dispositivo (ej. "330KTL-Inversor1" -> 330).
    Es una aproximación del modelo, puede no coincidir exacto con la ficha técnica."""
    if not dev_name:
        return None
    m = _CAPACIDAD_DEV_NAME_RE.match(dev_name)
    return float(m.group(1)) if m else None


def _inversores_solenium(p: Proyecto) -> list[dict]:
    """Inversores del proyecto según la API de Solenium (fuente en vivo),
    en vez de la tabla proyecto_inversores. Incluye potencia actual y estado,
    que la tabla no tiene. Cacheado brevemente para no golpear Solenium en
    cada click dentro de la misma ficha."""
    if not p.project_id_solenium:
        return []
    sol_id = str(p.project_id_solenium)
    cached = _SOLENIUM_INV_CACHE.get(sol_id)
    if cached and time.monotonic() - cached[0] < _SOLENIUM_INV_TTL:
        return cached[1]

    client = _get_solenium()
    if not client:
        return []
    try:
        raw = client.get_project_inverters(int(sol_id))
    except Exception:
        logger.warning("no se pudo obtener inversores de Solenium para proyecto_id=%d", p.id)
        return []

    inversores = [
        {
            "id": inv.get("id"),
            "nombre": inv.get("dev_name") or f"Inversor {inv.get('id')}",
            "potencia_nominal_kw": _parse_capacidad_kw(inv.get("dev_name")),
            "power_kw": inv.get("power"),
            "state": inv.get("state"),
        }
        for inv in raw if inv.get("id") is not None
    ]
    _SOLENIUM_INV_CACHE[sol_id] = (time.monotonic(), inversores)
    return inversores


_RECONECTADOR_LIVE_CACHE: dict[str, tuple[float, dict | None]] = {}
_RECONECTADOR_LIVE_TTL = 60  # segundos


def _reconectador_live(p: Proyecto) -> dict | None:
    """Telemetría en vivo del reconectador desde Solenium (`GET /relay/`, ya
    usado en `reconectadores.py`). None si el proyecto no tiene reconectador
    físico (Solenium responde 404) o no se pudo consultar."""
    if not p.project_id_solenium:
        return None
    sol_id = str(p.project_id_solenium)
    cached = _RECONECTADOR_LIVE_CACHE.get(sol_id)
    if cached and time.monotonic() - cached[0] < _RECONECTADOR_LIVE_TTL:
        return cached[1]

    client = _get_solenium()
    if not client:
        return None
    try:
        raw = client.get_relay(int(sol_id))
    except Exception:
        logger.warning("no se pudo obtener relay de Solenium para proyecto_id=%d", p.id)
        return None

    live = None
    if raw:
        r = raw.get("results") or {}
        live = {
            "activo": r.get("active"),
            "voltaje_a": r.get("u_a"), "voltaje_b": r.get("u_b"), "voltaje_c": r.get("u_c"),
            "corriente_a": r.get("i_a"), "corriente_b": r.get("i_b"), "corriente_c": r.get("i_c"),
            "frecuencia_hz": r.get("f_abc"),
            "factor_potencia": r.get("pf"),
            "potencia_kw": r.get("kw"),
            "ultima_actualizacion": r.get("time"),
        }
    _RECONECTADOR_LIVE_CACHE[sol_id] = (time.monotonic(), live)
    return live


_gaia_client: GaiaClient | None = None
_FRONTERA_LIVE_CACHE: dict[int, tuple[float, dict]] = {}
_FRONTERA_LIVE_TTL = 60  # segundos


def _get_gaia() -> GaiaClient | None:
    global _gaia_client
    if _gaia_client is None:
        _gaia_client = GaiaClient()
    return _gaia_client if _gaia_client.enabled else None


def _frontera_live(p: Proyecto, db: Session) -> dict:
    """Snapshot eléctrico en vivo de Gaia para el medidor principal y de
    respaldo (mismo patrón que `generacion_solar.py::project_monitoring_detail`).
    Devuelve {"principal": {...} | None, "respaldo": {...} | None}."""
    cached = _FRONTERA_LIVE_CACHE.get(p.id)
    if cached and time.monotonic() - cached[0] < _FRONTERA_LIVE_TTL:
        return cached[1]

    resultado = {"principal": None, "respaldo": None}
    gaia = _get_gaia()
    if not gaia:
        return resultado

    fronteras = db.query(Frontera.proyecto_id, Frontera.codigo_frontera).filter(
        Frontera.tipo_frontera.in_([TipoFronteraEnum.generacion, TipoFronteraEnum.generacion_consumo]),
        Frontera.codigo_frontera.isnot(None),
    ).all()
    frt_map = build_db_proyecto_frt_map(list(fronteras))
    node_principal, node_respaldo = find_gaia_node_pair(gaia=gaia, proyecto_id=p.id, db_proyecto_frt_map=frt_map)

    def _snapshot(node_id):
        if not node_id:
            return None
        try:
            s = gaia.get_node_electrical_snapshot(node_id)
        except Exception:
            logger.warning("no se pudo obtener snapshot de Gaia node_id=%s", node_id)
            return None
        if not s:
            return None
        eae_wh = s.get("eae_wh")
        return {
            "voltaje_v": [s.get("vp1"), s.get("vp2"), s.get("vp3")],
            "corriente_a": [s.get("cp1"), s.get("cp2"), s.get("cp3")],
            "potencia_activa_kw": s.get("ap_total"),
            "potencia_reactiva_kvar": s.get("rp_total"),
            "factor_potencia": s.get("pf_avg"),
            "energia_exportada_hoy_kwh": round(eae_wh / 1000, 2) if eae_wh is not None else None,
            "ultima_actualizacion": s.get("last_time"),
        }

    resultado = {"principal": _snapshot(node_principal), "respaldo": _snapshot(node_respaldo)}
    _FRONTERA_LIVE_CACHE[p.id] = (time.monotonic(), resultado)
    return resultado
