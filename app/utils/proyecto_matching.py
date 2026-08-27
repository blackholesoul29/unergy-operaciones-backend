"""
Matching entre nombres de proyectos externos (Excel / fallas-unergy / webhooks)
y los registros en la tabla proyectos.

Estrategia por orden de prioridad:
  1. Exacto (case-insensitive, sin tildes) sobre nombre_comercial
  2. app.utils.nombre_matching.mejor_candidato() -- ver ese módulo para el detalle
     del algoritmo (compartido con scripts/cargar_fronteras_gescon.py).
"""
from sqlalchemy.orm import Session
from app.models.proyectos import Proyecto
from app.utils.nombre_matching import normalizar, mejor_candidato


def _all_names(proyecto: Proyecto) -> list[str]:
    return [proyecto.nombre_comercial] if proyecto.nombre_comercial else []


def find_proyecto_by_name(db: Session, nombre_externo: str) -> Proyecto | None:
    """Devuelve el Proyecto que mejor coincide con nombre_externo, o None."""
    if not nombre_externo or not nombre_externo.strip():
        return None

    proyectos = db.query(Proyecto).all()
    norm_ext = normalizar(nombre_externo)

    # 1. Coincidencia exacta normalizada
    for proy in proyectos:
        for name in _all_names(proy):
            if normalizar(name) == norm_ext:
                return proy

    # 2. Solapamiento de tokens + similitud, con desambiguación (ver nombre_matching.py)
    candidatos = [(proy, _all_names(proy)) for proy in proyectos]
    ganador, _score = mejor_candidato(nombre_externo, candidatos)
    return ganador
