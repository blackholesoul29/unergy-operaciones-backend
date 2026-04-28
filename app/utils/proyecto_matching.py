from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.models.proyectos import Proyecto

_SIMILARITY_THRESHOLD = 0.75


def _normalize(s: str) -> str:
    return s.lower().strip()


def find_proyecto_by_name(db: Session, nombre: str) -> Proyecto | None:
    """Find a Proyecto by exact or fuzzy name match against nombre_comercial and alias_monitoreo."""
    if not nombre:
        return None

    norm = _normalize(nombre)

    proyectos = db.query(Proyecto).all()

    # 1. Exact match against nombre_comercial
    for p in proyectos:
        if _normalize(p.nombre_comercial) == norm:
            return p

    # 2. Exact match against alias_monitoreo
    for p in proyectos:
        if p.alias_monitoreo and _normalize(p.alias_monitoreo) == norm:
            return p

    # 3. Fuzzy match (best score above threshold)
    best: Proyecto | None = None
    best_score = 0.0
    for p in proyectos:
        candidates = [_normalize(p.nombre_comercial)]
        if p.alias_monitoreo:
            candidates.append(_normalize(p.alias_monitoreo))
        for candidate in candidates:
            score = SequenceMatcher(None, norm, candidate).ratio()
            if score > best_score:
                best_score = score
                best = p

    return best if best_score >= _SIMILARITY_THRESHOLD else None
