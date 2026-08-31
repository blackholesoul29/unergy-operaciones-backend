import logging
import re
import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.informe_om import ProyectoInformeOM
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.schemas.informe_om import (
    InformeOMDetail, InformeOMFicha, InformeOMKpis,
    InformeOMListItem, InformeOMProyecto,
)
from app.services.drive_evidencia import eliminar_archivo, subir_archivo
from app.services.mgs.gaia_client import (
    GaiaClient, build_db_proyecto_frt_map, find_gaia_node_pair,
)
from app.services.mgs.solenium_client import SoleniumClient

logger = logging.getLogger("informe_om")
router = APIRouter(prefix="/informe-om", tags=["Informe de Puesta en Marcha"])


# ── Checklist de comisionamiento -- 4 semáforos ─────────────────────────────
# Solo las 4 categorías que ya se resumían antes de la fusión 2026-08-31 (ver
# docstring de ProyectoInformeOM) -- el resto del catálogo viejo (CCTV,
# cableado, transformadores, tableros, shelter, obras civiles, paneles,
# trackers, checklist detallado por inversor) no se revive.

def _estado(item: dict | None) -> str | None:
    return (item or {}).get("estado")


def _fusion_solar_estado(c: dict | None) -> str:
    """Fusion Solar no se edita directo: aprueba solo si Starlink está aprobado,
    los datos se reportan coherentes, ningún inversor quedó marcado como
    limitado, y hay evidencia subida."""
    c = c or {}
    starlink_aprobado = _estado(c.get("starlink")) == "aprobado"
    datos_coherentes_aprobado = _estado(c.get("datos_coherentes")) == "aprobado"
    algun_limitado = any((inv or {}).get("limitado") for inv in (c.get("inversores") or []))
    tiene_evidencia = bool(c.get("evidencia"))
    if starlink_aprobado and datos_coherentes_aprobado and not algun_limitado and tiene_evidencia:
        return "aprobado"
    return "pendiente"


def _frontera_estado(c: dict | None) -> str:
    """Frontera aprueba solo si Medidor Principal Y Medidor Respaldo están
    aprobados, cada uno con su propia evidencia subida."""
    c = c or {}

    def _medidor_ok(clave: str) -> bool:
        item = c.get(clave) or {}
        return item.get("estado") == "aprobado" and bool(item.get("evidencia"))

    return "aprobado" if (_medidor_ok("principal") and _medidor_ok("respaldo")) else "pendiente"


_METEO_KEYS = [
    "instalacion", "en_plataforma", "reporta_datos",
    "poa", "temperatura_ambiente", "velocidad_viento", "direccion_viento",
]


def _estacion_meteo_estado(c: dict | None) -> str:
    """Estación meteo aprueba solo si TODOS sus ítems (instalación, en
    plataforma, reporta datos + las 4 variables) están aprobados; "reporta
    datos" además necesita su propia evidencia subida."""
    c = c or {}
    reporta = c.get("reporta_datos") or {}
    if reporta.get("estado") == "aprobado" and not reporta.get("evidencia"):
        return "pendiente"
    return "aprobado" if all(_estado(c.get(k)) == "aprobado" for k in _METEO_KEYS) else "pendiente"


def _reconectador_estado(c: dict | None) -> str:
    """Sin reconectador, siempre queda Pendiente. Con reconectador, aprueba
    solo si ambos ítems están aprobados y hay evidencia subida."""
    c = c or {}
    if not c.get("tiene"):
        return "pendiente"
    ok = (_estado(c.get("en_plataforma")) == "aprobado"
          and _estado(c.get("calidad_datos")) == "aprobado")
    return "aprobado" if (ok and bool(c.get("evidencia"))) else "pendiente"


# ── Datos en vivo -- Solenium / Gaia ────────────────────────────────────────

_solenium_client: SoleniumClient | None = None
_SOLENIUM_INV_CACHE: dict[str, tuple[float, list[dict]]] = {}
_SOLENIUM_INV_TTL = 60  # segundos


def _get_solenium() -> SoleniumClient | None:
    global _solenium_client
    if _solenium_client is None:
        _solenium_client = SoleniumClient()
    return _solenium_client if _solenium_client.enabled else None


