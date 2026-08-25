import copy
import logging
import re
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.inicio_operacion import ProyectoInicioOperacion
from app.models.proyectos import Proyecto, ProyectoInversor, TipoProyectoEnum
from app.schemas.inicio_operacion import (
    InicioOperacionDetail, InicioOperacionFicha, InicioOperacionInversor,
    InicioOperacionListItem, InicioOperacionProyecto,
)
from app.services.drive_evidencia import eliminar_archivo, subir_archivo
from app.services.mgs.gaia_client import (
    GaiaClient, build_db_proyecto_frt_map, find_gaia_node_pair,
)
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("inicio_operacion")
router = APIRouter(prefix="/inicio-operacion", tags=["Inicio de Operación"])

# Ítems "legado" del checklist original: un string plano aprobado|rechazado|na,
# sin nota ni evidencia. Se mantienen tal cual — solo se agregó detalle a los
# 5 ítems que sí necesitaban revisión más fina (paneles, tracker, inversores,
# estación meteo, reconectador), ver claves nuevas más abajo.
_LEGACY_KEYS = [
    "cctv", "cable_solar", "cableado_mt_bt", "transformadores",
    "tableros", "shelter_skid", "obras_civiles", "doc_om",
]
_METEO_KEYS = [
    "instalacion", "en_plataforma", "reporta_datos",
    "poa", "temperatura_ambiente", "velocidad_viento", "direccion_viento",
]

_INVERSOR_SECCION_RE = re.compile(r"^inversor:(\d+):strings$")
# Secciones fijas donde se puede subir evidencia — ruta dentro del checklist +
# nombre de subcarpeta en Drive. La sección de inversores se resuelve aparte
# (ver _INVERSOR_SECCION_RE) porque su ruta depende del id del inversor.
_SECCIONES_EVIDENCIA = {
    "monitoreo:starlink": (["monitoreo", "starlink"], "evidencia", ["Monitoreo", "Starlink"]),
    "monitoreo:fusion_solar": (["monitoreo", "fusion_solar"], "evidencia", ["Monitoreo", "Fusion Solar"]),
    "frontera:principal": (["frontera", "principal"], "evidencia", ["Frontera", "Medidor Principal"]),
    "frontera:respaldo": (["frontera", "respaldo"], "evidencia", ["Frontera", "Medidor Respaldo"]),
    "estacion_meteo:reporta_datos": (["estacion_meteo", "reporta_datos"], "evidencia", ["Estación Meteorológica", "Reporta Datos"]),
    "reconectador:evidencia": (["reconectador"], "evidencia", ["Reconectador"]),
}


def _estado(item: dict | None) -> str | None:
    return (item or {}).get("estado")


def _progreso(checklist: dict | None, num_inversores: int) -> int:
    """% de ítems Aprobados sobre el total de ítems aplicables a ESTE proyecto.

    El total varía por proyecto: depende de cuántos inversores tiene y de si
    tiene reconectador. Fusion Solar y el estado global de Frontera no cuentan
    porque son calculados (no son trabajo pendiente propio, son un resumen).
    """
    checklist = checklist or {}
    total = 0
    aprobados = 0

    for k in _LEGACY_KEYS:
        total += 1
        if checklist.get(k) == "aprobado":
            aprobados += 1

    for k in ("paneles", "tracker"):
        total += 1
        if _estado(checklist.get(k)) == "aprobado":
            aprobados += 1

    total += num_inversores
    inv_items = ((checklist.get("inversores") or {}).get("items") or {})
    aprobados += sum(1 for it in inv_items.values() if (it or {}).get("strings_estado") == "aprobado")

    monitoreo = checklist.get("monitoreo") or {}
    total += 1
    if _estado(monitoreo.get("starlink")) == "aprobado":
        aprobados += 1
    total += 1
    if _estado((monitoreo.get("fusion_solar") or {}).get("datos_coherentes")) == "aprobado":
        aprobados += 1

    frontera = checklist.get("frontera") or {}
    for k in ("principal", "respaldo"):
        total += 1
        if _estado(frontera.get(k)) == "aprobado":
            aprobados += 1

    meteo = checklist.get("estacion_meteo") or {}
    for k in _METEO_KEYS:
        total += 1
        if _estado(meteo.get(k)) == "aprobado":
            aprobados += 1

    reconectador = checklist.get("reconectador") or {}
    if reconectador.get("tiene"):
        for k in ("en_plataforma", "calidad_datos"):
            total += 1
            if _estado(reconectador.get(k)) == "aprobado":
                aprobados += 1

    return round(aprobados / total * 100) if total else 0


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


def _resolve_seccion(checklist: dict, seccion: str, p: Proyecto) -> tuple[dict, str, list[str]]:
    """Ubica (creando si hace falta) el nodo del checklist donde va la evidencia
    de `seccion`, y devuelve (nodo, clave_de_evidencia, subcarpetas_drive)."""
    m = _INVERSOR_SECCION_RE.match(seccion)
    if m:
        inv_id = m.group(1)
        inversores = _inversores_solenium(p)
        nombre = next((i["nombre"] for i in inversores if str(i["id"]) == inv_id), None) or f"Inversor {inv_id}"
        items = checklist.setdefault("inversores", {}).setdefault("items", {})
        item = items.setdefault(inv_id, {})
        return item, "strings_evidencia", [nombre, "Strings"]

    cfg = _SECCIONES_EVIDENCIA.get(seccion)
    if not cfg:
        raise HTTPException(404, "Sección no reconocida")
    path, evidencia_key, carpeta = cfg
    node = checklist
    for key in path:
        node = node.setdefault(key, {})
    return node, evidencia_key, carpeta


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


