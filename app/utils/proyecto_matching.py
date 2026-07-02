"""
Matching entre nombres de proyectos externos (Excel / fallas-unergy / webhooks)
y los registros en la tabla proyectos.

Estrategia por orden de prioridad:
  1. Exacto (case-insensitive, sin tildes) sobre nombre_comercial, nombre_bitacora,
     nombre_clientes o alguno de los alias_monitoreo (separados por |)
  2. Solapamiento de tokens + similitud de texto -- misma cadena que se usó para
     reconciliar fronteras.proyecto_id contra producción (2026-07-02, ver
     scripts/cargar_fronteras_gescon.py): primero quita prefijos de ruido
     ("Minigranja Solar", "GD", "MGS", "Consumo Aux", etc.) para no confundir
     proyectos con nombres parecidos, y no acepta un match si el segundo mejor
     candidato queda casi tan bien como el primero (mejor no adivinar que
     adivinar mal). Reemplaza la coincidencia parcial + SequenceMatcher ≥ 0.75
     que tenía antes esta función, que no limpiaba esos prefijos y tomaba el
     score más alto sin chequear ambigüedad.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.models.proyectos import Proyecto


def _normalize(text: str) -> str:
    """Quita tildes, pone minúsculas, elimina caracteres no alfanuméricos."""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9\s]", " ", ascii_str.lower()).strip()


_MATCH_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "y", "en",
    "minigranja", "minigranjas", "mgs", "mgr", "gd", "planta", "granja",
    "solar", "sol", "cielo", "frontera", "proyecto",
    "consumo", "auxiliar", "aux", "propio", "serv", "ser", "generacion",
}
_MATCH_UMBRAL = 0.55
_MATCH_MARGEN_AMBIGUO = 0.05


def _core_tokens(nombre: str) -> set[str]:
    """Tokens significativos de un nombre (sin stopwords de ruido tipo
    'Minigranja Solar' / 'GD' / 'Consumo Aux')."""
    tokens = _normalize(nombre).split()
    return {t for t in tokens if t and t not in _MATCH_STOPWORDS}


def _score_nombre(nombre_a: str, nombres_b: list[str]) -> float:
    """Mejor score entre nombre_a y cualquiera de nombres_b: combina solapamiento
    de tokens (orden-independiente) con similitud de texto (tolera typos)."""
    tokens_a = _core_tokens(nombre_a)
    if not tokens_a:
        return 0.0
    mejor = 0.0
    for nb in nombres_b:
        if not nb:
            continue
        tokens_b = _core_tokens(nb)
        if not tokens_b:
            continue
        inter = tokens_a & tokens_b
        jaccard = len(inter) / len(tokens_a | tokens_b) if (tokens_a | tokens_b) else 0.0
        overlap = len(inter) / min(len(tokens_a), len(tokens_b))
        ratio = SequenceMatcher(
            None, " ".join(sorted(tokens_a)), " ".join(sorted(tokens_b))
        ).ratio()
        mejor = max(mejor, jaccard, overlap * 0.85, ratio)
    return round(mejor, 3)


def _all_names(proyecto: Proyecto) -> list[str]:
    names = [proyecto.nombre_comercial or ""]
    if proyecto.nombre_bitacora:
        names.append(proyecto.nombre_bitacora)
    if proyecto.nombre_clientes:
        names.append(proyecto.nombre_clientes)
    if proyecto.alias_monitoreo:
        for alias in proyecto.alias_monitoreo.split("|"):
            a = alias.strip()
            if a:
                names.append(a)
    return [n for n in names if n]


def find_proyecto_by_name(db: Session, nombre_externo: str) -> Proyecto | None:
    """Devuelve el Proyecto que mejor coincide con nombre_externo, o None."""
    if not nombre_externo or not nombre_externo.strip():
        return None

    proyectos = db.query(Proyecto).all()
    norm_ext = _normalize(nombre_externo)

    # 1. Coincidencia exacta normalizada
    for proy in proyectos:
        for name in _all_names(proy):
            if _normalize(name) == norm_ext:
                return proy

    # 2. Solapamiento de tokens + similitud, con desambiguación explícita: si el
    #    segundo mejor candidato queda muy cerca del primero, no se adivina.
    puntajes = sorted(
        ((proy, _score_nombre(nombre_externo, _all_names(proy))) for proy in proyectos),
        key=lambda x: -x[1],
    )
    if not puntajes:
        return None
    mejor_proy, mejor_score = puntajes[0]
    segundo_score = puntajes[1][1] if len(puntajes) > 1 else 0.0

    if mejor_score < _MATCH_UMBRAL:
        return None
    if (mejor_score - segundo_score) < _MATCH_MARGEN_AMBIGUO and segundo_score >= _MATCH_UMBRAL:
        return None  # ambiguo entre 2+ candidatos, mejor no adivinar

    return mejor_proy
