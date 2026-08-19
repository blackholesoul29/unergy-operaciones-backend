# Integración Mandatos — Plan 3b: verificación de las dos firmas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la plataforma pueda abrir un PDF de mandato y decir si trae las dos firmas — la capacidad que hoy solo tiene el script local de Jessica, y la condición que ella puso para dejar de correrlo.

**Architecture:** Dos piezas. Una función **pura** de geometría decide, dadas las líneas de firma y las imágenes de una página, cuáles líneas están firmadas. Una capa delgada abre el PDF con `pdfplumber` y le pasa esos datos. La separación existe para poder probar la decisión con las coordenadas reales sin meter un documento financiero real al repositorio.

**Tech Stack:** Python 3.11, `pdfplumber` (ya en `requirements.txt`), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-mandatos-integracion-design.md` §4

**Rama:** `feat/mandatos-fase-b-imap`

---

## Qué se descubrió inspeccionando un PDF real

Muestra: `CMU1287-Mandato-Costos-Minigranja Solar Joropo.pdf`, firmado, 1 página de
709×1001 pt.

**Las firmas no son digitales.** El PDF no tiene `AcroForm`, ni campos `/Sig`, ni
anotaciones. El camino criptográfico queda descartado.

**Tampoco son texto.** Los nombres y cargos vienen impresos en la plantilla:

```
__________________________          ______________________
Flor Edith Muriel Acevedo           Eduardo Ospina Serrano
Revisor Fiscal                      Representante Legal Suplente
```

Buscar esos rótulos no distingue un firmado de uno sin firmar.

**Son imágenes pegadas sobre las líneas de firma.** Las cuatro imágenes de la página:

| top | x0 | tamaño | qué es |
|---:|---:|---|---|
| 38 | 122 | 464×49 | membrete (65% del ancho) |
| **638** | **159** | 123×29 | **firma, sobre la línea de x0=159** |
| **641** | **397** | 84×59 | **firma, sobre la línea de x0=390** |
| 864 | −6 | 720×138 | pie de página (102% del ancho) |

Cada firma se alinea horizontalmente con su línea `_____`. De ahí el diseño: **anclar
a las líneas, no a coordenadas fijas.** Una plantilla que cambie de márgenes sigue
funcionando; un umbral de coordenadas no.

**Verificado que descarta membrete y pie por la razón correcta**, no por suerte: ambos
se solapan horizontalmente con las líneas (el pie ocupa el 102% del ancho), y quedan
fuera solo por la condición vertical. Con únicamente esas dos imágenes el detector
reporta 0 de 2.

## Límite declarado: una sola muestra

**Solo se ha visto un PDF, y está firmado.** No hay muestra de uno sin firmar ni de uno
con una sola firma, así que no está confirmado que la plantilla sin firmar tenga las
mismas líneas `_____` — es lo esperable, pero es inferencia.

El diseño aguanta esa incertidumbre porque cuenta **por línea** en vez de asumir un
total, y porque distingue "no encontré líneas" de "encontré líneas sin firmar" (ver el
resultado `no_verificable`). Aun así, el primer caso real sin firmar hay que mirarlo y
agregarlo como fixture.

## Alcance

Este plan construye **solo el detector**. No lo conecta a nada: no cambia estados, no
toca `upsert_mandato`, no descarga de Drive. El cableado va en el Plan 2, que es donde
la ingesta decide `firmado` vs `sin_firma`.

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/mandatos/firmas.py` | **nuevo** — `lineas_firmadas()` puro + `verificar_firmas()` |
| `tests/test_mandatos_firmas.py` | **nuevo** — coordenadas reales como fixture |

---

### Task 1: `lineas_firmadas()` — la decisión, pura

**Files:**
- Create: `app/services/mandatos/firmas.py`
- Create: `tests/test_mandatos_firmas.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_mandatos_firmas.py`:

```python
"""Detección de firmas en los PDFs de mandato.

Las coordenadas de abajo son las REALES, medidas sobre
CMU1287-Mandato-Costos-Minigranja Solar Joropo.pdf (firmado, 2026-08-13). El
documento no se versiona -- trae valores y nombres reales -- así que lo que se
conserva es su geometría, que es lo que el detector necesita.
"""
from app.services.mandatos.firmas import lineas_firmadas, resumir_firmas


# Las dos líneas de firma del PDF real. Coordenadas MEDIDAS con pdfplumber, no
# estimadas -- una versión anterior de este plan traía x1 inventados (586 y 322
# en vez de 535 y 281) y los tests habrían pasado igual, validando geometría que
# no existe.
LINEAS_REALES = [
    {"x0": 390, "x1": 535, "top": 667},   # Revisor Fiscal
    {"x0": 159, "x1": 281, "top": 671},   # Representante Legal Suplente
]

MEMBRETE = {"x0": 122, "x1": 586, "top": 38}
PIE = {"x0": -6, "x1": 714, "top": 864}
FIRMA_IZQ = {"x0": 159, "x1": 282, "top": 638}
FIRMA_DER = {"x0": 397, "x1": 481, "top": 641}


def test_pdf_real_firmado_da_dos_de_dos():
    r = lineas_firmadas(LINEAS_REALES, [MEMBRETE, FIRMA_IZQ, FIRMA_DER, PIE])
    assert r == [True, True]


def test_membrete_y_pie_no_cuentan_como_firma():
    """Ambos se solapan horizontalmente con las líneas -- el pie ocupa el 102%
    del ancho. Solo la condición vertical los excluye. Si alguien relaja esa
    condición, este test lo atrapa."""
    assert lineas_firmadas(LINEAS_REALES, [MEMBRETE, PIE]) == [False, False]


def test_sin_imagenes_no_hay_firmas():
    assert lineas_firmadas(LINEAS_REALES, []) == [False, False]


def test_una_sola_firma():
    r = lineas_firmadas(LINEAS_REALES, [MEMBRETE, FIRMA_IZQ, PIE])
    assert r == [False, True]


def test_imagen_lejos_por_encima_no_cuenta():
    """Una imagen alineada pero muy arriba es otra cosa, no la firma."""
    lejana = {"x0": 159, "x1": 282, "top": 400}
    assert lineas_firmadas(LINEAS_REALES, [lejana]) == [False, False]


def test_imagen_debajo_de_la_linea_no_cuenta():
    debajo = {"x0": 159, "x1": 282, "top": 700}
    assert lineas_firmadas(LINEAS_REALES, [debajo]) == [False, False]


def test_imagen_sin_solape_horizontal_no_cuenta():
    corrida = {"x0": 600, "x1": 700, "top": 640}
    assert lineas_firmadas(LINEAS_REALES, [corrida]) == [False, False]


# ── resumir_firmas ────────────────────────────────────────────────────────────

def test_resumen_completo():
    assert resumir_firmas([True, True]) == {
        "lineas": 2, "firmadas": 2, "estado": "firmado_completo"}


def test_resumen_parcial():
    assert resumir_firmas([True, False]) == {
        "lineas": 2, "firmadas": 1, "estado": "parcial"}


def test_resumen_sin_firmas():
    assert resumir_firmas([False, False]) == {
        "lineas": 2, "firmadas": 0, "estado": "sin_firmas"}


def test_sin_lineas_es_no_verificable_no_sin_firmas():
    """Distinción crítica: si no se encontraron líneas de firma, el documento no
    es 'sin firmar' -- es que no se pudo mirar. Confundirlos haría que un PDF con
    otra plantilla se reporte como no firmado y dispare alarmas falsas, o peor,
    que se trate como concluido algo que nadie verificó."""
    assert resumir_firmas([]) == {
        "lineas": 0, "firmadas": 0, "estado": "no_verificable"}
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_firmas.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.mandatos.firmas'`

- [ ] **Step 3: Implementar la parte pura**

Crear `app/services/mandatos/firmas.py`:

```python
"""¿Trae este PDF de mandato las dos firmas?

Verificado sobre un PDF real (CMU1287, 2026-08-13): las firmas NO son digitales
-- el documento no tiene AcroForm, ni campos /Sig, ni anotaciones -- y tampoco
son texto, porque los nombres y cargos vienen impresos en la plantilla. Son
IMÁGENES pegadas encima de las líneas `_____`.

Por eso el detector se ancla a las líneas de firma que encuentra en el texto, no
a coordenadas fijas: si la plantilla cambia de márgenes sigue funcionando.

La decisión (lineas_firmadas) está separada de la lectura del PDF
(verificar_firmas) para poder probarla con las coordenadas reales sin versionar
un documento financiero real.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("mandatos.firmas")

# Una línea de firma: cinco guiones bajos o más.
_LINEA_FIRMA_RE = re.compile(r"^_{5,}$")

# Cuánto por encima de la línea puede empezar la imagen de la firma. En el PDF
# real las firmas empiezan 29 y 26 pt arriba; 70 deja margen para plantillas algo
# distintas sin llegar a alcanzar el membrete, que está a 629 pt de distancia.
_TOLERANCIA_VERTICAL = 70


def lineas_firmadas(lineas: list[dict], imagenes: list[dict],
                    tolerancia: int = _TOLERANCIA_VERTICAL) -> list[bool]:
    """Por cada línea de firma, si hay una imagen encima que la firme.

    `lineas` e `imagenes` son dicts con x0/x1/top, tal como los da pdfplumber.
    Una línea cuenta como firmada si existe una imagen que:
      - se solapa con ella horizontalmente, y
      - empieza por encima de la línea, dentro de `tolerancia` puntos.

    Las dos condiciones son necesarias: el membrete y el pie de página TAMBIÉN se
    solapan en horizontal (el pie ocupa el 102% del ancho), y solo la condición
    vertical los deja fuera.
    """
    resultado: list[bool] = []
    for ln in lineas:
        firmada = any(
            im["x1"] > ln["x0"] and im["x0"] < ln["x1"]
            and im["top"] < ln["top"]
            and (ln["top"] - im["top"]) <= tolerancia
            for im in imagenes
        )
        resultado.append(firmada)
    return resultado


def resumir_firmas(firmadas: list[bool]) -> dict:
    """{'lineas': 2, 'firmadas': 2, 'estado': 'firmado_completo'}

    `estado` distingue cuatro casos, y la distinción importa:
      firmado_completo  todas las líneas tienen firma
      parcial           algunas sí, otras no
      sin_firmas        hay líneas y ninguna está firmada
      no_verificable    NO se encontraron líneas -- no es lo mismo que sin firmar

    Confundir `no_verificable` con `sin_firmas` haría que un PDF con otra
    plantilla se reporte como no firmado, o que se dé por concluido algo que
    nadie llegó a mirar.
    """
    total = len(firmadas)
    n = sum(firmadas)
    if total == 0:
        estado = "no_verificable"
    elif n == total:
        estado = "firmado_completo"
    elif n == 0:
        estado = "sin_firmas"
    else:
        estado = "parcial"
    return {"lineas": total, "firmadas": n, "estado": estado}
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_firmas.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/firmas.py tests/test_mandatos_firmas.py
git commit -m "feat(mandatos): detectar firmas por geometria, anclado a las lineas de firma"
```

---

### Task 2: `verificar_firmas()` — abrir el PDF

**Files:**
- Modify: `app/services/mandatos/firmas.py`
- Modify: `tests/test_mandatos_firmas.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_mandatos_firmas.py` (importar `verificar_firmas` arriba):

```python
# ── verificar_firmas ──────────────────────────────────────────────────────────

def test_verificar_firmas_con_bytes_invalidos_es_no_verificable():
    """Un adjunto corrupto o que no es PDF no debe reventar el cron ni, peor,
    reportarse como 'sin firmas' -- que se leería como un problema del documento
    en vez de un problema al leerlo."""
    r = verificar_firmas(b"esto no es un pdf")
    assert r["estado"] == "no_verificable"


def test_verificar_firmas_con_bytes_vacios():
    assert verificar_firmas(b"")["estado"] == "no_verificable"


def test_verificar_firmas_con_none():
    assert verificar_firmas(None)["estado"] == "no_verificable"
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_firmas.py -k verificar -v`
Expected: FAIL con `ImportError: cannot import name 'verificar_firmas'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/firmas.py`:

