"""Resolución pura sitio Starlink → proyecto (minigranja).

Sin dependencias de DB ni FastAPI. Recibe el `agrupado` de una factura (ya con los
splits aplicados por el parser en _construir_agrupado) y el catálogo de mapeos, y
devuelve una línea por sitio con su proyecto_id resuelto (o None si no está mapeado).
El match es por nombre normalizado — espejo de normName() de costosExcelExport.js.
"""
from __future__ import annotations
import unicodedata


def normalizar_sitio(nombre: str) -> str:
    """Mayúsculas, sin acentos, espacios colapsados."""
    s = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def resolver_lineas(agrupado: list[dict], mapeos: list[dict]) -> list[dict]:
    """
    agrupado: entradas con 'descripcion', 'sin_iva', 'iva', 'monto_total'.
    mapeos:   entradas con 'patron' (texto) y 'proyecto_id' (int | None).
    Devuelve una línea por entrada del agrupado:
      {'descripcion', 'proyecto_id', 'sin_iva', 'iva', 'monto_total'}.
    Sin match → proyecto_id = None.
    """
    indice = {normalizar_sitio(m["patron"]): m.get("proyecto_id") for m in mapeos}
    lineas: list[dict] = []
    for it in agrupado:
        desc = it.get("descripcion", "")
        lineas.append({
            "descripcion": desc,
            "proyecto_id": indice.get(normalizar_sitio(desc)),
            "sin_iva":     float(it.get("sin_iva") or 0),
            "iva":         float(it.get("iva") or 0),
            "monto_total": float(it.get("monto_total") or 0),
        })
    return lineas
