"""
Emparejamiento semántico de resoluciones de falla (texto libre -> código catálogo).

Reemplaza el viejo emparejamiento por substring de palabras clave (frágil: "reset"
dentro de "reseteamos" no matcheaba, y un typo lo tumbaba) por similitud difusa
con umbral de confianza. Cuando la confianza cae por debajo del umbral, el resultado
se marca ``PENDING_REVIEW`` para que un humano lo revise en vez de forzar un código
equivocado (mejor no adivinar que adivinar mal — misma filosofía de
``app/utils/nombre_matching.py``).

Prefiere ``thefuzz`` (Levenshtein + token-sort, rápido con rapidfuzz). Si no está
instalado, cae a ``difflib`` de la stdlib para que scripts y tests corran igual.

Uso:
    matcher = FallaResolutionMatcher(["reinicio_inversor", "visita_tecnica", ...])
    matcher.match("Se reinició el inversor de forma remota")
    # -> {"code": "reinicio_inversor", "confidence": 90, "status": "MATCHED", "description": "..."}
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

try:  # motor preferido: rápido y con token_set_ratio robusto ante orden/subconjuntos
    from thefuzz import fuzz, process

    _HAS_THEFUZZ = True
except ModuleNotFoundError:  # respaldo puro-stdlib para no obligar la dependencia
    from difflib import SequenceMatcher

    _HAS_THEFUZZ = False


# Umbral de confianza (0-100): por debajo, el match se marca para revisión manual.
DEFAULT_THRESHOLD = 85

STATUS_MATCHED = "MATCHED"
STATUS_PENDING = "PENDING_REVIEW"

# Frases/sinónimos representativos por código de resolución. El texto libre se compara
# contra estas frases (no contra el código crudo "reinicio_inversor", que no es lenguaje
# natural). Derivados del viejo RESOLUCION_KEYWORDS + las etiquetas del catálogo.
DEFAULT_SYNONYMS: Dict[str, List[str]] = {
    "reinicio_inversor": [
        "reinicio de inversor", "reinicio inversor", "reiniciar inversor",
        "reset inversor", "resetear inversor", "reseteo de inversor",
        "se reinicio el inversor", "reinicio", "reset",
    ],
    "visita_tecnica": [
        "visita tecnica", "visita de tecnico", "revision en sitio",
        "inspeccion en sitio", "atencion en sitio", "visita",
    ],
    "cambio_componente": [
        "cambio de componente", "reemplazo de componente", "cambio de pieza",
        "cambio de tarjeta", "reemplazo", "cambio de repuesto",
    ],
    "actualizacion_fw": [
        "actualizacion de firmware", "actualizacion firmware", "update de firmware",
        "actualizacion de software", "firmware", "flasheo de firmware",
    ],
    "intervencion_red": [
        "intervencion operador de red", "operador de red", "intervencion del or",
        "empresa de energia", "intervencion de la red", "falla del operador de red",
    ],
    "resolucion_remota": [
        "resolucion remota", "gestion remota", "telegestion", "telemando",
        "solucion remota", "atencion remota",
    ],
    "sin_accion": [
        "sin accion requerida", "sin accion", "no aplica", "no requiere accion",
        "ninguna accion", "sin intervencion",
    ],
    "otro": ["otro"],
}


def _normalize(text: str) -> str:
    """minúsculas, sin tildes, espacios colapsados, guiones bajos como espacios."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text.lower().strip())


def _ratio(a: str, b: str) -> int:
    """Puntaje de similitud 0-100 (respaldo difflib, estilo token_set_ratio)."""
    if not a or not b:
        return 0
    directo = SequenceMatcher(None, a, b).ratio()
    # token-sort: tolera diferencias de orden de palabras
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    ordenado = SequenceMatcher(None, a_sorted, b_sorted).ratio()
    # token-set: premia cuando una frase es subconjunto de la otra
    ta, tb = set(a.split()), set(b.split())
    inter = ta & tb
    subconjunto = len(inter) / min(len(ta), len(tb)) if (ta and tb) else 0.0
    return round(max(directo, ordenado, subconjunto) * 100)


class FallaResolutionMatcher:
    """Empareja texto libre de resolución contra un catálogo de códigos válidos."""

    def __init__(
        self,
        resolution_codes: List[str],
        synonyms: Optional[Dict[str, List[str]]] = None,
        threshold: int = DEFAULT_THRESHOLD,
    ) -> None:
        if not resolution_codes:
            raise ValueError("resolution_codes no puede estar vacío")
        self.resolution_codes = list(resolution_codes)
        self.threshold = threshold
        synonyms = synonyms if synonyms is not None else DEFAULT_SYNONYMS

        # frase normalizada -> código. Cada código aporta su forma legible más sinónimos.
        self._phrase_to_code: Dict[str, str] = {}
        for code in self.resolution_codes:
            frases = {_normalize(code)}  # "reinicio_inversor" -> "reinicio inversor"
            for syn in synonyms.get(code, []):
                frases.add(_normalize(syn))
            for frase in frases:
                if frase:
                    # el primer código gana una frase compartida (evita colisiones raras)
                    self._phrase_to_code.setdefault(frase, code)
        self._phrases = list(self._phrase_to_code.keys())

    def match(self, text: str) -> dict:
        """Devuelve {'code', 'confidence', 'status', 'description'} para un texto.

        - code: mejor código candidato (aunque la confianza sea baja, se devuelve
          como *sugerencia*).
        - confidence: puntaje 0-100 del mejor candidato.
        - status: 'MATCHED' si confidence >= threshold, si no 'PENDING_REVIEW'.
        - description: el texto de entrada (crudo), para conservarlo en la revisión.
        """
        original = text or ""
        query = _normalize(original)
        if not query:
            return {
                "code": None,
                "confidence": 0,
                "status": STATUS_PENDING,
                "description": original,
            }

        best_phrase, score = self._extract_one(query)
        best_code = self._phrase_to_code.get(best_phrase) if best_phrase else None
        status = STATUS_MATCHED if score >= self.threshold else STATUS_PENDING
        return {
            "code": best_code,
            "confidence": int(score),
            "status": status,
            "description": original,
        }

    def batch_match(self, descriptions: List[str]) -> List[dict]:
        """Empareja una lista de descripciones (para migraciones masivas)."""
        return [self.match(d) for d in descriptions]

    # -- internos --------------------------------------------------------------

    def _extract_one(self, query: str):
        """(mejor_frase, score 0-100) contra las frases candidatas."""
        if _HAS_THEFUZZ:
            result = process.extractOne(
                query, self._phrases, scorer=fuzz.token_set_ratio
            )
            if result is None:
                return None, 0
            phrase, score = result[0], result[1]
            return phrase, int(score)
        # respaldo difflib
        best_phrase, best_score = None, 0
        for phrase in self._phrases:
            s = _ratio(query, phrase)
            if s > best_score:
                best_phrase, best_score = phrase, s
        return best_phrase, best_score
