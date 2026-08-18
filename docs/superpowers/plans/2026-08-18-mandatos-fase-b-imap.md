# Mandatos Fase B (lectura IMAP) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la plataforma lea por IMAP el buzón `adhara@unergy.io` y actualice sola el estado de los mandatos de costos a partir de los correos de la revisoría y de los envíos a inversionistas, dejando registro de todo lo que vio.

**Architecture:** Cuatro unidades. `email_parser.py` es puro (texto → estructura, sin red ni BD) y concentra toda la fragilidad, por eso se prueba con los seis correos reales como fixtures. `imap_client.py` hace solo I/O. `email_sync.py` orquesta y aplica transiciones. Un cron en `main.py` lo dispara. Se reusa `mandatos_service.py` de Fase A (`CMU_RE`, `extraer_cmu_de_nombre`, `transicion_valida`, `TRANSICIONES`).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, APScheduler, `imaplib`/`email` (stdlib), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-mandatos-fase-b-imap-design.md`

**Rama:** `feat/mandatos-fase-b-imap` (ya creada, con el spec commiteado en `0d2af36`)

---

## Alcance

Este plan cubre **solo el backend**. El panel "Correos leídos" del frontend (spec §9) va en un plan aparte, en el repo `unergy-operaciones-frontend`, una vez que exista la API. El backend es software funcional por sí solo: el cron lee, aplica y registra, y todo es consultable por `GET /mandatos/correos`.

**Seguridad de despliegue:** el cron se registra únicamente si `MANDATOS_IMAP_USER` y `MANDATOS_IMAP_PASSWORD` están definidas. Ya lo están en Railway, así que **el cron empezará a correr en el primer deploy a master**. Mientras el trabajo viva en la rama, no corre nada.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/services/mandatos/__init__.py` | Marca el paquete. Vacío. |
| `app/services/mandatos/email_parser.py` | **Puro.** HTML→texto, clasificación, extracción de CMU y observaciones. |
| `app/services/mandatos/imap_client.py` | Conexión IMAP, búsqueda, decodificación de correos. No sabe de mandatos. |
| `app/services/mandatos/email_sync.py` | Orquesta: correos → parser → BD, aplica transiciones, escribe bitácora. |
| `app/models/mandatos.py` *(modificar)* | Modelo `MandatoCorreo`. |
| `app/core/config.py` *(modificar)* | `MANDATOS_IMAP_USER`, `MANDATOS_IMAP_PASSWORD`. |
| `app/main.py` *(modificar)* | DDL de `mandato_correos` + registro del cron. |
| `app/api/v1/mandatos.py` *(modificar)* | `GET /mandatos/correos`, `POST /mandatos/correos/{id}/revertir`. |
| `tests/fixtures_mandatos_correos.py` | Los seis correos reales como constantes. |
| `tests/test_mandatos_email_parser.py` | Tests del parser puro. |
| `tests/test_mandatos_email_sync.py` | Tests de orquestación con IMAP simulado. |

Nota: existe `app/services/mandatos_service.py` (módulo) y se crea `app/services/mandatos/` (paquete). No colisionan — son nombres distintos. El paquete sigue el patrón de `app/services/reporte_energia/`.

---

### Task 1: Fixtures de los correos reales

Los seis correos revisados el 2026-08-18. Todo el resto del plan depende de ellos.

**Files:**
- Create: `tests/fixtures_mandatos_correos.py`

- [ ] **Step 1: Crear el archivo de fixtures**

```python
"""Correos reales revisados el 2026-08-18, usados como fixtures del parser.

Transcritos de capturas del buzón adhara@unergy.io. Se conservan tal cual --
la redacción exacta ES el caso de prueba. No "limpiar" ni normalizar nada acá.
"""

# ── Fuente 1/2 -- revisoría (vlondono@jbp.com.co) ─────────────────────────────

# 2026-08-10 2:25 p.m. -- observaciones nuevas, con tabla HTML embebida.
REVISORIA_OBSERVACIONES = """Buenas tardes Adhara,

Revisando la información que me compartes, encuentro las siguientes observaciones:

1. Certificado CMU1255 el valor a pagar no coincide con la suma de los conceptos detallados, además encuentro una diferencia entre contabilidad y el certificado así:

2. Certificados CMU1266,CMU1269,CMU1270 y CMU1271   no se evidencia contabilización del internet, el IVA y el arriendo.
3. Certificado CMU1284 no se evidencia contabilización

Quedo atenta,

Cordialmente
Vanessa Londoño Sánchez
Asistente de auditoria
JB Pérez & Cía S.A.S."""

# 2026-08-10 5:50 p.m. -- respuesta en el hilo. CMU1255 quedó RESUELTO.
# Caso de regresión más importante del sistema: un regex de CMU\\d+ marcaría
# CMU1255 como con_correcciones siendo el único que quedó bien.
REVISORIA_SEGUIMIENTO = """Hola Vanessa,

Agradezco su respuesta y los ajustes realizados para el mandato CMU1255. Sin embargo, para los mandatos CMU1266, CMU1269, CMU1271 y CMU1284, las observaciones siguen siendo las mismas.

Por favor, valide los conceptos y los comentarios anteriores para realizar la contabilización o los ajustes correspondientes, ya que en algunos casos se evidencia la contabilización pero no de todos los conceptos que se encuentran certificados.

Cordialmente
Vanessa Londoño Sánchez"""

# 2026-07-14 3:20 p.m. -- PDFs firmados Y observaciones en el mismo correo.
REVISORIA_MIXTO = """Buenas tardes, Adhara:

Adjunto comparto los certificados de Sol de la Sierra debidamente firmados. Asimismo, relaciono a continuación las diferencias identificadas en los certificados de costos:

CMU1052 No se evidencia contabilización del mantenimiento y el IVA de este.
CMU1122 Evidencio que el arrendamiento se encuentra contabilizado al debito y al crédito generado un efecto 0 en el valor y una diferencia con el certificado

Los demás certificados se encuentran actualmente en proceso de firma y se los estaré compartiendo tan pronto estén listos.

Cordialmente
Vanessa Londoño Sánchez"""

# Cuerpo HTML con la tabla del correo de las 2:25 p.m.
REVISORIA_HTML = """<div dir="ltr"><p>Buenas tardes Adhara,</p>
<p>Revisando la informaci&oacute;n que me compartes, encuentro las siguientes observaciones:</p>
<p>1. Certificado CMU1255 el valor a pagar no coincide con la suma de los conceptos detallados, adem&aacute;s encuentro una diferencia entre contabilidad y el certificado as&iacute;:</p>
<table><tr><td>Certificado</td><td>Contabilidad</td></tr>
<tr><td>5,703,802</td><td>5,475,170.65</td></tr></table>
<p>2. Certificados CMU1266,CMU1269,CMU1270 y CMU1271 &nbsp; no se evidencia contabilizaci&oacute;n del internet, el IVA y el arriendo.</p>
<p>3. Certificado CMU1284 no se evidencia contabilizaci&oacute;n</p>
<p>Cordialmente</p></div>"""

# ── Fuente 3 -- envío a inversionistas (jessica@unergy.io) ────────────────────

# 2026-08-12 8:14 a.m. -- 8 adjuntos: 1 xlsx + 4 PDFs de mandato (visibles).
ENVIO_INVERSIONISTA = """Cordial saludo equipo de PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA , espero se encuentren muy bien.

La presente es con el fin de informarles que los certificados de mandato de costos de los proyectos asociados al 17844 - P.A SOL DE LA SIERRA del mes de junio ya se encuentran emitidos y firmados con fecha actual. Anexo bajo este correo cada uno de estos certificados de mandato

--
Cordialmente,
Jessica Ramirez"""

ENVIO_INVERSIONISTA_ADJUNTOS = [
    "REGISTRO MANDATOS.xlsx",
    "CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1141-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1139-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    "CMU1142-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
]

# 2026-08-12 5:05 p.m. -- "Liquidación preliminar". Caso NEGATIVO: es de Jessica,
# va a un inversionista y menciona "certificados de mandato", pero no trae
# adjuntos de mandato. La regla de Fuente 3 debe descartarlo sin excepciones.
LIQUIDACION_PRELIMINAR = """LIQUIDACIÓN PRELIMINAR
ESTRADA

Cordial saludo,

Esperamos que se encuentren muy bien.

Por medio del presente, les compartimos la información preliminar de liquidación correspondiente a la operación del mes de julio. Tenga en cuenta que estos datos son preliminares y no oficiales; los valores definitivos serán comunicados una vez se emitan los certificados de mandato y las facturas oficiales.

RELACIÓN DE PROYECTOS
Minigranja Solar La Reserva"""

LIQUIDACION_PRELIMINAR_ADJUNTOS = []
```