def _ficha_de(f: ProyectoInicioOperacion | None, proyecto: Proyecto) -> InicioOperacionFicha:
    return InicioOperacionFicha(
        empresa_contratista=f.empresa_contratista if f else None,
        # Por defecto, prellenar inicio de operación con la fecha de entrada del proyecto.
        fecha_energizacion=f.fecha_energizacion if f else None,
        fecha_inicio_operacion=(f.fecha_inicio_operacion if f else None) or proyecto.fecha_entrada_operacion,
        checklist=(f.checklist if f else {}) or {},
        pruebas=(f.pruebas if f else {}) or {},
        documentos=(f.documentos if f else {}) or {},
        pendientes=(f.pendientes if f else []) or [],
    )


@router.get("/proyectos", response_model=list[InicioOperacionListItem])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Minigranjas en operación con servicio de operación, con su % de avance."""
    proyectos = (
        db.query(Proyecto)
        .filter(
            Proyecto.srv_operacion == True,  # noqa: E712
            Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
            Proyecto.estado == "en_operacion",
            Proyecto.deleted_at.is_(None),
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    fichas = {f.proyecto_id: f for f in db.query(ProyectoInicioOperacion).all()}
    inv_counts = dict(
        db.query(ProyectoInversor.proyecto_id, func.count(ProyectoInversor.id))
        .filter(ProyectoInversor.activo == True)  # noqa: E712
        .group_by(ProyectoInversor.proyecto_id)
        .all()
    )
    out = []
    for p in proyectos:
        f = fichas.get(p.id)
        out.append(InicioOperacionListItem(
            id=p.id,
            nombre_comercial=p.nombre_comercial,
            municipio=p.municipio,
            departamento=p.departamento,
            potencia_instalada_kwp=float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
            fecha_entrada_operacion=p.fecha_entrada_operacion,
            tiene_ficha=f is not None,
            progreso_pct=_progreso(f.checklist, inv_counts.get(p.id, 0)) if f else 0,
        ))
    return out


@router.get("/{proyecto_id}", response_model=InicioOperacionDetail)
def obtener(proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == proyecto_id).first()
    inversores = _inversores_solenium(p)
    checklist = f.checklist if f else {}
    return InicioOperacionDetail(
        proyecto=InicioOperacionProyecto.model_validate(p),
        ficha=_ficha_de(f, p),
        inversores=[InicioOperacionInversor(**i) for i in inversores],
        fusion_solar_estado=_fusion_solar_estado(checklist),
        frontera_estado=_frontera_estado(checklist),
        estacion_meteo_estado=_estacion_meteo_estado(checklist),
        reconectador_estado=_reconectador_estado(checklist),
        progreso_pct=_progreso(checklist, len(inversores)),
        reconectador_live=_reconectador_live(p),
        frontera_live=_frontera_live(p, db),
    )


@router.put("/{proyecto_id}", response_model=InicioOperacionDetail)
def guardar(
    proyecto_id: int,
    body: InicioOperacionFicha,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInicioOperacion(proyecto_id=proyecto_id)
        db.add(f)

    f.empresa_contratista = body.empresa_contratista
    f.fecha_energizacion = body.fecha_energizacion
    f.fecha_inicio_operacion = body.fecha_inicio_operacion
    f.checklist = body.checklist or {}
    f.pruebas = body.pruebas or {}
    f.documentos = body.documentos or {}
    f.pendientes = body.pendientes or []

    db.commit()
    db.refresh(f)
    inversores = _inversores_solenium(p)
    return InicioOperacionDetail(
        proyecto=InicioOperacionProyecto.model_validate(p),
        ficha=_ficha_de(f, p),
        inversores=[InicioOperacionInversor(**i) for i in inversores],
        fusion_solar_estado=_fusion_solar_estado(f.checklist),
        frontera_estado=_frontera_estado(f.checklist),
        estacion_meteo_estado=_estacion_meteo_estado(f.checklist),
        reconectador_estado=_reconectador_estado(f.checklist),
        progreso_pct=_progreso(f.checklist, len(inversores)),
        reconectador_live=_reconectador_live(p),
        frontera_live=_frontera_live(p, db),
    )


def _get_or_create_ficha(proyecto_id: int, db: Session) -> ProyectoInicioOperacion:
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInicioOperacion(proyecto_id=proyecto_id, checklist={})
        db.add(f)
        db.flush()
    return f, p


@router.post("/{proyecto_id}/archivos/{seccion}")
async def subir_evidencia(
    proyecto_id: int,
    seccion: str,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f, p = _get_or_create_ficha(proyecto_id, db)
    checklist = copy.deepcopy(f.checklist or {})
    nodo, evidencia_key, carpeta = _resolve_seccion(checklist, seccion, p)

    nuevo = await subir_archivo(archivo, [p.nombre_comercial, *carpeta])
    nodo.setdefault(evidencia_key, []).append(nuevo)

    f.checklist = checklist
    db.commit()
    return nuevo


@router.delete("/{proyecto_id}/archivos/{seccion}/{archivo_id}")
def eliminar_evidencia(
    proyecto_id: int,
    seccion: str,
    archivo_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f, p = _get_or_create_ficha(proyecto_id, db)
    checklist = copy.deepcopy(f.checklist or {})
    nodo, evidencia_key, _carpeta = _resolve_seccion(checklist, seccion, p)

    lista = nodo.get(evidencia_key) or []
    nueva_lista = [x for x in lista if x.get("id") != archivo_id]
    if len(nueva_lista) == len(lista):
        raise HTTPException(404, "Archivo no encontrado")

    eliminar_archivo(archivo_id)
    nodo[evidencia_key] = nueva_lista
    f.checklist = checklist
    db.commit()
    return {"status": "ok"}
