"""Parsing puro de correos de mandatos: HTML→texto, clasificación y extracción.

Sin red, sin base de datos, sin estado. Toda la fragilidad del sistema vive
acá, por eso se prueba contra los correos reales (tests/fixtures_mandatos_correos.py).
Si Vanessa cambia su redacción, el fix es agregar el correo nuevo como fixture
y ajustar estas funciones -- nada más del sistema debería moverse.
"""
from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

# Etiquetas que implican salto de línea. Las celdas (td/th) NO están: dentro de
# una fila el texto se une con espacios, que es lo que queremos para las tablas
# de comparación que Vanessa embebe -- no las parseamos, solo evitamos que
# rompan las líneas que sí traen CMU.
_BLOQUE = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "ul", "ol"}
_IGNORAR = {"script", "style"}


class _ExtractorTexto(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []
        self._saltando = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _IGNORAR:
            self._saltando = True
        elif tag in _BLOQUE:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORAR:
            self._saltando = False
        elif tag in _BLOQUE:
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._saltando:
            self.partes.append(data)


def html_a_texto(html: str | None) -> str:
    """HTML de correo → texto plano, una línea por bloque, sin líneas vacías.

    HTMLParser desescapa las entidades solo (convert_charrefs por defecto).
    """
    if not html:
        return ""
    p = _ExtractorTexto()
    p.feed(html)
    p.close()
    crudo = "".join(p.partes)
    lineas = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in crudo.split("\n")]
    return "\n".join(l for l in lineas if l)


def _normaliza(texto: str | None) -> str:
    """Minúsculas sin tildes, para comparar frases con redacción variable."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()