- [ ] **Step 2: Verificar que importa sin errores**

Run: `python -c "import tests.fixtures_mandatos_correos as f; print(len(f.ENVIO_INVERSIONISTA_ADJUNTOS))"`
Expected: `5`

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures_mandatos_correos.py
git commit -m "test(mandatos): fixtures de los seis correos reales de Fase B"
```

---

### Task 2: `html_a_texto` — cuerpos HTML a texto plano

Los correos llegan en HTML con tablas y entidades. Sin dependencias nuevas: `html.parser` de stdlib.

**Files:**
- Create: `app/services/mandatos/__init__.py`
- Create: `app/services/mandatos/email_parser.py`
- Create: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir el test que falla**

```python
"""Tests del parser de correos de mandatos -- funciones puras, sin red ni BD."""
from app.services.mandatos.email_parser import html_a_texto
from tests.fixtures_mandatos_correos import REVISORIA_HTML


def test_html_a_texto_desescapa_entidades():
    texto = html_a_texto("<p>informaci&oacute;n&nbsp;compartida</p>")
    assert texto == "información compartida"


def test_html_a_texto_separa_bloques_en_lineas():
    texto = html_a_texto("<p>uno</p><p>dos</p>")
    assert texto.split("\n") == ["uno", "dos"]


def test_html_a_texto_ignora_script_y_style():
    texto = html_a_texto("<p>visible</p><style>.x{color:red}</style><script>var a=1</script>")
    assert texto == "visible"


def test_html_a_texto_conserva_los_cmu_de_cada_linea():
    texto = html_a_texto(REVISORIA_HTML)
    lineas_con_cmu = [l for l in texto.split("\n") if "CMU" in l]
    assert len(lineas_con_cmu) == 3
    assert "CMU1266,CMU1269,CMU1270 y CMU1271" in lineas_con_cmu[1]


def test_html_a_texto_vacio():
    assert html_a_texto("") == ""
    assert html_a_texto(None) == ""
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.mandatos'`

- [ ] **Step 3: Crear el paquete y la implementación mínima**

Crear `app/services/mandatos/__init__.py` vacío (archivo sin contenido).

Crear `app/services/mandatos/email_parser.py`:

```python
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
```

Nota sobre `_normaliza`: `mandatos_service.py` tiene una función equivalente,
también privada. Se duplican tres líneas a propósito, en vez de acoplar el
parser a un símbolo privado de otro módulo. El parser debe poder cambiar sin
arrastrar a Fase A.

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/__init__.py app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): html_a_texto para cuerpos de correo HTML"
```

---

### Task 3: `clasificar_correo` — la compuerta de molde conocido

La pieza que impide que el regex interprete un correo de seguimiento. Ver spec §6.3.

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_mandatos_email_parser.py`:

