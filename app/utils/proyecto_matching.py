"""
Matching fuzzy entre nombres de proyectos externos (Excel / fallas-unergy)
y los registros en la tabla proyectos.

Estrategia por orden de prioridad:
  1. Exacto sobre nombre_comercial (case-insensitive)
  2. Exacto sobre alguno de los alias_monitoreo (separados por |)
  3. Exacto sobre nombre_bitacora o nombre_clientes (si existen)
  4. Coincidencia parcial: el término externo contiene nombre_comercial o viceversa
  5. Similitud SequenceMatcher ≥ 0.75 sobre nombre_comercial
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

    # Paso 1 y 2 y 3: coincidencia exacta normalizada
    for proy in proyectos:
        for name in _all_names(proy):
            if _normalize(name) == norm_ext:
                return proy

    # Paso 4: coincidencia parcial (uno contiene al otro)
    best_partial: Proyecto | None = None
    best_partial_len = 0
    for proy in proyectos:
        for name in _all_names(proy):
            norm_db = _normalize(name)
            if norm_ext in norm_db or norm_db in norm_ext:
                # preferir el match más largo (más específico)
                matched_len = max(len(norm_ext), len(norm_db))
                if matched_len > best_partial_len:
                    best_partial = proy
                    best_partial_len = matched_len

    if best_partial:
        return best_partial

    # Paso 5: similitud SequenceMatcher
    best_score = 0.0
    best_fuzzy: Proyecto | None = None
    for proy in proyectos:
        for name in _all_names(proy):
            score = SequenceMatcher(None, norm_ext, _normalize(name)).ratio()
            if score > best_score:
                best_score = score
                best_fuzzy = proy

    return best_fuzzy if best_score >= 0.75 else None
