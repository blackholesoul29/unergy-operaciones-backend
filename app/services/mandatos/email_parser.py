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

# Etiquetas que implican salto de línea. Nota: etiquetas autocerradas como
# <br/> disparan tanto el start-tag como el end-tag, así que aportan DOS saltos
# de línea -- inofensivo porque las líneas vacías se filtran al final, pero es
# una trampa latente si alguien toca esta lógica.
_BLOQUE = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "ul", "ol"}
# Celdas de tabla: no rompen la línea (para no partir las filas de las tablas
# de comparación que Vanessa embebe), pero SÍ necesitan un separador entre
# ellas -- sin esto "5,703,802" y "5,475,170.65" quedarían pegados.
_CELDA = {"td", "th"}
_IGNORAR = {"script", "style"}


class _ExtractorTexto(HTMLParser):
    # Por defecto HTMLParser trata <script>/<style> como CDATA: si el cierre
    # nunca llega, todo lo que sigue (incluidas etiquetas reales, como un <p>
    # con un CMU) queda embebido como texto crudo y handle_starttag jamás se
    # entera de que hay un <p> ahí -- nuestra lógica de "recuperación" de más
    # abajo no podría dispararse nunca. Desactivamos ese modo especial para
    # que las etiquetas dentro de un script/style mal cerrado se sigan
    # parseando como etiquetas normales.
    CDATA_CONTENT_ELEMENTS: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self.partes: list[str] = []
        self._saltando = False

    def handle_starttag(self, tag: str, attrs) -> None:
        # Un <script>/<style> sin su cierre correspondiente (webmail truncado
        # o mal formado) no debe silenciar el resto del documento para siempre:
        # si mientras "saltamos" aparece una etiqueta de bloque, asumimos que
        # el tag ignorado nunca se cerró y retomamos el procesamiento normal.
        if self._saltando and tag in _BLOQUE:
            self._saltando = False
        if tag in _IGNORAR:
            self._saltando = True
        elif tag in _BLOQUE:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORAR:
            self._saltando = False
        elif tag in _BLOQUE:
            self.partes.append("\n")
        elif tag in _CELDA:
            self.partes.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._saltando:
            self.partes.append(data)


def html_a_texto(html: str | None) -> str:
    """HTML de correo → texto plano, una línea por bloque, sin líneas vacías.

    HTMLParser desescapa las entidades solo (convert_charrefs por defecto).
    """
    if not html:
        return ""
    extractor = _ExtractorTexto()
    extractor.feed(html)
    extractor.close()
    crudo = "".join(extractor.partes)
    lineas = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in crudo.split("\n")]
    return "\n".join(l for l in lineas if l)


def _normaliza(texto: str | None) -> str:
    """Minúsculas sin tildes, para comparar frases con redacción variable."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()