```python
from app.services.mandatos.email_parser import (
    clasificar_correo, CLASIF_MOLDE_SIMPLE, CLASIF_SEGUIMIENTO, CLASIF_DESCONOCIDO,
)
from tests.fixtures_mandatos_correos import (
    REVISORIA_OBSERVACIONES, REVISORIA_SEGUIMIENTO, REVISORIA_MIXTO,
)


# ── clasificar_correo ─────────────────────────────────────────────────────────

def test_clasificar_observaciones_nuevas_es_molde_simple():
    assert clasificar_correo("Mandatos de costos julio", REVISORIA_OBSERVACIONES) == CLASIF_MOLDE_SIMPLE


def test_clasificar_correo_mixto_es_molde_simple():
    assert clasificar_correo("Certificados Sol de la Sierra", REVISORIA_MIXTO) == CLASIF_MOLDE_SIMPLE


def test_clasificar_seguimiento_no_se_interpreta():
    """El correo donde CMU1255 quedó resuelto. Si esto se rompe, el sistema
    empieza a marcar mandatos resueltos como con_correcciones."""
    assert clasificar_correo("Mandatos de costos julio", REVISORIA_SEGUIMIENTO) == CLASIF_SEGUIMIENTO


def test_clasificar_asunto_re_es_seguimiento():
    assert clasificar_correo("RE: Certificados", "encuentro las siguientes observaciones: CMU1000 mal") == CLASIF_SEGUIMIENTO


def test_seguimiento_gana_sobre_molde_simple():
    """Ante señales de ambos, gana seguimiento -- falla hacia el lado seguro."""
    cuerpo = "Agradezco su respuesta. Encuentro las siguientes observaciones: CMU1000 mal"
    assert clasificar_correo("Certificados", cuerpo) == CLASIF_SEGUIMIENTO


def test_clasificar_correo_sin_senales_es_desconocido():
    assert clasificar_correo("Hola", "Buenas tardes, quedo atenta.") == CLASIF_DESCONOCIDO
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: FAIL con `ImportError: cannot import name 'clasificar_correo'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/email_parser.py`:

```python
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
    """
    a = _normaliza(asunto)
    c = _normaliza(cuerpo)
    if a.startswith(_PREFIJOS_RESPUESTA) or any(s in c for s in _SENALES_SEGUIMIENTO):
        return CLASIF_SEGUIMIENTO
    if any(s in c for s in _SENALES_MOLDE):
        return CLASIF_MOLDE_SIMPLE
    return CLASIF_DESCONOCIDO
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): compuerta de clasificacion de correos de la revisoria"
```

---

### Task 4: `extraer_observaciones` — CMU con su texto

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_mandatos_email_parser.py`:

```python
from app.services.mandatos.email_parser import extraer_observaciones


# ── extraer_observaciones ─────────────────────────────────────────────────────

def test_extraer_observaciones_correo_real():
    obs = extraer_observaciones(REVISORIA_OBSERVACIONES)
    assert [o["cmu"] for o in obs] == [
        "CMU1255", "CMU1266", "CMU1269", "CMU1270", "CMU1271", "CMU1284",
    ]


def test_varios_cmu_en_una_linea_comparten_observacion():
    obs = {o["cmu"]: o["observacion"] for o in extraer_observaciones(REVISORIA_OBSERVACIONES)}
    esperado = "no se evidencia contabilización del internet, el IVA y el arriendo"
    assert obs["CMU1266"] == esperado
    assert obs["CMU1271"] == esperado


def test_observacion_arranca_despues_del_ultimo_cmu():
    obs = {o["cmu"]: o["observacion"] for o in extraer_observaciones(REVISORIA_OBSERVACIONES)}
    assert obs["CMU1255"].startswith("el valor a pagar no coincide")
    assert obs["CMU1284"] == "no se evidencia contabilización"


def test_extraer_observaciones_correo_mixto():
    obs = extraer_observaciones(REVISORIA_MIXTO)
    assert [o["cmu"] for o in obs] == ["CMU1052", "CMU1122"]
    assert obs[0]["observacion"] == "No se evidencia contabilización del mantenimiento y el IVA de este"


def test_extraer_observaciones_corta_en_la_firma():
    cuerpo = "CMU1000 tiene novedad\nCordialmente\nCMU9999 esto es parte de la firma"
    assert [o["cmu"] for o in extraer_observaciones(cuerpo)] == ["CMU1000"]


def test_extraer_observaciones_sin_cmu():
    assert extraer_observaciones("Buenas tardes, quedo atenta.") == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: FAIL con `ImportError: cannot import name 'extraer_observaciones'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/email_parser.py`:

```python
from app.services.mandatos_service import CMU_RE

# Líneas desde las que el cuerpo deja de tener contenido útil. Sin este corte,
# un CMU citado en la firma o en el hilo previo se leería como observación.
_INICIO_FIRMA = (
    "cordialmente",
    "quedo atenta",
    "quedo atento",
    "saludos",
    "atentamente",
)


def extraer_observaciones(cuerpo: str | None) -> list[dict]:
    """[{'cmu': 'CMU1255', 'observacion': '...'}] en orden de aparición.

    Una línea puede traer varios CMU compartiendo una misma observación
    (correo real: "Certificados CMU1266,CMU1269,CMU1270 y CMU1271 no se
    evidencia contabilización..."). La observación es lo que sigue al ÚLTIMO
    CMU de la línea. Un CMU repetido conserva su primera observación.

    Solo debe llamarse con cuerpos clasificados CLASIF_MOLDE_SIMPLE.
    """
    resultado: list[dict] = []
    vistos: set[str] = set()
    for linea in (cuerpo or "").split("\n"):
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
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: PASS, 17 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): extraer CMU y su observacion del cuerpo del correo"
```

---

### Task 5: CMU desde nombres de adjuntos (Fuentes 2 y 3)

Dos reglas distintas a propósito. Fuente 3 (Jessica) usa la convención verificada
`CMU####-Mandato-Costos-...`, así que se ancla al inicio. Fuente 2 (Vanessa) tiene
convención **sin verificar**, así que se busca el CMU en cualquier parte del nombre —
reusando `extraer_cmu_de_nombre()` de Fase A.

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_mandatos_email_parser.py`:

```python
from app.services.mandatos.email_parser import cmu_al_inicio_de_nombre, solo_pdfs
from tests.fixtures_mandatos_correos import (
    ENVIO_INVERSIONISTA_ADJUNTOS, LIQUIDACION_PRELIMINAR_ADJUNTOS,
)


# ── adjuntos ──────────────────────────────────────────────────────────────────

def test_cmu_al_inicio_de_nombre_convencion_de_jessica():
    assert cmu_al_inicio_de_nombre("CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf") == "CMU1135"


def test_cmu_al_inicio_ignora_cmu_en_medio_del_nombre():
    """Ancla al inicio: un CMU suelto en medio del nombre no cuenta para Fuente 3."""
    assert cmu_al_inicio_de_nombre("REGISTRO MANDATOS CMU1135.xlsx") is None


def test_cmu_al_inicio_sin_match():
    assert cmu_al_inicio_de_nombre("REGISTRO MANDATOS.xlsx") is None
    assert cmu_al_inicio_de_nombre("") is None
    assert cmu_al_inicio_de_nombre(None) is None


def test_solo_pdfs_descarta_el_excel():
    assert solo_pdfs(ENVIO_INVERSIONISTA_ADJUNTOS) == [
        "CMU1135-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1141-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1139-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
        "CMU1142-Mandato-Costos-Sol de la Sierra-Bancolombia.pdf",
    ]


def test_liquidacion_preliminar_no_aporta_cmu():
    """Caso negativo: correo de Jessica a inversionistas que menciona
    'certificados de mandato' pero no trae adjuntos de mandato."""
    pdfs = solo_pdfs(LIQUIDACION_PRELIMINAR_ADJUNTOS)
    assert [cmu_al_inicio_de_nombre(n) for n in pdfs] == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: FAIL con `ImportError: cannot import name 'cmu_al_inicio_de_nombre'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/email_parser.py`:

```python
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
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: PASS, 22 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): extraer CMU de nombres de adjuntos (Fuentes 2 y 3)"
```

---

### Task 6: Modelo `MandatoCorreo` y DDL

**Files:**
- Modify: `app/models/mandatos.py` (agregar al final)
- Modify: `app/main.py` → `_PENDING_DDLS` (después del bloque de `gmail_credenciales`)

- [ ] **Step 1: Agregar el modelo**

Al final de `app/models/mandatos.py`:

```python
class MandatoCorreo(Base):
    """Bitácora de correos leídos por IMAP -- procesados y omitidos.

    Una fila por correo, deduplicada por el header Message-ID. Se registra
    TODO lo que el lector vio, no solo aquello sobre lo que actuó: un correo
    omitido es información, y sin esta tabla el usuario no tendría cómo saber
    que existió.

    `detalle` guarda el estado anterior de cada mandato afectado -- de ahí sale
    la reversión.
    """
    __tablename__ = "mandato_correos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[str] = mapped_column(String(998), nullable=False, unique=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    remitente: Mapped[str] = mapped_column(String(255), nullable=False)
    asunto: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    fuente: Mapped[str] = mapped_column(String(20), nullable=False)          # revisoria | envio_inversionista
    clasificacion: Mapped[str] = mapped_column(String(20), nullable=False)   # molde_simple | seguimiento | desconocido
    resultado: Mapped[str] = mapped_column(String(20), nullable=False)       # aplicado | omitido | error
    requiere_revision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    detalle: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="'{}'::jsonb")
    revertido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Agregar el DDL**

En `app/main.py`, dentro de `_PENDING_DDLS`, después del bloque `CREATE TABLE IF NOT EXISTS gmail_credenciales (...)`:

```python
    """CREATE TABLE IF NOT EXISTS mandato_correos (
        id BIGSERIAL PRIMARY KEY,
        message_id VARCHAR(998) NOT NULL UNIQUE,
        fecha TIMESTAMPTZ NOT NULL,
        remitente VARCHAR(255) NOT NULL,
        asunto VARCHAR(1000),
        fuente VARCHAR(20) NOT NULL,
        clasificacion VARCHAR(20) NOT NULL,
        resultado VARCHAR(20) NOT NULL,
        requiere_revision BOOLEAN NOT NULL DEFAULT FALSE,
        detalle JSONB NOT NULL DEFAULT '{}'::jsonb,
        revertido BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_mandato_correos_fecha ON mandato_correos (fecha)",
    "CREATE INDEX IF NOT EXISTS ix_mandato_correos_revision ON mandato_correos (requiere_revision)",
```

- [ ] **Step 3: Verificar que el modelo importa y el DDL es válido**

Run: `python -c "from app.models.mandatos import MandatoCorreo; print(MandatoCorreo.__tablename__, len(MandatoCorreo.__table__.columns))"`
Expected: `mandato_correos 12`

Run: `python -c "import app.main"`
Expected: sin salida ni excepción

- [ ] **Step 4: Commit**

```bash
git add app/models/mandatos.py app/main.py
git commit -m "feat(mandatos): tabla mandato_correos -- bitacora de correos leidos"
```

---

### Task 7: Config e `imap_client`

**Files:**
- Modify: `app/core/config.py` (después del bloque IMAP existente, ~línea 119)
- Create: `app/services/mandatos/imap_client.py`

- [ ] **Step 1: Agregar las variables de configuración**

En `app/core/config.py`, justo después de `IMAP_PORT: int = 993`:

```python
    # IMAP de mandatos -- buzón adhara@unergy.io, el único en copia de las tres
    # fuentes de correo de mandatos (revisoría y envíos a inversionistas).
    # NO reusa SMTP_USER/SMTP_PASSWORD: esas son de operaciones@, otra cuenta.
    # Requiere App Password propio (verificación en dos pasos activa en la cuenta).
    MANDATOS_IMAP_USER: str = ""
    MANDATOS_IMAP_PASSWORD: str = ""
```

- [ ] **Step 2: Crear el cliente IMAP**

Crear `app/services/mandatos/imap_client.py`:

```python
"""Acceso IMAP de solo lectura al buzón de mandatos.

Solo I/O -- no sabe qué es un mandato. Nunca marca correos como leídos ni
modifica etiquetas: adhara@unergy.io es el buzón de una persona y la plataforma
no debe alterar su bandeja (a diferencia de excel_terceros_email.py, que lee
una cuenta operativa y sí marca \\Seen).

Como no se usa UNSEEN, la deduplicación va por Message-ID contra la tabla
mandato_correos -- ver email_sync.py.
"""
from __future__ import annotations

import email
import imaplib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from app.core.config import settings

logger = logging.getLogger("mandatos.imap")


@dataclass
class CorreoCrudo:
    message_id: str
    fecha: datetime
    remitente: str
    asunto: str
    cuerpo: str                                    # texto plano ya resuelto
    adjuntos: list[tuple[str, bytes]] = field(default_factory=list)


def _decodifica(valor: str | None) -> str:
    """Cabecera RFC2047 ('=?UTF-8?B?...?=') → str legible."""
    if not valor:
        return ""
    try:
        return str(make_header(decode_header(valor)))
    except Exception:
        return valor


def _cuerpo_de(msg: email.message.Message) -> str:
    """Texto del correo. Prefiere text/plain; si no hay, convierte el HTML."""
    from app.services.mandatos.email_parser import html_a_texto

    plano, html = "", ""
    for parte in msg.walk():
        if parte.get_content_maintype() == "multipart" or parte.get_filename():
            continue
        try:
            crudo = parte.get_payload(decode=True) or b""
            texto = crudo.decode(parte.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if parte.get_content_type() == "text/plain" and not plano:
            plano = texto
        elif parte.get_content_type() == "text/html" and not html:
            html = texto
    return plano.strip() or html_a_texto(html)


def _adjuntos_de(msg: email.message.Message) -> list[tuple[str, bytes]]:
    salida: list[tuple[str, bytes]] = []
    for parte in msg.walk():
        nombre = _decodifica(parte.get_filename())
        if not nombre:
            continue
        contenido = parte.get_payload(decode=True)
        if contenido:
            salida.append((nombre, contenido))
    return salida


def buscar_correos(remitente: str, dias: int = 30) -> list[CorreoCrudo]:
    """Correos de `remitente` recibidos en los últimos `dias`.

    Devuelve [] ante cualquier fallo de conexión, autenticación o búsqueda --
    nunca lanza hacia el llamador, para no tumbar el scheduler.
    """
    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("IMAP mandatos: credenciales no configuradas, se omite la revisión")
        return []

    try:
        imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        imap.login(settings.MANDATOS_IMAP_USER, settings.MANDATOS_IMAP_PASSWORD)
    except Exception as exc:
        logger.error("IMAP mandatos: no se pudo conectar/autenticar contra %s: %s",
                     settings.IMAP_HOST, exc)
        return []

    correos: list[CorreoCrudo] = []
    try:
        imap.select("INBOX", readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{desde}" FROM "{remitente}")')
        if status != "OK":
            logger.error("IMAP mandatos: búsqueda falló para %s: %s", remitente, data)
            return []

        for uid in (data[0].split() if data and data[0] else []):
            status, msg_data = imap.fetch(uid, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            message_id = (msg.get("Message-ID") or "").strip()
            if not message_id:
                logger.warning("IMAP mandatos: correo sin Message-ID, se omite -- asunto=%r",
                               msg.get("Subject"))
                continue
            try:
                fecha = parsedate_to_datetime(msg.get("Date"))
            except Exception:
                fecha = datetime.now(timezone.utc)
            if fecha.tzinfo is None:
                fecha = fecha.replace(tzinfo=timezone.utc)
            correos.append(CorreoCrudo(
                message_id=message_id,
                fecha=fecha,
                remitente=remitente,
                asunto=_decodifica(msg.get("Subject")),
                cuerpo=_cuerpo_de(msg),
                adjuntos=_adjuntos_de(msg),
            ))
    except Exception as exc:
        logger.error("IMAP mandatos: fallo leyendo correos de %s: %s", remitente, exc)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        try:
            imap.logout()
        except Exception:
            pass
    return correos
```

`readonly=True` en el `select` es la garantía a nivel de protocolo de que no se
modifica nada en la bandeja, ni siquiera por accidente.

- [ ] **Step 3: Verificar que importa y que sin credenciales no revienta**

Run: `python -c "from app.services.mandatos.imap_client import buscar_correos; print(buscar_correos('x@y.com'))"`
Expected: `[]` (las credenciales no están en el entorno local)

- [ ] **Step 4: Commit**

```bash
git add app/core/config.py app/services/mandatos/imap_client.py
git commit -m "feat(mandatos): cliente IMAP de solo lectura para el buzon de mandatos"
```

---

### Task 8: `email_sync` — orquestación y transiciones

El corazón. Todas las reglas del spec §6.4 y §8.

**Files:**
- Create: `app/services/mandatos/email_sync.py`
- Create: `tests/test_mandatos_email_sync.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_mandatos_email_sync.py`:

```python
"""Tests de la decisión de sincronización -- pura, sin BD ni IMAP.

decidir_acciones() concentra las reglas de negocio del spec §6.4 y se prueba
sola; aplicar_correo() (que sí toca la BD) queda cubierto por el uso real.
"""
from datetime import datetime, timezone

from app.services.mandatos.email_sync import decidir_acciones, FUENTE_REVISORIA, FUENTE_ENVIO
from app.services.mandatos.imap_client import CorreoCrudo
from tests.fixtures_mandatos_correos import (
    REVISORIA_OBSERVACIONES, REVISORIA_SEGUIMIENTO, REVISORIA_MIXTO,
    ENVIO_INVERSIONISTA, ENVIO_INVERSIONISTA_ADJUNTOS,
    LIQUIDACION_PRELIMINAR, LIQUIDACION_PRELIMINAR_ADJUNTOS,
)

AHORA = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)


def _correo(cuerpo, adjuntos=(), asunto="Certificados", remitente="vlondono@jbp.com.co"):
    return CorreoCrudo(
        message_id=f"<{hash(cuerpo)}@test>", fecha=AHORA, remitente=remitente,
        asunto=asunto, cuerpo=cuerpo,
        adjuntos=[(n, b"%PDF-1.4 fake") for n in adjuntos],
    )


def test_observaciones_producen_con_correcciones():
    d = decidir_acciones(_correo(REVISORIA_OBSERVACIONES), FUENTE_REVISORIA)
    assert d["clasificacion"] == "molde_simple"
    assert [a["cmu"] for a in d["acciones"]] == [
        "CMU1255", "CMU1266", "CMU1269", "CMU1270", "CMU1271", "CMU1284",
    ]
    assert all(a["estado_destino"] == "con_correcciones" for a in d["acciones"])


def test_seguimiento_no_produce_acciones_de_texto():
    """El correo donde CMU1255 quedó resuelto: cero acciones, revisión manual."""
    d = decidir_acciones(_correo(REVISORIA_SEGUIMIENTO), FUENTE_REVISORIA)
    assert d["clasificacion"] == "seguimiento"
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_seguimiento_con_pdf_igual_procesa_el_adjunto():
    """La compuerta gobierna el texto, no los adjuntos (spec §6.3)."""
    d = decidir_acciones(
        _correo(REVISORIA_SEGUIMIENTO, adjuntos=["CMU1266-firmado.pdf"]), FUENTE_REVISORIA
    )
    assert [a["cmu"] for a in d["acciones"]] == ["CMU1266"]
    assert d["acciones"][0]["estado_destino"] == "firmado"
    assert d["requiere_revision"] is True


def test_correo_mixto_produce_correcciones_y_firmados():
    d = decidir_acciones(
        _correo(REVISORIA_MIXTO, adjuntos=["CMU1052-Mandato-Costos-Sol-X.pdf"]),
        FUENTE_REVISORIA,
    )
    por_cmu = {a["cmu"]: a["estado_destino"] for a in d["acciones"]}
    assert por_cmu["CMU1122"] == "con_correcciones"
    assert por_cmu["CMU1052"] == "firmado"      # el adjunto manda sobre el texto


def test_envio_a_inversionista_desde_los_adjuntos():
    d = decidir_acciones(
        _correo(ENVIO_INVERSIONISTA, adjuntos=ENVIO_INVERSIONISTA_ADJUNTOS,
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert sorted(a["cmu"] for a in d["acciones"]) == [
        "CMU1135", "CMU1139", "CMU1141", "CMU1142",
    ]
    assert all(a["estado_destino"] == "enviado_inversionista" for a in d["acciones"])


def test_liquidacion_preliminar_no_produce_nada():
    """Caso negativo: menciona 'certificados de mandato' pero no trae adjuntos."""
    d = decidir_acciones(
        _correo(LIQUIDACION_PRELIMINAR, adjuntos=LIQUIDACION_PRELIMINAR_ADJUNTOS,
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert d["acciones"] == []
    assert d["requiere_revision"] is False      # nada que revisar: no era un envío


def test_envio_ignora_adjuntos_que_no_son_pdf_de_mandato():
    d = decidir_acciones(
        _correo(ENVIO_INVERSIONISTA, adjuntos=["REGISTRO MANDATOS.xlsx"],
                remitente="jessica@unergy.io"),
        FUENTE_ENVIO,
    )
    assert d["acciones"] == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_mandatos_email_sync.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.mandatos.email_sync'`

- [ ] **Step 3: Implementar `decidir_acciones`**

Crear `app/services/mandatos/email_sync.py`:

```python
"""Orquestación: correos → decisiones → base de datos.

Separado en dos mitades a propósito:
  - decidir_acciones(): pura. Correo → qué habría que hacer. Testeable sola.
  - aplicar_correo(): impura. Toma esas decisiones y las escribe en la BD,
    respetando la máquina de estados y sin pisar cambios manuales.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mandatos import Mandato, MandatoCorreo
from app.services.mandatos.email_parser import (
    CLASIF_MOLDE_SIMPLE, CLASIF_SEGUIMIENTO, clasificar_correo,
    cmu_al_inicio_de_nombre, extraer_observaciones, solo_pdfs,
)
from app.services.mandatos.imap_client import CorreoCrudo, buscar_correos
from app.services.mandatos_service import extraer_cmu_de_nombre, transicion_valida

logger = logging.getLogger("mandatos.email_sync")

FUENTE_REVISORIA = "revisoria"
FUENTE_ENVIO = "envio_inversionista"

REMITENTE_REVISORIA = "vlondono@jbp.com.co"
REMITENTE_ENVIO = "jessica@unergy.io"

_PDF_DIR = Path("uploads/mandatos")


def decidir_acciones(correo: CorreoCrudo, fuente: str) -> dict:
    """Correo → {'clasificacion', 'acciones', 'requiere_revision', 'adjuntos_sin_cmu'}.

    Cada acción es {'cmu', 'estado_destino', 'observacion', 'adjunto'}. Pura: no
    consulta la base ni escribe archivos, solo dice qué habría que hacer.
    """
    nombres = [n for n, _ in correo.adjuntos]
    pdfs = solo_pdfs(nombres)
    acciones: list[dict] = []
    adjuntos_sin_cmu: list[str] = []

    if fuente == FUENTE_ENVIO:
        # Fuente 3: el CMU viene en el nombre del adjunto. El cuerpo no se lee --
        # por eso los correos de "Liquidación preliminar", que mencionan
        # "certificados de mandato" sin adjuntarlos, no producen nada.
        for nombre in pdfs:
            cmu = cmu_al_inicio_de_nombre(nombre)
            if cmu:
                acciones.append({"cmu": cmu, "estado_destino": "enviado_inversionista",
                                 "observacion": None, "adjunto": nombre})
        return {"clasificacion": CLASIF_MOLDE_SIMPLE if acciones else "desconocido",
                "acciones": acciones, "requiere_revision": False,
                "adjuntos_sin_cmu": []}

    # Fuente 1/2: revisoría.
    clasificacion = clasificar_correo(correo.asunto, correo.cuerpo)

    # Fuente 2 -- los adjuntos se procesan SIEMPRE, cualquiera sea la
    # clasificación: un archivo es un hecho objetivo, no una interpretación.
    cmus_con_pdf: set[str] = set()
    for nombre in pdfs:
        cmu = extraer_cmu_de_nombre(nombre)
        if cmu:
            cmus_con_pdf.add(cmu)
            acciones.append({"cmu": cmu, "estado_destino": "firmado",
                             "observacion": None, "adjunto": nombre})
        else:
            adjuntos_sin_cmu.append(nombre)

    # Fuente 1 -- solo si el texto encaja en el molde conocido.
    if clasificacion == CLASIF_MOLDE_SIMPLE:
        for obs in extraer_observaciones(correo.cuerpo):
            if obs["cmu"] in cmus_con_pdf:
                continue        # el PDF firmado manda sobre la observación
            acciones.append({"cmu": obs["cmu"], "estado_destino": "con_correcciones",
                             "observacion": obs["observacion"], "adjunto": None})

    requiere_revision = clasificacion != CLASIF_MOLDE_SIMPLE or bool(adjuntos_sin_cmu)
    return {"clasificacion": clasificacion, "acciones": acciones,
            "requiere_revision": requiere_revision,
            "adjuntos_sin_cmu": adjuntos_sin_cmu}
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_mandatos_email_sync.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_sync.py tests/test_mandatos_email_sync.py
git commit -m "feat(mandatos): reglas de decision por correo (Fuentes 1, 2 y 3)"
```

- [ ] **Step 6: Implementar la aplicación a base de datos**

Agregar a `app/services/mandatos/email_sync.py`:

```python
def _guardar_adjunto(nombre: str, contenido: bytes) -> str:
    _PDF_DIR.mkdir(parents=True, exist_ok=True)
    destino = _PDF_DIR / nombre
    destino.write_bytes(contenido)
    return str(destino)


def _aplicar_accion(db: Session, accion: dict, correo: CorreoCrudo, fuente: str) -> dict:
    """Aplica una acción a su mandato. Devuelve el registro para `detalle`.

    Nunca fuerza una transición: si la máquina de estados no la permite, se
    registra el conflicto y el mandato queda como estaba.
    """
    cmu = accion["cmu"]
    # El correo no dice a qué período pertenece el CMU. La restricción única es
    # (cmu, periodo), así que en teoría un mismo CMU puede repetirse entre
    # períodos; se toma el más reciente, que es el que está en curso.
    m = db.execute(
        select(Mandato).where(Mandato.cmu == cmu).order_by(Mandato.periodo.desc())
    ).scalars().first()
    if not m:
        return {"cmu": cmu, "resultado": "cmu_no_encontrado"}

    destino = accion["estado_destino"]
    estado_previo = m.estado
    fecha_correo = correo.fecha.date()

    # Un PDF de envío a inversionista es evidencia de que el mandato fue firmado.
    # Si viene desde enviado_revisoria o corregido, se encadena firmado →
    # enviado_inversionista. Desde con_correcciones NO: enviar al inversionista
    # un mandato con observaciones pendientes es una anomalía que debe verse.
    cadena = [destino]
    if destino == "enviado_inversionista" and estado_previo in ("enviado_revisoria", "corregido"):
        cadena = ["firmado", "enviado_inversionista"]

    estado = estado_previo
    for paso in cadena:
        if estado == paso:
            continue
        if not transicion_valida(estado, paso):
            return {"cmu": cmu, "resultado": "transicion_invalida",
                    "estado_previo": estado_previo, "estado_destino": paso}
        estado = paso

    if accion["adjunto"]:
        contenido = dict(correo.adjuntos).get(accion["adjunto"])
        if contenido:
            m.pdf_firmado_ruta = _guardar_adjunto(accion["adjunto"], contenido)
            m.pdf_firmado_nombre = accion["adjunto"]

    if estado != estado_previo:
        m.estado = estado
    if accion["observacion"]:
        m.observacion = accion["observacion"]
    if "firmado" in cadena or destino == "firmado":
        m.fecha_firmado = m.fecha_firmado or fecha_correo
    if destino == "enviado_inversionista":
        m.fecha_envio_inversionista = fecha_correo
        m.correo_ref_envio = correo.message_id
    if fuente == FUENTE_REVISORIA:
        m.correo_ref_revisoria = correo.message_id

    return {"cmu": cmu, "resultado": "aplicado", "mandato_id": m.id,
            "estado_previo": estado_previo, "estado_nuevo": estado}


def procesar_correo(db: Session, correo: CorreoCrudo, fuente: str) -> MandatoCorreo:
    """Procesa un correo y devuelve su fila de bitácora (sin commit)."""
    decision = decidir_acciones(correo, fuente)
    registros = [_aplicar_accion(db, a, correo, fuente) for a in decision["acciones"]]
    hubo_cambio = any(r["resultado"] == "aplicado" for r in registros)
    hubo_problema = any(r["resultado"] != "aplicado" for r in registros)

    return MandatoCorreo(
        message_id=correo.message_id,
        fecha=correo.fecha,
        remitente=correo.remitente,
        asunto=correo.asunto[:1000] if correo.asunto else None,
        fuente=fuente,
        clasificacion=decision["clasificacion"],
        resultado="aplicado" if hubo_cambio else "omitido",
        requiere_revision=decision["requiere_revision"] or hubo_problema,
        detalle={"acciones": registros,
                 "adjuntos_sin_cmu": decision["adjuntos_sin_cmu"]},
    )


def revisar_correos_mandatos() -> None:
    """Punto de entrada del cron. Nunca lanza hacia el scheduler.

    Transacción POR CORREO: un correo que revienta no arrastra a los demás.
    """
    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("IMAP mandatos: credenciales no configuradas, se omite la corrida")
        return

    db = SessionLocal()
    try:
        vistos = {mid for (mid,) in db.execute(select(MandatoCorreo.message_id)).all()}
        for remitente, fuente in ((REMITENTE_REVISORIA, FUENTE_REVISORIA),
                                  (REMITENTE_ENVIO, FUENTE_ENVIO)):
            for correo in buscar_correos(remitente):
                if correo.message_id in vistos:
                    continue
                try:
                    fila = procesar_correo(db, correo, fuente)
                    db.add(fila)
                    db.commit()
                    vistos.add(correo.message_id)
                    logger.info("IMAP mandatos: %s -- %s/%s, %d acciones",
                                correo.message_id, fila.clasificacion, fila.resultado,
                                len(fila.detalle.get("acciones", [])))
                except Exception as exc:
                    db.rollback()
                    logger.error("IMAP mandatos: fallo procesando %s: %s",
                                 correo.message_id, exc)
                    try:
                        db.add(MandatoCorreo(
                            message_id=correo.message_id, fecha=correo.fecha,
                            remitente=correo.remitente,
                            asunto=(correo.asunto or "")[:1000],
                            fuente=fuente, clasificacion="desconocido",
                            resultado="error", requiere_revision=True,
                            detalle={"error": str(exc)},
                        ))
                        db.commit()
                        vistos.add(correo.message_id)
                    except Exception:
                        db.rollback()
    finally:
        db.close()
```

Agregar los imports que faltan al inicio del archivo, junto a los existentes:

```python
from app.core.config import settings
from app.core.database import SessionLocal
```

- [ ] **Step 7: Verificar que importa y que los tests siguen pasando**

Run: `python -c "from app.services.mandatos.email_sync import revisar_correos_mandatos; print('ok')"`
Expected: `ok`

Run: `python -m pytest tests/test_mandatos_email_sync.py tests/test_mandatos_email_parser.py tests/test_mandatos.py -v`
Expected: PASS, todos

- [ ] **Step 8: Commit**

```bash
git add app/services/mandatos/email_sync.py
git commit -m "feat(mandatos): aplicar decisiones de correo a la BD con transaccion por correo"
```

---

### Task 9: Cron y endpoints

**Files:**
- Modify: `app/main.py` (función programada ~línea 2521 y registro ~línea 3518)
- Modify: `app/api/v1/mandatos.py`

- [ ] **Step 1: Agregar la función programada**

En `app/main.py`, después de `_scheduled_excel_terceros_cedillanos()`:

```python
def _scheduled_correos_mandatos():
    """Lee adhara@unergy.io y actualiza el estado de los mandatos de costos.

    Cada hora de 7am a 7pm: los correos de la revisoría y los envíos a
    inversionistas llegan en horario laboral y no son urgentes (a diferencia
    del de Cedillanos, que debe procesarse antes de las 6am). Sin correos
    nuevos la corrida es solo un IMAP SEARCH que no toca la base."""
    from app.services.mandatos.email_sync import revisar_correos_mandatos

    revisar_correos_mandatos()
```

- [ ] **Step 2: Registrar el cron**

En `app/main.py`, justo después del bloque `if settings.SMTP_USER and settings.SMTP_PASSWORD:` que registra los dos jobs de Cedillanos:

```python
            if settings.MANDATOS_IMAP_USER and settings.MANDATOS_IMAP_PASSWORD:
                _mgs_scheduler.add_job(
                    _scheduled_correos_mandatos,
                    CronTrigger(hour="7-19", minute=5, timezone=settings.TIMEZONE),
                    id="correos_mandatos",
                    name="Mandatos -- lectura de correo por IMAP (7am-7pm)",
                )
```

- [ ] **Step 3: Agregar los endpoints**

**Ubicación crítica:** estos endpoints van **ANTES** de cualquier ruta con
`/{mandato_id}` (hay un `@router.patch("/{mandato_id}")` alrededor de la línea
103). Si `GET /correos` queda después de un `GET /{mandato_id}`, FastAPI intenta
parsear `"correos"` como entero y devuelve 422 — la ruta nunca se alcanza.
Colocarlos justo después de los imports y las constantes del módulo, antes del
primer decorador `@router` que use `{mandato_id}`.

En `app/api/v1/mandatos.py`:

```python
@router.get("/correos")
def listar_correos(limite: int = 100, solo_revision: bool = False,
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Bitácora de correos leídos por IMAP, del más reciente al más viejo."""
    q = select(MandatoCorreo).order_by(MandatoCorreo.fecha.desc())
    if solo_revision:
        q = q.where(MandatoCorreo.requiere_revision.is_(True))
    filas = db.execute(q.limit(min(limite, 500))).scalars().all()
    return [{
        "id": f.id, "fecha": f.fecha.isoformat(), "remitente": f.remitente,
        "asunto": f.asunto, "fuente": f.fuente, "clasificacion": f.clasificacion,
        "resultado": f.resultado, "requiere_revision": f.requiere_revision,
        "revertido": f.revertido, "detalle": f.detalle,
    } for f in filas]


@router.post("/correos/{correo_id}/revertir")
def revertir_correo(correo_id: int, db: Session = Depends(get_db),
                    _=Depends(get_current_user)):
    """Devuelve al estado previo los mandatos que este correo cambió.

    No borra PDFs guardados ni la fila de bitácora: revertir un estado no
    des-firma un documento que sí existe.
    """
    fila = db.get(MandatoCorreo, correo_id)
    if not fila:
        raise HTTPException(404, "Correo no encontrado.")
    if fila.revertido:
        raise HTTPException(409, "Este correo ya fue revertido.")

    revertidos = []
    for accion in (fila.detalle or {}).get("acciones", []):
        if accion.get("resultado") != "aplicado":
            continue
        m = db.get(Mandato, accion.get("mandato_id"))
        if not m:
            continue
        m.estado = accion["estado_previo"]
        revertidos.append(m.cmu)

    fila.revertido = True
    fila.requiere_revision = True
    db.commit()
    return {"revertidos": revertidos, "total": len(revertidos)}
```

Agregar `MandatoCorreo` al import de modelos existente al inicio de
`app/api/v1/mandatos.py` (la línea que ya importa `Mandato` desde
`app.models.mandatos`).

- [ ] **Step 4: Verificar que la app arranca y las rutas existen**

Run: `python -c "import app.main; rutas=[r.path for r in app.main.app.routes if 'correos' in r.path]; print(rutas)"`
Expected: `['/api/v1/mandatos/correos', '/api/v1/mandatos/correos/{correo_id}/revertir']`

- [ ] **Step 5: Correr toda la suite de mandatos**

Run: `python -m pytest tests/test_mandatos_email_parser.py tests/test_mandatos_email_sync.py tests/test_mandatos.py tests/test_conciliacion_mandatos.py -v`
Expected: PASS, todos

- [ ] **Step 6: Commit**

```bash
git add app/main.py app/api/v1/mandatos.py
git commit -m "feat(mandatos): cron horario de lectura IMAP + endpoints de bitacora"
```

---

## Verificación en producción

Los tests no prueban que la credencial funcione — solo el primer deploy lo hace.
Recordar que Sara encontró el bug del filtro `FRT85329` así, no antes.

Después del merge a master y del deploy automático de Railway:

1. En el **dashboard de Railway** → Deploy Logs, buscar `IMAP mandatos`.
2. Resultado bueno: líneas `IMAP mandatos: <message-id> -- molde_simple/aplicado, N acciones`.
3. Resultado malo típico: `no se pudo conectar/autenticar` → revisar que
   `MANDATOS_IMAP_PASSWORD` sea el App Password de 16 caracteres (no la contraseña
   normal de la cuenta) y que `MANDATOS_IMAP_USER` sea exactamente `adhara@unergy.io`.
4. Contrastar con `GET /api/v1/mandatos/correos?limite=20` para ver la bitácora.
5. Revisar en la pestaña Mandatos que los cambios de estado tengan sentido contra
   los correos reales del último mes. Si alguno está mal, `POST
   /api/v1/mandatos/correos/{id}/revertir`.

**El primer deploy procesa 30 días de correos hacia atrás de una vez.** Es
intencional (recupera el histórico reciente), pero conviene revisar esa primera
tanda con calma antes de confiar en el automatismo.

## Pendiente para planes aparte

- **Panel "Correos leídos"** en `src/views/Finanzas/MandatosOperaciones.vue`
  (repo `unergy-operaciones-frontend`), consumiendo `GET /mandatos/correos` y el
  botón de revertir. Spec §9.
- **Nombres de PDF de la revisoría.** No están verificados. Si Vanessa no usa la
  convención `CMU####`, sus adjuntos caerán en `adjuntos_sin_cmu` y quedarán para
  asociación manual — el sistema lo reporta, no lo esconde. Confirmar con el
  primer correo real que llegue.
