import unicodedata
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.models.proyectos import Proyecto

_SIMILARITY_THRESHOLD = 0.75


def _normalize(s: str) -> str:
    """Lowercase, strip, remove accents — so 'Perijá' == 'perija'."""
    s = s.lower().strip()
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _candidates(p: Proyecto) -> list[str]:
    seen: set[str] = set()
    result = []
    for raw in [p.nombre_comercial, p.alias_monitoreo, p.sub_project, p.nombre_clientes, p.nombre_bitacora]:
        if raw:
            n = _normalize(raw)
            if n not in seen:
                seen.add(n)
                result.append(n)
    return result


def find_proyecto_by_name(db: Session, nombre: str) -> Proyecto | None:
    """Find a Proyecto by exact or fuzzy name match.
    Checks nombre_comercial, alias_monitoreo, sub_project, nombre_clientes, nombre_bitacora.
    Accent-insensitive."""
    if not nombre:
        return None

    norm = _normalize(nombre)
    proyectos = db.query(Proyecto).all()

    # 1. Exact match on any candidate field
    for p in proyectos:
        if norm in _candidates(p):
            return p

    # 2. Fuzzy match — best score across all candidate fields
    best: Proyecto | None = None
    best_score = 0.0
    for p in proyectos:
        for candidate in _candidates(p):
            score = SequenceMatcher(None, norm, candidate).ratio()
            if score > best_score:
                best_score = score
                best = p

    return best if best_score >= _SIMILARITY_THRESHOLD else None
