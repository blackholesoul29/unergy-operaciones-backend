"""Proyectos pendientes: fusiona Sun Factory + Quoia + Solenium contra la
tabla `proyectos`, y produce dos tipos de sugerencia -- nunca escribe solo:

  - "crear": el proyecto no tiene fila en absoluto.
  - "actualizar": el proyecto ya existe, pero una fuente externa contradice
    su `estado`/`fase_construccion` actual (ej. Sun Factory sigue diciendo
    "en construcción" mientras Quoia/Solenium ya lo ven generando), o le
    faltan datos (Potencia AC/Capacidad instalada) que la fuente sí tiene.

Cascada de confianza (nunca se auto-aplica, solo decide qué tan segura es
la sugerencia):
  1. Match exacto por ID/código -- sunfactory_project_id, origina_code/
     codigo_tsf, project_id_solenium, o fronteras.codigo_frontera ya
     vinculada a un proyecto.
  2. Sin match por ID, nombre normalizado (`_core`) coincide -- se sugiere
     igual, pero como "actualizar" (vincular), nunca como auto-match.
  3. Sin match en absoluto -- candidato genuino a "crear".
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto, ProyectoPendienteIgnorado
from app.services.mgs.gaia_client import GaiaClient, _get_dynamic_maps
from app.services.mgs.solenium_client import SoleniumClient
from app.services.tsf_sync import (
    _core, _derive_commercial_name, _parece_codigo,
    _sunfactory_all_projects, _sunfactory_token,
    _SF_IMPORT_STATES, _STATUS_TO_FASE,
)

# Sun Factory usa este listado para el propio edificio de Solenium y para
# proyectos ya dados de baja -- nunca son candidatos reales.
_EXCLUIR_NOMBRES = ("solenium piso",)
_EXCLUIR_PREFIJOS = ("deprecated",)


def _excluir_por_nombre(nombre: str) -> bool:
    n = (nombre or "").strip().lower()
    return any(n.startswith(p) for p in _EXCLUIR_PREFIJOS) or any(x in n for x in _EXCLUIR_NOMBRES)


def _coord_valida(lat, lon) -> bool:
    """Filtra coordenadas placeholder de las fuentes (ej. -1,-1 o 0,0 como
    "sin dato", visto en Solenium) -- Colombia continental cae aprox. en
    lat [-5, 16], lon [-82, -65]."""
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if lat == lon:
        return False
    return -5 <= lat <= 16 and -82 <= lon <= -65


@dataclass
class _Candidato:
    fuentes: set[str] = field(default_factory=set)
    nombre_raw: str = ""
    core: str = ""
    municipio: str | None = None
    departamento: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    tipo_proyecto: str | None = None
    fase_construccion: str | None = None
    estado_sugerido: str | None = None
    potencia_ac_kw: float | None = None
    capacidad_instalada_kwp: float | None = None
    sub_project: str | None = None
    project_id_solenium: str | None = None
    origina_code: str | None = None
    codigo_tsf: str | None = None
    sunfactory_project_id: int | None = None
    proyecto_id: int | None = None  # si ya se resolvió contra uno existente
    # Solo lo llena _candidatos_quoia -- generación real sostenida varios días
    # (no solo el último reportado). Se exige cuando el candidato NO tiene
    # corroboración de Sun Factory/Solenium (ver resolver_pendientes).
    generacion_multidia: bool = False


def _tsf_code_from_base_name(base_name: str | None) -> str | None:
    if not base_name:
        return None
    prefix = base_name.split("_", 1)[0]
    return prefix if re.match(r"^COL[A-Z0-9]+$", prefix) else None


def _candidatos_sunfactory() -> list[_Candidato]:
    """Todos los estados (no solo el pipeline de construcción) -- para
    /proyectos/pendientes nos interesa tanto lo que sigue en obra como lo
    que Sun Factory ya marcó como operando, no solo lo primero."""
    try:
        token = _sunfactory_token()
    except Exception:
        token = None
    if not token:
        return []
    try:
        raw = _sunfactory_all_projects(token)
    except Exception:
        return []

    out = []
    for p in raw:
        nombre = (p.get("name") or "").strip()
        if not nombre or _excluir_por_nombre(nombre):
            continue
        state = p.get("state")
        if state == 5:  # Debida diligencia -- demasiado temprano, ni prospecto confirmado
            continue
        base_name = p.get("base_name")
        lat, lon = p.get("lat"), p.get("lon")
        c = _Candidato(
            fuentes={"sunfactory"},
            nombre_raw=nombre if not _parece_codigo(nombre) else _derive_commercial_name(base_name or nombre),
            municipio=p.get("city"),
            departamento=p.get("department"),
            latitud=lat if _coord_valida(lat, lon) else None,
            longitud=lon if _coord_valida(lat, lon) else None,
            tipo_proyecto="minigranja" if p.get("is_minifarm") else "autoconsumo",
            origina_code=base_name,
            codigo_tsf=_tsf_code_from_base_name(base_name),
            sunfactory_project_id=p.get("id"),
        )
        if state == 2:
            c.estado_sugerido = "en_operacion"
            c.fase_construccion = "energizado"
        elif state in _SF_IMPORT_STATES:
            c.fase_construccion = _STATUS_TO_FASE.get(_SF_IMPORT_STATES[state])
        c.core = _core(c.nombre_raw)
        out.append(c)
    return out


def _nodo_tiene_generacion(gaia: GaiaClient, node_id: int | None, node_id_resp: int | None, fecha: str) -> bool:
    """True si el medidor (principal o respaldo, por node_id) reportó energía
    real (eae > 0) ese día.

    Por nodo, NO por frt_code: `/border/{frt}/measurements/` da 400 para
    algunos borders -- caso real "El Paso Norte" (Quoia lo tiene bajo otro
    `company`) -- mientras que por nodo funciona siempre y coincide con lo
    que muestra el dashboard de Quoia."""
    for nid in (node_id, node_id_resp):
        if nid is None:
            continue
        try:
            rows = gaia.get_node_measurements(nid, fecha, "eae")
        except Exception:
            continue
        total = 0.0
        for r in rows:
            for f in ("eaepd1", "eaepd2", "eaepd3"):
                v = r.get(f)
                if v is not None:
                    try:
                        total += float(v)
                    except (TypeError, ValueError):
                        pass
        if total > 0:
            return True
    return False


# Cache de "¿generación real?" por frt_code -- evita repetir ~66 llamadas de
# medición en paralelo en cada GET /proyectos/pendientes (se llama también
# desde confirmar/ignorar). Mismo TTL que _get_dynamic_maps en gaia_client.
_generacion_real_cache: dict[str, bool] | None = None
_generacion_real_cache_ts: float = 0.0
_GENERACION_REAL_CACHE_TTL = 3600  # segundos


def _generacion_real_por_frt(gaia: GaiaClient, borders: list[dict]) -> dict[str, bool]:
    global _generacion_real_cache, _generacion_real_cache_ts
    now = time.monotonic()
    if _generacion_real_cache is not None and (now - _generacion_real_cache_ts) < _GENERACION_REAL_CACHE_TTL:
        return _generacion_real_cache

    dynamic = _get_dynamic_maps(gaia) or {}
    frt_a_nodos = dynamic.get("frt") or {}

    con_reporte = [
        ((b.get("frt_generation") or {}).get("frt_code", "").strip().lower(),
         (b.get("frt_generation") or {}).get("last_report_date"))
        for b in borders
        if (b.get("frt_generation") or {}).get("last_report_date")
    ]
    resultado: dict[str, bool] = {}
    if con_reporte:
        with ThreadPoolExecutor(max_workers=min(len(con_reporte), 12)) as pool:
            def _check(item):
                code, fecha = item
                node_p, node_r = frt_a_nodos.get(code, (None, None))
                return code, _nodo_tiene_generacion(gaia, node_p, node_r, fecha)
            for code, tiene in pool.map(_check, con_reporte):
                resultado[code] = tiene

    _generacion_real_cache = resultado
    _generacion_real_cache_ts = now
    return resultado


# Cache de "¿generación sostenida varios días?" -- más caro que el de 1 día
# (repite la medición por N días), así que solo se calcula para los frt_code
# que YA pasaron el chequeo de 1 día (subconjunto chico). Mismo TTL.
_generacion_multidia_cache: dict[str, bool] | None = None
_generacion_multidia_cache_ts: float = 0.0
_DIAS_GENERACION_SOSTENIDA = 3


def _generacion_real_multidia_por_frt(
    gaia: GaiaClient, frt_codes: list[str],
) -> dict[str, bool]:
    """Como `_generacion_real_por_frt`, pero exige generación real en los
    últimos `_DIAS_GENERACION_SOSTENIDA` días completos (no el día de hoy,
    que puede estar parcial) -- una sola lectura aislada (prueba/calibración
    de un proyecto recién comisionado) no basta para considerar que ya opera
    de verdad. Caso real 2026-07-10: Garza/La Perdiz/Taurus VIII-X pasaban el
    chequeo de 1 día, pero ese mismo día, revisado después, mostraba
    generación real en cero -- solo se sostuvo un día aislado."""
    global _generacion_multidia_cache, _generacion_multidia_cache_ts
    now = time.monotonic()
    if _generacion_multidia_cache is not None and (now - _generacion_multidia_cache_ts) < _GENERACION_REAL_CACHE_TTL:
        return _generacion_multidia_cache

    dynamic = _get_dynamic_maps(gaia) or {}
    frt_a_nodos = dynamic.get("frt") or {}
    hoy = date.today()
    fechas = [(hoy - timedelta(days=i)).isoformat() for i in range(1, _DIAS_GENERACION_SOSTENIDA + 1)]

    resultado: dict[str, bool] = {}
    codigos = [c for c in frt_codes if c]
    if codigos:
        with ThreadPoolExecutor(max_workers=min(len(codigos), 12)) as pool:
            def _check(code):
                node_p, node_r = frt_a_nodos.get(code, (None, None))
                sostenida = all(_nodo_tiene_generacion(gaia, node_p, node_r, f) for f in fechas)
                return code, sostenida
            for code, tiene in pool.map(_check, codigos):
                resultado[code] = tiene

    _generacion_multidia_cache = resultado
    _generacion_multidia_cache_ts = now
    return resultado


def _candidatos_quoia(fronteras_vinculadas: dict[str, int]) -> list[_Candidato]:
    gaia = GaiaClient()
    if not gaia.enabled:
        return []
    try:
        borders = gaia.get_all_borders()
    except Exception:
        return []
    generacion_real = _generacion_real_por_frt(gaia, borders)
    # Multi-día solo para los que ya pasaron el de 1 día -- subconjunto chico,
    # evita multiplicar por 3 las llamadas de medición para todo el pipeline.
    codigos_1dia = [code for code, tiene in generacion_real.items() if tiene]
    generacion_multidia = _generacion_real_multidia_por_frt(gaia, codigos_1dia)

    out = []
    for b in borders:
        nombre = (b.get("name") or "").strip()
        if not nombre or _excluir_por_nombre(nombre):
            continue
        gen = b.get("frt_generation") or {}
        cons = b.get("frt_consumption") or {}
        frt_gen_code = (gen.get("frt_code") or "").strip().lower()
        frt_cons_code = (cons.get("frt_code") or "").strip().lower()

        # Ya vinculado a un proyecto vía fronteras.codigo_frontera -- match
        # directo, no hace falta adivinar por nombre.
        proyecto_id = fronteras_vinculadas.get(frt_gen_code) or fronteras_vinculadas.get(frt_cons_code)

        cap_mw = gen.get("installed_capacity")
        c = _Candidato(
            fuentes={"quoia"},
            nombre_raw=nombre,
            tipo_proyecto="minigranja" if re.match(r"^(mgs|minigranja)\b", nombre, re.IGNORECASE) else (
                "gd" if nombre.upper().startswith("GD ") else None
            ),
            potencia_ac_kw=(float(cap_mw) * 1000) if cap_mw else None,
            proyecto_id=proyecto_id,
        )
        # Exige generación real (eae > 0), no solo que el medidor esté
        # registrado y reportando -- ver _tiene_generacion_real.
        if gen.get("last_report_date") and generacion_real.get(frt_gen_code):
            c.estado_sugerido = "en_operacion"
            c.fase_construccion = "energizado"
            c.generacion_multidia = generacion_multidia.get(frt_gen_code, False)
        c.core = _core(c.nombre_raw)
        out.append(c)
    return out


def _candidatos_solenium() -> list[_Candidato]:
    client = SoleniumClient()
    if not client.enabled:
        return []
    try:
        raw = client.get_projects()
    except Exception:
        return []

    out = []
    for p in raw:
        nombre = (p.get("name") or "").strip()
        if not nombre or _excluir_por_nombre(nombre):
            continue
        cap = p.get("installed_capacity")
        try:
            cap_val = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            cap_val = None  # "Desconocida"

        if p.get("is_minifarm"):
            tipo = "minigranja"
        elif p.get("is_self_consumption"):
            tipo = "autoconsumo"
        else:
            tipo = None  # ambiguo -- que lo decida quien confirma

        lat, lon = p.get("lat"), p.get("lon")
        c = _Candidato(
            fuentes={"solenium"},
            nombre_raw=nombre,
            latitud=lat if _coord_valida(lat, lon) else None,
            longitud=lon if _coord_valida(lat, lon) else None,
            tipo_proyecto=tipo,
            capacidad_instalada_kwp=cap_val,
            project_id_solenium=str(p["id"]) if p.get("id") is not None else None,
            estado_sugerido="en_operacion",
            fase_construccion="energizado",
        )
        c.core = _core(c.nombre_raw)
        out.append(c)
    return out


def _fusionar_por_core(candidatos: list[_Candidato]) -> list[_Candidato]:
    """Combina candidatos de distintas fuentes que refieren al mismo
    proyecto real (mismo `core`), sin pisar campos ya llenados.

    Excepción: `fase_construccion`/`estado_sugerido` -- "energizado"/
    "en_operacion" (evidencia real de Quoia: generación medida, no solo el
    medidor registrado) SIEMPRE gana, sin importar el orden de llegada.
    Bug real encontrado 2026-07-09: Sun Factory siempre trae algún
    fase_construccion (aunque esté desactualizado, ej. "en_construccion"),
    y como sus candidatos suelen llegar primero en la lista, el "no pisar
    si ya tiene valor" dejaba la fase vieja de Sun Factory ganando sobre la
    señal real de Quoia -- proyectos que ya generan de verdad (El Paso
    Norte, Chiriguaná Norte 2, etc.) nunca se sugerían para actualizar."""
    por_core: dict[str, _Candidato] = {}
    for c in candidatos:
        if len(c.core) < 3:
            continue
        existente = por_core.get(c.core)
        if existente is None:
            por_core[c.core] = c
            continue
        existente.fuentes |= c.fuentes
        # "energizado"/"en_operacion" siempre gana; si no, se rellena el
        # hueco como cualquier otro campo (primero que llegue, sin pisar).
        if c.fase_construccion == "energizado":
            existente.fase_construccion = "energizado"
        elif existente.fase_construccion is None and c.fase_construccion is not None:
            existente.fase_construccion = c.fase_construccion
        if c.estado_sugerido == "en_operacion":
            existente.estado_sugerido = "en_operacion"
        elif existente.estado_sugerido is None and c.estado_sugerido is not None:
            existente.estado_sugerido = c.estado_sugerido
        existente.generacion_multidia = existente.generacion_multidia or c.generacion_multidia
        for campo in (
            "municipio", "departamento", "latitud", "longitud", "tipo_proyecto",
            "potencia_ac_kw", "capacidad_instalada_kwp", "sub_project",
            "project_id_solenium", "origina_code", "codigo_tsf",
            "sunfactory_project_id", "proyecto_id",
        ):
            if getattr(existente, campo) is None and getattr(c, campo) is not None:
                setattr(existente, campo, getattr(c, campo))
    return list(por_core.values())


def _reforzar_solo_quoia(candidatos: list[_Candidato]) -> None:
    """Sin corroboración de Sun Factory/Solenium (el candidato viene solo de
    Quoia), exige generación sostenida varios días, no solo el último
    reportado -- caso real 2026-07-10: Garza/La Perdiz/Taurus VIII-X se
    confirmaron como "en operación" con evidencia de un solo día que resultó
    ser aislada (prueba/calibración), sin que ninguna otra fuente respaldara
    la sugerencia. Muta `candidatos` in-place."""
    for c in candidatos:
        if c.fuentes == {"quoia"} and c.estado_sugerido == "en_operacion" and not c.generacion_multidia:
            c.estado_sugerido = None
            c.fase_construccion = None


def resolver_pendientes(db: Session) -> list[dict]:
    proyectos = db.query(
        Proyecto.id, Proyecto.nombre_comercial, Proyecto.estado, Proyecto.fase_construccion,
        Proyecto.origina_code, Proyecto.codigo_tsf, Proyecto.sunfactory_project_id,
        Proyecto.sub_project, Proyecto.project_id_solenium,
    ).filter(Proyecto.deleted_at.is_(None)).all()

    por_sunfactory_id = {p.sunfactory_project_id: p for p in proyectos if p.sunfactory_project_id is not None}
    por_origina_code = {(p.origina_code or "").upper(): p for p in proyectos if p.origina_code}
    por_codigo_tsf = {(p.codigo_tsf or "").upper(): p for p in proyectos if p.codigo_tsf}
    por_solenium_id = {p.project_id_solenium: p for p in proyectos if p.project_id_solenium}
    por_core = {}
    for p in proyectos:
        core = _core(p.nombre_comercial)
        if len(core) >= 3:
            por_core.setdefault(core, p)

    fronteras_vinculadas = {
        (codigo or "").lower(): proyecto_id
        for codigo, proyecto_id in db.query(Frontera.codigo_frontera, Frontera.proyecto_id)
        .filter(Frontera.proyecto_id.isnot(None), Frontera.codigo_frontera.isnot(None))
        .all()
    }

    ignorados = {row[0] for row in db.query(ProyectoPendienteIgnorado.clave).all()}

    crudos = (
        _candidatos_sunfactory()
        + _candidatos_quoia(fronteras_vinculadas)
        + _candidatos_solenium()
    )
    candidatos = _fusionar_por_core(crudos)
    _reforzar_solo_quoia(candidatos)

    pendientes: list[dict] = []
    vistos_proyecto_id: set[int] = set()

    for c in candidatos:
        match = None
        # 1. Match exacto por ID/código.
        if c.sunfactory_project_id is not None:
            match = por_sunfactory_id.get(c.sunfactory_project_id)
        if match is None and c.origina_code:
            match = por_origina_code.get(c.origina_code.upper())
        if match is None and c.codigo_tsf:
            match = por_codigo_tsf.get(c.codigo_tsf.upper())
        if match is None and c.project_id_solenium:
            match = por_solenium_id.get(c.project_id_solenium)
        if match is None and c.proyecto_id:
            match = next((p for p in proyectos if p.id == c.proyecto_id), None)

        confianza = "id"
        # 2. Sin match por ID -- probar nombre normalizado.
        if match is None:
            match = por_core.get(c.core)
            confianza = "nombre" if match else "id"

        clave = f"core:{c.core}"
        if clave in ignorados:
            continue

        if match is not None:
            if match.id in vistos_proyecto_id:
                continue
            necesita_actualizar = (
                (c.estado_sugerido == "en_operacion" and match.estado != "en_operacion")
                or (
                    c.fase_construccion
                    and match.fase_construccion != c.fase_construccion
                    # Nunca sugerir que un proyecto YA "energizado" regrese a
                    # una fase de obra anterior -- mismo bug que el de
                    # sync_tsf_projects: Sun Factory puede seguir trayendo un
                    # status de obra desactualizado para un proyecto que ya
                    # se confirmó operando (caso real 2026-07-09: "Chima
                    # Oriente"/"Chiriguana N1"/"Valencia Oriente 1" ya estaban
                    # en energizado y esto los sugería de vuelta a
                    # en_construccion).
                    and match.fase_construccion != "energizado"
                )
                or (confianza == "nombre")  # vínculo sin confirmar todavía
            )
            if not necesita_actualizar:
                continue
            vistos_proyecto_id.add(match.id)
            pendientes.append({
                "clave": clave,
                "tipo_sugerencia": "actualizar",
                "confianza": confianza,
                "fuentes": sorted(c.fuentes),
                "proyecto_id": match.id,
                "proyecto_nombre_actual": match.nombre_comercial,
                "nombre_sugerido": c.nombre_raw,
                "estado_actual": match.estado,
                "estado_sugerido": c.estado_sugerido,
                "fase_construccion_actual": match.fase_construccion,
                "fase_construccion_sugerida": c.fase_construccion,
                "tipo_proyecto_sugerido": c.tipo_proyecto,
                "municipio": c.municipio,
                "departamento": c.departamento,
                "latitud": c.latitud,
                "longitud": c.longitud,
                "potencia_ac_kw": c.potencia_ac_kw,
                "capacidad_instalada_kwp": c.capacidad_instalada_kwp,
                "sub_project": c.sub_project,
                "project_id_solenium": c.project_id_solenium,
                "origina_code": c.origina_code,
                "codigo_tsf": c.codigo_tsf,
                "sunfactory_project_id": c.sunfactory_project_id,
            })
        else:
            pendientes.append({
                "clave": clave,
                "tipo_sugerencia": "crear",
                "confianza": "sin_match",
                "fuentes": sorted(c.fuentes),
                "proyecto_id": None,
                "proyecto_nombre_actual": None,
                "nombre_sugerido": c.nombre_raw,
                "estado_actual": None,
                "estado_sugerido": c.estado_sugerido or "en_desarrollo",
                "fase_construccion_actual": None,
                "fase_construccion_sugerida": c.fase_construccion,
                "tipo_proyecto_sugerido": c.tipo_proyecto,
                "municipio": c.municipio,
                "departamento": c.departamento,
                "latitud": c.latitud,
                "longitud": c.longitud,
                "potencia_ac_kw": c.potencia_ac_kw,
                "capacidad_instalada_kwp": c.capacidad_instalada_kwp,
                "sub_project": c.sub_project,
                "project_id_solenium": c.project_id_solenium,
                "origina_code": c.origina_code,
                "codigo_tsf": c.codigo_tsf,
                "sunfactory_project_id": c.sunfactory_project_id,
            })

    return pendientes


def backfill_ubicacion(db: Session, dry_run: bool = True) -> dict:
    """Completa latitud/longitud/municipio/departamento en proyectos que ya
    existen pero les falta ese dato, cruzando contra Sun Factory y Solenium
    (Quoia no trae coordenadas). Match por vínculo directo (ID/código) primero;
    si no hay vínculo, por nombre normalizado (`_core`). Nunca pisa un valor
    ya diligenciado."""
    proyectos = db.query(Proyecto).filter(Proyecto.deleted_at.is_(None)).all()

    por_sunfactory_id = {p.sunfactory_project_id: p for p in proyectos if p.sunfactory_project_id is not None}
    por_origina_code = {(p.origina_code or "").upper(): p for p in proyectos if p.origina_code}
    por_codigo_tsf = {(p.codigo_tsf or "").upper(): p for p in proyectos if p.codigo_tsf}
    por_solenium_id = {p.project_id_solenium: p for p in proyectos if p.project_id_solenium}
    por_core = {}
    for p in proyectos:
        core = _core(p.nombre_comercial)
        if len(core) >= 3:
            por_core.setdefault(core, p)

    candidatos = _fusionar_por_core(_candidatos_sunfactory() + _candidatos_solenium())

    actualizados = []
    vistos: set[int] = set()
    for c in candidatos:
        if c.latitud is None and c.longitud is None and not c.municipio and not c.departamento:
            continue  # nada que aportar

        match = None
        if c.sunfactory_project_id is not None:
            match = por_sunfactory_id.get(c.sunfactory_project_id)
        if match is None and c.origina_code:
            match = por_origina_code.get(c.origina_code.upper())
        if match is None and c.codigo_tsf:
            match = por_codigo_tsf.get(c.codigo_tsf.upper())
        if match is None and c.project_id_solenium:
            match = por_solenium_id.get(c.project_id_solenium)
        if match is None:
            match = por_core.get(c.core)

        if match is None or match.id in vistos:
            continue

        cambios = {}
        if match.latitud is None and c.latitud is not None:
            cambios["latitud"] = c.latitud
        if match.longitud is None and c.longitud is not None:
            cambios["longitud"] = c.longitud
        if not match.municipio and c.municipio:
            cambios["municipio"] = c.municipio
        if not match.departamento and c.departamento:
            cambios["departamento"] = c.departamento

        if cambios:
            vistos.add(match.id)
            actualizados.append({"id": match.id, "nombre": match.nombre_comercial, "cambios": cambios})
            if not dry_run:
                for campo, valor in cambios.items():
                    setattr(match, campo, valor)

    if not dry_run and actualizados:
        db.commit()

    return {
        "dry_run": dry_run,
        "total_candidatos": len(candidatos),
        "actualizados": len(actualizados),
        "detalle": actualizados,
    }
