"""Vinculación de arr_proyectos (catálogo de Arriendos) con la tabla maestra proyectos.

Match por tokens significativos del nombre (mismo espíritu que om_calculator.om_match_seed):
exige que TODOS los tokens significativos del nombre de arriendo estén en el nombre del
proyecto maestro, y que el match sea único. Fill-if-null: nunca pisa un proyecto_id ya puesto.
"""
from __future__ import annotations
import re
import unicodedata

from sqlalchemy.orm import Session

_GENERICOS = {"la", "el", "los", "las", "de", "del", "san", "sur", "norte",
              "solar", "minigranja", "valle", "mgs"}


def normaliza(s: str) -> str:
    return (
        unicodedata.normalize("NFKD", s or "")
        .encode("ascii", "ignore").decode().lower().strip()
    )


def _tokens(nombre: str) -> list[str]:
    n = normaliza(nombre).replace("minigranja solar", " ").replace("minigranja", " ")
    toks = re.findall(r"[a-z]+|\d+", n)
    sig = [t for t in toks if t.isdigit() or (len(t) > 3 and t not in _GENERICOS)]
    return sig or [t for t in toks if t not in _GENERICOS] or toks


def match_proyecto(arr_nombre: str, arr_codigo, proyectos) -> "object | None":
    """Devuelve el Proyecto único que casa con el nombre de arriendo, o None."""
    claves = _tokens(arr_nombre)
    if not claves:
        return None
    candidatos = []
    for p in proyectos:
        disp = set(re.findall(r"[a-z]+|\d+", normaliza(p.nombre_comercial)))
        if all(t in disp for t in claves):
            candidatos.append(p)
    return candidatos[0] if len(candidatos) == 1 else None


def backfill_arr_proyecto_links(db: Session) -> dict:
    """Rellena arr_proyectos.proyecto_id (fill-if-null). Devuelve reporte con no-matcheados."""
    from app.models.proyectos import Proyecto
    from app.models.arriendos import ArrProyecto

    proyectos = db.query(Proyecto).all()
    arr = db.query(ArrProyecto).all()

    vinculados = 0
    ya_tenian = 0
    sin_match = []
    for a in arr:
        if a.proyecto_id is not None:
            ya_tenian += 1
            continue
        m = match_proyecto(a.nombre, a.codigo, proyectos)
        if m is not None:
            a.proyecto_id = m.id
            vinculados += 1
        else:
            sin_match.append({"id": a.id, "nombre": a.nombre, "codigo": a.codigo})
    db.commit()
    return {"vinculados": vinculados, "ya_tenian": ya_tenian,
            "sin_match": sin_match, "total": len(arr)}