_CAPACIDAD_DEV_NAME_RE = re.compile(r"^(\d+(?:\.\d+)?)")


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
    cada click dentro de la misma ficha.

    NOTA: sigue en Solenium, no SolarView -- la migración de esta fuente
    específica (fallback SolarView si hay project_id_solarview, si no
    Solenium) queda pendiente por separado, ver memoria de la migración."""
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


# ── Ficha / KPIs / detalle ───────────────────────────────────────────────────

def _kpis(f: ProyectoInformeOM | None) -> InformeOMKpis:
    pruebas = (f.protocolo_pruebas if f else []) or []
    eventos = (f.eventos_operativos if f else []) or []

    conformes = sum(1 for p in pruebas if (p or {}).get("resultado") == "conforme")
    no_conformes = sum(1 for p in pruebas if (p or {}).get("resultado") == "no_conforme")
    cerrados = sum(1 for e in eventos if (e or {}).get("estado") == "cerrada")
    abiertos_o_gestion = sum(1 for e in eventos if (e or {}).get("estado") in ("abierta", "en_gestion"))

    checklist_aprobados = sum(1 for estado in (
        _fusion_solar_estado(f.checklist_fusion_solar if f else None),
        _frontera_estado(f.checklist_frontera if f else None),
        _estacion_meteo_estado(f.checklist_estacion_meteo if f else None),
        _reconectador_estado(f.checklist_reconectador if f else None),
    ) if estado == "aprobado")

    estado_global = "atencion" if (no_conformes > 0 or abiertos_o_gestion > 0) else "operativo"

    return InformeOMKpis(
        pruebas_ejecutadas=len(pruebas),
        pruebas_conformes=conformes,
        pruebas_no_conformes=no_conformes,
        eventos_total=len(eventos),
        eventos_cerrados=cerrados,
        eventos_en_gestion=sum(1 for e in eventos if (e or {}).get("estado") == "en_gestion"),
        checklist_aprobados=checklist_aprobados,
        checklist_total=4,
        estado_global=estado_global,
    )


def _ficha_de(f: ProyectoInformeOM | None) -> InformeOMFicha:
    return InformeOMFicha(
        version=f.version if f else None,
        elaborado_por=(f.elaborado_por if f else None) or "Operaciones Unergy",
        actividad=(f.actividad if f else None) or "Puesta en marcha del sistema de monitoreo",
        estado=(f.estado if f else None) or "borrador",
        empresa_contratista=f.empresa_contratista if f else None,
        fecha_energizacion=f.fecha_energizacion if f else None,
        fecha_inicio_operacion=f.fecha_inicio_operacion if f else None,
        pendientes=(f.pendientes if f else []) or [],
        checklist_fusion_solar=(f.checklist_fusion_solar if f else {}) or {},
        checklist_frontera=(f.checklist_frontera if f else {}) or {},
        checklist_estacion_meteo=(f.checklist_estacion_meteo if f else {}) or {},
        checklist_reconectador=(f.checklist_reconectador if f else {}) or {},
        objetivo_alcance=(f.objetivo_alcance if f else {}) or {},
        datos_generales=(f.datos_generales if f else {}) or {},
        arquitectura_comunicacion=(f.arquitectura_comunicacion if f else {}) or {},
        equipos=(f.equipos if f else []) or [],
        variables_monitoreadas=(f.variables_monitoreadas if f else []) or [],
        configuracion_monitoreo=(f.configuracion_monitoreo if f else {}) or {},
        protocolo_pruebas=(f.protocolo_pruebas if f else []) or [],
        eventos_operativos=(f.eventos_operativos if f else []) or [],
        observaciones=(f.observaciones if f else {}) or {},
        recomendaciones=(f.recomendaciones if f else []) or [],
        conclusion=f.conclusion if f else None,
        firmas=(f.firmas if f else []) or [],
        evidencia_arquitectura=(f.evidencia_arquitectura if f else []) or [],
    )


def _evidencia_relacionada(f: ProyectoInformeOM | None) -> list[dict]:
    """Toda la evidencia ya subida (los 4 checklist de comisionamiento +
    Arquitectura de este informe), para que el Informe la muestre y el PDF
    la enlace -- sin volver a subir nada, es la misma evidencia."""
    items: list[dict] = []

    def _add(seccion: str, lista):
        for ev in (lista or []):
            if ev.get("url"):
                items.append({"seccion": seccion, "nombre": ev.get("nombre") or "Archivo", "url": ev["url"]})

    if not f:
        return items

    fusion_solar = f.checklist_fusion_solar or {}
    _add("Starlink", (fusion_solar.get("starlink") or {}).get("evidencia"))
    _add("Fusion Solar", fusion_solar.get("evidencia"))

    frontera = f.checklist_frontera or {}
    _add("Frontera — Medidor principal", (frontera.get("principal") or {}).get("evidencia"))
    _add("Frontera — Medidor de respaldo", (frontera.get("respaldo") or {}).get("evidencia"))

    meteo = f.checklist_estacion_meteo or {}
    _add("Estación meteorológica", (meteo.get("reporta_datos") or {}).get("evidencia"))

    _add("Reconectador", (f.checklist_reconectador or {}).get("evidencia"))
    _add("Arquitectura de comunicación", f.evidencia_arquitectura)

    return items


def _detail(p: Proyecto, f: ProyectoInformeOM | None, db: Session) -> InformeOMDetail:
    return InformeOMDetail(
        proyecto=InformeOMProyecto.model_validate(p),
        ficha=_ficha_de(f),
        kpis=_kpis(f),
        inversores=_inversores_solenium(p),
        fusion_solar_estado=_fusion_solar_estado(f.checklist_fusion_solar if f else None),
        frontera_estado=_frontera_estado(f.checklist_frontera if f else None),
        estacion_meteo_estado=_estacion_meteo_estado(f.checklist_estacion_meteo if f else None),
        reconectador_estado=_reconectador_estado(f.checklist_reconectador if f else None),
        frontera_live=_frontera_live(p, db),
        evidencia_relacionada=_evidencia_relacionada(f),
    )


@router.get("/proyectos", response_model=list[InformeOMListItem])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Minigranjas en operación con servicio de operación (mismo filtro que Inicio de Operación)."""
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
    fichas = {f.proyecto_id: f for f in db.query(ProyectoInformeOM).all()}
    out = []
    for p in proyectos:
        f = fichas.get(p.id)
        out.append(InformeOMListItem(
            id=p.id,
            nombre_comercial=p.nombre_comercial,
            municipio=p.municipio,
            departamento=p.departamento,
            potencia_instalada_kwp=float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
            tiene_ficha=f is not None,
            estado_global=_kpis(f).estado_global,
        ))
    return out


