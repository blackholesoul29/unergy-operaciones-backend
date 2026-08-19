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

from app.services.mandatos_service import CMU_RE

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
    #
    # Contrapartida aceptada: un cuerpo de script/style que contenga algo con
    # forma de par de etiquetas balanceado (p. ej. `var t = "<p>x</p>"`) hace
    # que ese texto interno se emita como si fuera del documento. Se acepta
    # porque este parser solo ve correo interno escrito a mano en Gmail/Outlook,
    # nunca HTML de terceros: nadie redacta <script> a mano, y el CSS de un
    # <style> no lleva "<" literal (es CSS inválido). Si algún día esto pasara a
    # leer correo de remitentes arbitrarios, hay que revisar esta decisión.
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
        #
        # La recuperación es de mejor esfuerzo, no total: si dentro de ese
        # script/style sin cerrar aparece además un token con forma de etiqueta
        # sin terminar (`<div){x=1}` sin ">"), el tokenizador se lo traga junto
        # con lo que sigue y ese contenido se pierde. Hace falta que se den las
        # dos rarezas a la vez, así que se documenta en vez de arreglarse: el
        # arreglo exigiría reimplementar recuperación de tokens malformados,
        # desproporcionado para un módulo que lee un solo remitente conocido.
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


CLASIF_MOLDE_SIMPLE = "molde_simple"
CLASIF_SEGUIMIENTO = "seguimiento"
CLASIF_DESCONOCIDO = "desconocido"

# Señales de que el correo responde sobre observaciones previas. Un CMU
# mencionado acá puede estar resuelto, no con novedad -- ver el correo del
# 2026-08-10 5:50 p.m. en los fixtures.
_SENALES_SEGUIMIENTO = (
    "agradezco",
    "sin embargo",
    "siguen siendo las mismas",
    "ajustes realizados",
    "su respuesta",
    "en respuesta a",
)

# Frases que abren un listado de observaciones nuevas.
_SENALES_MOLDE = (
    "siguientes observaciones",
    "siguientes diferencias",
    "siguientes novedades",
    "siguientes inconsistencias",
    "diferencias identificadas",
)

_PREFIJOS_RESPUESTA = ("re:", "rv:", "fwd:", "rw:")


def clasificar_correo(asunto: str | None, cuerpo: str | None) -> str:
    """molde_simple | seguimiento | desconocido.

    Seguimiento se evalúa PRIMERO y gana ante señales mezcladas: interpretar de
    menos deja trabajo manual, interpretar de más corrompe estados en silencio.

    A propósito, esta función mira el cuerpo COMPLETO (incluida cualquier cita
    del hilo), a diferencia de extraer_observaciones() que trabaja sobre el
    cuerpo recortado -- ver _sin_cita(). Un "agradezco" enterrado en una cita
    empujando el correo a seguimiento es un resultado seguro: en el peor caso
    exige revisión manual. Clasificar de más (leer de más) no corrompe nada acá;
    extraer de más sí. Por eso una función es permisiva y la otra estricta.
    """
    a = _normaliza(asunto)
    c = _normaliza(cuerpo)
    if a.startswith(_PREFIJOS_RESPUESTA) or any(s in c for s in _SENALES_SEGUIMIENTO):
        return CLASIF_SEGUIMIENTO
    if any(s in c for s in _SENALES_MOLDE):
        return CLASIF_MOLDE_SIMPLE
    return CLASIF_DESCONOCIDO


# Líneas desde las que el cuerpo deja de tener contenido útil. Sin este corte,
# un CMU citado en la firma o en el hilo previo se leería como observación.
_INICIO_FIRMA = (
    "cordialmente",
    "quedo atenta",
    "quedo atento",
    "saludos",
    "atentamente",
)


# Encabezados que marcan el arranque del historial citado de un hilo. Cortar
# acá es crítico: un CMU citado del correo anterior puede figurar como YA
# RESUELTO (ver REVISORIA_SEGUIMIENTO en los fixtures) y si extraer_observaciones
# sigue leyendo después del corte, ese CMU resuelto se guarda como corrección
# nueva -- el mismo peligro que motiva clasificar_correo, colándose por otra vía.
_INICIO_CITA_GMAIL_RE = re.compile(r"^el .*\d.* escribio:$")
_INICIO_CITA_OUTLOOK_RE = re.compile(r"^on .*\d.* wrote:$")
_SEPARADORES_CITA = ("-----mensaje original-----", "-----original message-----")


