"""
Algoritmo puro de comparación de nombres de proyectos/fronteras -- sin
dependencias de base de datos ni de la app, para que lo puedan importar tanto
código que corre dentro del backend (con sesión de BD) como scripts externos
que solo reciben listas de nombres por HTTP.

Es la misma cadena que se usó para reconciliar fronteras.proyecto_id contra
producción (2026-07-02, scripts/etl_fronteras_proyectos.py, ya retirado):
normaliza, quita prefijos de ruido ("Minigranja Solar", "GD", "MGS", "Consumo
Aux", etc.) que antes causaban falsos matches entre proyectos distintos,
compara solapamiento de tokens + similitud de texto, y no acepta un resultado
si el segundo mejor candidato queda casi tan bien como el primero (mejor no
adivinar que adivinar mal).

Usado por:
  - app/utils/proyecto_matching.py  (find_proyecto_by_name, con sesión de BD)
  - scripts/cargar_fronteras_gescon.py  (match_proyecto, vía API externa)
"""
import re
import unicodedata
from difflib import SequenceMatcher

UMBRAL_ACEPTAR = 0.55
MARGEN_AMBIGUO = 0.05

_STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "y", "en",
    "minigranja", "minigranjas", "mgs", "mgr", "gd", "planta", "granja",
    "solar", "sol", "cielo", "frontera", "proyecto",
    "consumo", "auxiliar", "aux", "propio", "serv", "ser", "generacion",
}


# Sufijos societarios (razón social de empresa, no de proyecto/frontera) --
# se quitan ANTES de tirar la puntuación, para que "S.A.S." se reconozca como
# una sola unidad y no como las letras sueltas "s"/"a"/"s" tras normalizar.
_SUFIJOS_SOCIETARIOS = re.compile(
    r"\b(s\.?a\.?s\.?|e\.?s\.?p\.?|s\.?a\.?|ltda\.?|bic)\b", re.IGNORECASE
)


def normalizar(texto: str) -> str:
    """Quita tildes, pone minúsculas, sufijos societarios (S.A.S./LTDA/E.S.P.)
    y elimina caracteres no alfanuméricos."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii").lower()
    ascii_str = _SUFIJOS_SOCIETARIOS.sub(" ", ascii_str)
    return re.sub(r"[^a-z0-9\s]", " ", ascii_str).strip()


def core_tokens(nombre: str) -> set[str]:
    """Tokens significativos de un nombre (sin stopwords de ruido tipo
    'Minigranja Solar' / 'GD' / 'Consumo Aux')."""
    return {t for t in normalizar(nombre).split() if t and t not in _STOPWORDS}


def score_nombre(nombre_a: str, nombres_b: list[str]) -> float:
    """Mejor score entre nombre_a y cualquiera de nombres_b: combina solapamiento
    de tokens (orden-independiente) con similitud de texto (tolera typos)."""
    tokens_a = core_tokens(nombre_a)
    if not tokens_a:
        return 0.0
    mejor = 0.0
    for nb in nombres_b:
        if not nb:
            continue
        tokens_b = core_tokens(nb)
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


def mejor_candidato(nombre_objetivo: str, candidatos: list[tuple]) -> tuple:
    """Elige el mejor candidato para nombre_objetivo.

    candidatos: lista de (id_o_objeto, [nombres...]) -- el segundo elemento de
    cada tupla es la lista de nombres alternativos de ese candidato.

    Devuelve (id_o_objeto, score) del ganador, o (None, score) si ninguno supera
    el umbral, o si los dos mejores quedan demasiado cerca entre sí (ambiguo --
    mejor no adivinar)."""
    puntajes = sorted(
        ((item, score_nombre(nombre_objetivo, nombres)) for item, nombres in candidatos),
        key=lambda x: -x[1],
    )
    if not puntajes:
        return None, 0.0
    mejor_item, mejor_score = puntajes[0]
    segundo_score = puntajes[1][1] if len(puntajes) > 1 else 0.0

    if mejor_score < UMBRAL_ACEPTAR:
        return None, mejor_score
    if (mejor_score - segundo_score) < MARGEN_AMBIGUO and segundo_score >= UMBRAL_ACEPTAR:
        return None, mejor_score  # ambiguo entre 2+ candidatos

    return mejor_item, mejor_score
