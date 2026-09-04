"""Emparejar el nombre de un proyecto tal como viene en un Excel.

Puerto de `normalizar` y `match_proyecto` de `app/utils/liquidaciones_loader.py`
— las dos funciones puras que necesitan tanto el cargador de liquidaciones como
el del Estado de Resultados.

Son puras a propósito: reciben la lista de proyectos como dicts, no un queryset.
Eso permite probarlas sin base y reusarlas desde los dos cargadores sin que
ninguno tenga que conocer al otro.
"""

from __future__ import annotations

import re
import unicodedata

ALIASES_PROYECTO: dict[str, str] = {
    "instituto bolivariano": "ibes",
    # ER de El Remolino traen el nombre pegado ("naos2"/"naos3") y en DB son
    # "MGS Naos 2" / "MGS Naos 3".
    "naos2": "mgs naos 2",
    "naos3": "mgs naos 3",
    # ER NITRO ALL_DATA traen el nombre de la planta a secas ("CACICA"/"PILONERAS")
    # y en DB son "Minigranja Solar La Cacica" / "Minigranja Solar Las Piloneras".
    "cacica": "la cacica",
    "piloneras": "las piloneras",
}


def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def match_proyecto(proyectos_db: list[dict], nombre: str) -> dict | None:
    norm = normalizar(nombre)
    norm = ALIASES_PROYECTO.get(norm, norm)

    for p in proyectos_db:
        if normalizar(p["nombre_comercial"]) == norm:
            return p

    _SUFIJOS = re.compile(
        r'\s*(trading|dup\b|duplicado|dulicado|terpel|excedentes|excendentes'
        r'|gasto|gastos)\s*$'
    )
    norm_sin_sufijo = _SUFIJOS.sub('', norm).strip()
    _m_trail = re.search(r'\b(\d+)\s*$', norm_sin_sufijo)
    trailing_num: str | None = _m_trail.group(1) if _m_trail else None
    _m_code = re.search(r'\b(mgs[\s\-]*\d+)\b', norm)
    excel_mgs: str | None = re.sub(r'[\s\-]+', '', _m_code.group(1)) if _m_code else None

    def _db_trailing(p: dict) -> str | None:
        m = re.search(r'\bn?(\d+)\s*$', normalizar(p["nombre_comercial"]))
        return m.group(1) if m else None

    def _db_mgs(p: dict) -> str | None:
        m = re.search(r'\b(mgs[\s\-]*\d+)\b', normalizar(p["nombre_comercial"]))
        return re.sub(r'[\s\-]+', '', m.group(1)) if m else None

    def _num_ok(p: dict) -> bool:
        if trailing_num is None:
            return True
        db_num = _db_trailing(p)
        # Si el Excel tiene número final, exigir que el proyecto DB también lo tenga
        # y que coincida. Evita que proyectos sin número (ej. "Chima Oriente")
        # capturen nombres numerados (ej. "Valencia Oriente 1").
        if db_num is None:
            return False
        return db_num == trailing_num

    if excel_mgs:
        for p in proyectos_db:
            if _db_mgs(p) == excel_mgs:
                return p

    for p in proyectos_db:
        n = normalizar(p["nombre_comercial"])
        if n and (n in norm or norm in n):
            if not _num_ok(p):
                continue
            return p

    partes = [t for t in norm.split() if len(t) >= 4 and not t.isdigit()]
    for parte in reversed(partes):
        for p in proyectos_db:
            if parte in normalizar(p["nombre_comercial"]):
                if not _num_ok(p):
                    continue
                return p

    return None