def _sin_cita(cuerpo: str) -> str:
    """Todo el texto ANTES de que arranque el historial citado del hilo.

    Corta en la primera línea que sea, en cualquier variante:
    - una cita de respuesta línea a línea (prefijo '>')
    - un encabezado de Gmail ("El vie, 10 ago 2026 ... escribió:")
    - un encabezado de Outlook en inglés ("On ... wrote:")
    - un separador de reenvío de Outlook ("-----Mensaje original-----")
    - el bloque de encabezados reenviados de Outlook (De:/Para:/Asunto: en
      las líneas siguientes a una que empieza con "de:"/"from:")
    """
    lineas = cuerpo.split("\n")
    for i, linea in enumerate(lineas):
        n = _normaliza(linea)
        if linea.lstrip().startswith(">"):
            return "\n".join(lineas[:i])
        if _INICIO_CITA_GMAIL_RE.match(n) or _INICIO_CITA_OUTLOOK_RE.match(n):
            return "\n".join(lineas[:i])
        if n in _SEPARADORES_CITA:
            return "\n".join(lineas[:i])
        if n.startswith(("de:", "from:")):
            siguientes = " ".join(_normaliza(l) for l in lineas[i + 1 : i + 5])
            tiene_para = "para:" in siguientes or "to:" in siguientes
            tiene_asunto = "asunto:" in siguientes or "subject:" in siguientes
            if tiene_para and tiene_asunto:
                return "\n".join(lineas[:i])
    return cuerpo


def extraer_observaciones(cuerpo: str | None) -> list[dict]:
    """[{'cmu': 'CMU1255', 'observacion': '...'}] en orden de aparición.

    Una línea puede traer varios CMU compartiendo una misma observación
    (correo real: "Certificados CMU1266,CMU1269,CMU1270 y CMU1271 no se
    evidencia contabilización..."). La observación es lo que sigue al ÚLTIMO
    CMU de la línea. Un CMU repetido conserva su primera observación.

    Solo debe llamarse con cuerpos clasificados CLASIF_MOLDE_SIMPLE. Trabaja
    sobre el cuerpo recortado por _sin_cita() -- ver el comentario ahí y el
    de clasificar_correo() sobre por qué esta función es la estricta.

    Límite conocido y aceptado: si un correo en texto plano hace wrap de una
    observación larga en dos líneas, la línea de continuación no tiene CMU y
    se descarta en silencio, truncando la observación guardada. No se
    implementa unión de líneas de continuación porque el riesgo es bajo: el
    camino real es HTML (Gmail/Outlook componen en HTML), y html_a_texto()
    ya entrega una línea por bloque, sin wraps de texto plano.
    """
    resultado: list[dict] = []
    vistos: set[str] = set()
    for linea in _sin_cita(cuerpo or "").split("\n"):
        if _normaliza(linea).startswith(_INICIO_FIRMA):
            break
        cmus = CMU_RE.findall(linea)
        if not cmus:
            continue
        corte = linea.rfind(cmus[-1]) + len(cmus[-1])
        observacion = linea[corte:].strip().strip(".,:;-–—").strip()
        for cmu in cmus:
            if cmu in vistos:
                continue
            vistos.add(cmu)
            resultado.append({"cmu": cmu, "observacion": observacion})
    return resultado


# Fuente 3: convención verificada en los correos de Jessica
# ("CMU1135-Mandato-Costos-{Proyecto}-{Inversionista}.pdf"). Anclada al inicio
# para no confundir un CMU citado en otra parte del nombre.
_CMU_INICIO_RE = re.compile(r"^(CMU\d+)", re.IGNORECASE)


def cmu_al_inicio_de_nombre(nombre: str | None) -> str | None:
    """'CMU1135-Mandato-Costos-....pdf' → 'CMU1135'. None si no arranca con CMU.

    Para Fuente 2 (revisoría), cuya convención de nombres NO está verificada,
    usar extraer_cmu_de_nombre() de mandatos_service, que busca en cualquier parte.
    """
    m = _CMU_INICIO_RE.match((nombre or "").strip())
    return m.group(1).upper() if m else None


def solo_pdfs(nombres: list[str]) -> list[str]:
    """Los nombres que terminan en .pdf, conservando el orden."""
    return [n for n in nombres if (n or "").lower().endswith(".pdf")]


# El mandante (tercero) de la identidad de Finanzas. En los correos de Jessica
# aparece como "17844 - P.A SOL DE LA SIERRA": un código numérico seguido del
# nombre en mayúsculas. El CÓDIGO es lo estable -- los nombres se escriben con
# y sin tilde, con y sin puntos ("P.A" vs "P.A."), así que cruzar por nombre es
# frágil y cruzar por código no.
#
# El nombre corre hasta que aparece minúscula ("del mes de..."), coma o fin de
# línea. Exigir el código evita morder el saludo, que nombra a la fiduciaria
# ("PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA") sin ser la identidad.
_PA_RE = re.compile(
    r"(\d{4,6})\s*-\s*(P\.?\s?A\.?\s+[A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9\s\.\-]*?)"
    r"(?=\s+(?:del|de|para)\s|[,\n]|$)",
    re.UNICODE,
)


def extraer_pa_del_cuerpo(cuerpo: str | None) -> dict | None:
    """{'codigo': '17844', 'nombre': 'P.A SOL DE LA SIERRA'} o None.

    Solo reconoce el patrón `código - NOMBRE`. Si el correo nombra un patrimonio
    sin código, devuelve None: preferimos no identificar a identificar mal, porque
    el tercero es parte de la identidad y equivocarlo crea una fila fantasma.
    """
    m = _PA_RE.search(cuerpo or "")
    if not m:
        return None
    nombre = re.sub(r"\s+", " ", m.group(2)).strip()
    return {"codigo": m.group(1), "nombre": nombre}