@router.get("/{proyecto_id}", response_model=InformeOMDetail)
def obtener(proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    return _detail(p, f, db)


@router.put("/{proyecto_id}", response_model=InformeOMDetail)
def guardar(
    proyecto_id: int,
    body: InformeOMFicha,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInformeOM(proyecto_id=proyecto_id)
        db.add(f)

    f.version = body.version
    f.elaborado_por = body.elaborado_por
    f.actividad = body.actividad
    f.estado = body.estado
    f.empresa_contratista = body.empresa_contratista
    f.fecha_energizacion = body.fecha_energizacion
    f.fecha_inicio_operacion = body.fecha_inicio_operacion
    f.pendientes = [item.model_dump() for item in body.pendientes]
    f.checklist_fusion_solar = body.checklist_fusion_solar.model_dump()
    f.checklist_frontera = body.checklist_frontera.model_dump()
    f.checklist_estacion_meteo = body.checklist_estacion_meteo.model_dump()
    f.checklist_reconectador = body.checklist_reconectador.model_dump()
    f.objetivo_alcance = body.objetivo_alcance or {}
    f.datos_generales = body.datos_generales or {}
    f.arquitectura_comunicacion = body.arquitectura_comunicacion or {}
    f.equipos = body.equipos or []
    f.variables_monitoreadas = body.variables_monitoreadas or []
    f.configuracion_monitoreo = body.configuracion_monitoreo or {}
    f.protocolo_pruebas = body.protocolo_pruebas or []
    f.eventos_operativos = body.eventos_operativos or []
    f.observaciones = body.observaciones or {}
    f.recomendaciones = body.recomendaciones or []
    f.conclusion = body.conclusion
    f.firmas = body.firmas or []
    f.evidencia_arquitectura = body.evidencia_arquitectura or []

    db.commit()
    db.refresh(f)
    return _detail(p, f, db)


def _get_or_create_ficha(proyecto_id: int, db: Session) -> tuple[ProyectoInformeOM, Proyecto]:
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInformeOM(proyecto_id=proyecto_id)
        db.add(f)
        db.flush()
    return f, p


def _ev_arquitectura(f): return f.evidencia_arquitectura or []
def _ev_arquitectura_set(f, lista): f.evidencia_arquitectura = lista


def _ev_fusion_solar(f): return (f.checklist_fusion_solar or {}).get("evidencia") or []
def _ev_fusion_solar_set(f, lista):
    f.checklist_fusion_solar = {**(f.checklist_fusion_solar or {}), "evidencia": lista}


def _ev_frontera_principal(f): return ((f.checklist_frontera or {}).get("principal") or {}).get("evidencia") or []
def _ev_frontera_principal_set(f, lista):
    c = dict(f.checklist_frontera or {})
    c["principal"] = {**(c.get("principal") or {}), "evidencia": lista}
    f.checklist_frontera = c


def _ev_frontera_respaldo(f): return ((f.checklist_frontera or {}).get("respaldo") or {}).get("evidencia") or []
def _ev_frontera_respaldo_set(f, lista):
    c = dict(f.checklist_frontera or {})
    c["respaldo"] = {**(c.get("respaldo") or {}), "evidencia": lista}
    f.checklist_frontera = c


def _ev_estacion_meteo(f): return ((f.checklist_estacion_meteo or {}).get("reporta_datos") or {}).get("evidencia") or []
def _ev_estacion_meteo_set(f, lista):
    c = dict(f.checklist_estacion_meteo or {})
    c["reporta_datos"] = {**(c.get("reporta_datos") or {}), "evidencia": lista}
    f.checklist_estacion_meteo = c


def _ev_reconectador(f): return (f.checklist_reconectador or {}).get("evidencia") or []
def _ev_reconectador_set(f, lista):
    f.checklist_reconectador = {**(f.checklist_reconectador or {}), "evidencia": lista}


# Secciones de evidencia válidas para POST/DELETE /{id}/archivos/{seccion} --
# cada una apunta a un campo (o subcampo anidado dentro de un JSONB) distinto
# de ProyectoInformeOM. "arquitectura" es la única que existía antes de la
# fusión con proyecto_inicio_operacion; las otras 5 son los 4 checklist de
# comisionamiento (frontera tiene 2, principal/respaldo).
_SECCIONES_EVIDENCIA = {
    "arquitectura": (_ev_arquitectura, _ev_arquitectura_set, "Arquitectura de comunicación"),
    "checklist-fusion-solar": (_ev_fusion_solar, _ev_fusion_solar_set, "Fusion Solar"),
    "checklist-frontera-principal": (_ev_frontera_principal, _ev_frontera_principal_set, "Frontera — Medidor principal"),
    "checklist-frontera-respaldo": (_ev_frontera_respaldo, _ev_frontera_respaldo_set, "Frontera — Medidor de respaldo"),
    "checklist-estacion-meteo": (_ev_estacion_meteo, _ev_estacion_meteo_set, "Estación meteorológica"),
    "checklist-reconectador": (_ev_reconectador, _ev_reconectador_set, "Reconectador"),
}


@router.post("/{proyecto_id}/archivos/{seccion}")
async def subir_evidencia(
    proyecto_id: int,
    seccion: str,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if seccion not in _SECCIONES_EVIDENCIA:
        raise HTTPException(404, "Sección de evidencia no reconocida")
    getter, setter, etiqueta = _SECCIONES_EVIDENCIA[seccion]
    f, p = _get_or_create_ficha(proyecto_id, db)
    nuevo = await subir_archivo(archivo, [p.nombre_comercial, etiqueta])
    setter(f, [*getter(f), nuevo])
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
    if seccion not in _SECCIONES_EVIDENCIA:
        raise HTTPException(404, "Sección de evidencia no reconocida")
    getter, setter, _etiqueta = _SECCIONES_EVIDENCIA[seccion]
    f, _p = _get_or_create_ficha(proyecto_id, db)
    lista = getter(f)
    nueva_lista = [x for x in lista if x.get("id") != archivo_id]
    if len(nueva_lista) == len(lista):
        raise HTTPException(404, "Archivo no encontrado")
    eliminar_archivo(archivo_id)
    setter(f, nueva_lista)
    db.commit()
    return {"status": "ok"}
