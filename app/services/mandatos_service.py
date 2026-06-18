"""Lógica pura de mandatos: parsing CMU, transiciones de estado, serialización."""
from __future__ import annotations
import re
import unicodedata
from datetime import date

CMU_RE = re.compile(r"CMU\d+")

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Estados de flujo y transiciones permitidas (incluye acciones manuales).
TRANSICIONES = {
    "pendiente_envio":       {"enviado_revisoria", "sin_inversionista"},
    "enviado_revisoria":     {"con_correcciones", "firmado"},
    "con_correcciones":      {"corregido"},
    "corregido":             {"firmado", "enviado_revisoria"},
    "firmado":               {"enviado_inversionista"},
    "enviado_inversionista": set(),
    "sin_inversionista":     {"pendiente_envio", "enviado_revisoria"},
}


def _normaliza(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def extraer_cmus(texto: str) -> list[str]:
    """Todos los CMU del texto, en orden de aparición, sin duplicados."""
    vistos: list[str] = []
    for m in CMU_RE.findall(texto or ""):
        if m not in vistos:
            vistos.append(m)
    return vistos


def extraer_cmu_de_nombre(nombre_archivo: str) -> str | None:
    """Primer CMU encontrado en el nombre de un archivo, o None."""
    m = CMU_RE.search(nombre_archivo or "")
    return m.group(0) if m else None


def mes_a_periodo(mes_texto: str, anio: int) -> date | None:
    """'Mayo', 2025 → date(2025, 5, 1). None si el mes no es reconocible."""
    n = _normaliza(mes_texto)
    mes = MESES.get(n)
    return date(anio, mes, 1) if mes else None


def transicion_valida(estado_actual: str, estado_nuevo: str) -> bool:
    return estado_nuevo in TRANSICIONES.get(estado_actual, set())


def mandato_to_dict(row) -> dict:
    """Serializa una fila Mandato (o SimpleNamespace) al contrato de la API."""
    def iso(d):
        return d.isoformat() if d else None
    return {
        "id": row.id,
        "cmu": row.cmu,
        "periodo": row.periodo.strftime("%Y-%m") if row.periodo else None,
        "proyecto": row.proyecto,
        "tercero": row.tercero,
        "inversionista_id": row.inversionista_id,
        "estado": row.estado,
        "observacion": row.observacion,
        "fecha_envio_revisoria": iso(row.fecha_envio_revisoria),
        "fecha_firmado": iso(row.fecha_firmado),
        "fecha_envio_inversionista": iso(row.fecha_envio_inversionista),
        "pdf_firmado_nombre": row.pdf_firmado_nombre,
        "tiene_pdf": bool(row.pdf_firmado_ruta),
    }


def calcular_resumen(filas) -> dict:
    """Conteos para las 5 tarjetas de métricas."""
    estados = [f.estado for f in filas]
    pendientes = sum(1 for e in estados if e in ("pendiente_envio", "enviado_revisoria"))
    return {
        "total": len(estados),
        "correcciones": estados.count("con_correcciones"),
        "firmados": estados.count("firmado"),
        "enviados_inversionista": estados.count("enviado_inversionista"),
        "pendientes": pendientes,
    }