```python
def verificar_firmas(contenido: bytes | None) -> dict:
    """Abre el PDF y devuelve el resumen de resumir_firmas().

    Recorre TODAS las páginas y acumula: la plantilla real tiene una sola, pero
    un mandato de varias hojas pondría las firmas en la última y buscar solo en
    la primera daría 'no_verificable' por error.

    Nunca lanza. Un adjunto corrupto, cifrado o que no es PDF devuelve
    `no_verificable`, nunca `sin_firmas`: no es lo mismo "este documento no está
    firmado" que "no pude abrirlo", y tratarlos igual convertiría un problema de
    lectura en una alarma sobre el documento.
    """
    if not contenido:
        return resumir_firmas([])

    import io

    import pdfplumber

    todas: list[bool] = []
    try:
        with pdfplumber.open(io.BytesIO(contenido)) as pdf:
            for pagina in pdf.pages:
                lineas = [
                    {"x0": w["x0"], "x1": w["x1"], "top": w["top"]}
                    for w in pagina.extract_words()
                    if _LINEA_FIRMA_RE.match(w["text"])
                ]
                if not lineas:
                    continue
                imagenes = [
                    {"x0": im["x0"], "x1": im["x1"], "top": im["top"]}
                    for im in pagina.images
                ]
                todas.extend(lineas_firmadas(lineas, imagenes))
    except Exception as exc:
        logger.warning("Firmas: no se pudo leer el PDF (%s): %s", type(exc).__name__, exc)
        return resumir_firmas([])

    return resumir_firmas(todas)
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_firmas.py -v`
Expected: 14 passed.

- [ ] **Step 5: Verificar contra el PDF real**

El PDF no está en el repo. Si tienes a mano
`CMU1287-Mandato-Costos-Minigranja Solar Joropo.pdf`, correr:

```bash
python -c "
from pathlib import Path
from app.services.mandatos.firmas import verificar_firmas
p = Path.home() / 'Downloads' / 'CMU1287-Mandato-Costos-Minigranja Solar Joropo.pdf'
print(verificar_firmas(p.read_bytes()) if p.exists() else 'PDF no disponible, se omite')
"
```
Expected si el archivo está: `{'lineas': 2, 'firmadas': 2, 'estado': 'firmado_completo'}`

Este paso es opcional — el archivo no se versiona. Si no está, seguir; las
coordenadas reales ya están cubiertas por los tests de la Tarea 1.

- [ ] **Step 6: Correr toda la suite**

Run: `python -m pytest tests/ -q`
Expected: 1253+ passed, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add app/services/mandatos/firmas.py tests/test_mandatos_firmas.py
git commit -m "feat(mandatos): verificar_firmas lee el PDF y nunca lanza"
```

---

## Lo que este plan deja listo, y lo que no

**Listo:** dado el contenido de un PDF, saber si trae las dos firmas, con los cuatro
resultados posibles bien distinguidos.

**No hace, a propósito:** no cambia el estado de ningún mandato, no descarga de Drive,
no toca `upsert_mandato`, no registra cron. El Plan 2 lo conecta: cuando la ingesta
reciba un PDF adjunto, `verificar_firmas` decidirá `firmado` en vez de deducirlo de
quién va en el campo `De:` — que es una inferencia, mientras que abrir el documento es
un hecho.

**Pendiente de muestra real:**
- Un mandato **sin firmar**, para confirmar que la plantilla trae las mismas líneas.
- Uno con **una sola firma**, para confirmar que el caso `parcial` se da en la práctica.
- Un mandato de **ingresos**, por si su plantilla difiere de la de costos.

Cuando aparezcan, agregar sus coordenadas a `tests/test_mandatos_firmas.py` igual que
las del CMU1287.
