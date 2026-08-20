"""Lógica pura de mandatos: parsing CMU, transiciones de estado, serialización."""
from __future__ import annotations
import re
import unicodedata
import difflib
from datetime import date

CMU_RE = re.compile(r"CMU\d+")
# Tres convenciones reales conviven (verificadas contra la bitácora de la
# primera corrida, 2026-08-19):
#   CMU0988-Mandato-Costos-{Proyecto}-{Inversionista}.pdf   costos, con inversionista
#   CMU1140-Mandato-Costos-{Proyecto}.pdf                   costos, mandante es un P.A.
#   CMU1182-Mandato-{Proyecto}.pdf                          ingresos/autoconsumo
#
# "Costos-" es opcional; su ausencia es justamente lo que distingue un mandato
# de ingresos (ver tipo_de_nombre). El inversionista también es opcional, y se
# reconoce por el ESPACIADO del guion: pegado cuando separa al inversionista
# ("...Uruaco-SUNO..."), con espacios cuando es parte del nombre del proyecto
# ("PSF - Yurbaqua"). Heurística, no garantía -- documentada en el spec.
ZIP_NOMBRE_RE = re.compile(
    r"^(CMU\d+)-Mandato-(?:Costos-)?(.+?)(?:(?<! )-(?! )([^-]+))?\.pdf$",
    re.IGNORECASE)

# Gmail renombra los adjuntos repetidos agregando " (1)", " (2)". Sin quitarlo,
# el sufijo termina dentro del nombre del inversionista y la misma entidad
# genera dos identidades distintas.
_SUFIJO_GMAIL_RE = re.compile(r"\s\(\d+\)(?=\.pdf$)", re.IGNORECASE)

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
        "archivo_zip_nombre": getattr(row, "archivo_zip_nombre", None),
        "tiene_pdf_zip": bool(getattr(row, "archivo_zip_nombre", None)),
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


def parsear_nombre_zip(nombre: str) -> dict | None:
    """'CMU0988-Mandato-Costos-{Proyecto}[-{Inversionista}].pdf' → dict | None.

    El inversionista es opcional: los mandatos de un P.A. de fiduciaria no lo
    traen en el nombre (ahí el mandante sale del cuerpo del correo). Cuando
    falta, se devuelve cadena vacía -- nunca se inventa.
    """
    m = ZIP_NOMBRE_RE.match(_SUFIJO_GMAIL_RE.sub("", (nombre or "").strip()))
    if not m:
        return None
    return {"cmu": m.group(1).upper(),
            "proyecto": (m.group(2) or "").strip(),
            "inversionista": (m.group(3) or "").strip()}


def match_inversionista(nombre: str, maestra: list[dict], umbral: float = 0.6):
    """Cruza el nombre de inversionista contra la maestra.

    Devuelve (inversionista_id | None, sugerencia | None, score):
      - match exacto normalizado            → (id, None, 1.0)        auto-vincula
      - nombre de maestra contenido (substr) → (id, None, 0.9)        auto-vincula
      - mejor fuzzy >= umbral                → (None, sugerencia, sc)  confirmación manual
      - sin candidato                        → (None, None, sc)
    `maestra` es lista de {"id", "nombre"}.
    """
    n = _normaliza(nombre)
    if not n:
        return None, None, 0.0
    tokens = n.split()
    # 1) exacto
    for inv in maestra:
        if _normaliza(inv["nombre"]) == n:
            return inv["id"], None, 1.0
    # 2) substring (maestra corta dentro del nombre largo) -> auto-vincula
    for inv in maestra:
        mn = _normaliza(inv["nombre"])
        if mn and mn in n:
            return inv["id"], None, 0.9
    # 3) fuzzy (mejor ratio contra el nombre completo o cualquier token)
    mejor, mejor_score = None, 0.0
    for inv in maestra:
        mn = _normaliza(inv["nombre"])
        if not mn:
            continue
        ratios = [difflib.SequenceMatcher(None, mn, n).ratio()]
        ratios += [difflib.SequenceMatcher(None, mn, t).ratio() for t in tokens]
        score = max(ratios)
        if score > mejor_score:
            mejor, mejor_score = inv, score
    if mejor and mejor_score >= umbral:
        return None, {"sugerido_id": mejor["id"], "sugerido_nombre": mejor["nombre"],
                      "score": round(mejor_score, 2)}, mejor_score
    return None, None, round(mejor_score, 2)
