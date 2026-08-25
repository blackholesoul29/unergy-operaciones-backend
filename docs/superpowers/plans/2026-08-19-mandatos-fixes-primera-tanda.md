# Mandatos — arreglos de la primera tanda real

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir los cuatro defectos que destapó la primera corrida contra 94 correos reales, y que ningún fixture iba a mostrar.

**Architecture:** Tres arreglos independientes: la pasada de Enviados necesita su propia fuente (hoy usa la de entrada, que significa lo contrario); el parser de nombres debe aceptar la convención de ingresos; y volver a aplicar el mismo estado debe ser un no-op, no un error.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0, pytest. Sin dependencias nuevas.

**Rama:** `feat/mandatos-fase-b-imap`

---

## Qué pasó en la primera corrida

94 correos procesados. Resultado:

```
Por resultado:      omitido 91, aplicado 3
Por clasificación:  desconocido 58, seguimiento 36, molde_simple 0
Acciones:           aplicado 20, transicion_invalida 40, cmu_no_encontrado 1
Reconciliación:     enviados 1, sin_registro_de_envio 62
```

**Nada se corrompió** — cero estados equivocados. Todos los defectos son de omisión, que es el lado hacia el que se diseñó fallar. Pero tres de ellos dejan capacidades enteras inertes.

El cuarto -- **cero correos clasificados `molde_simple`**, o sea la Fuente 1 muerta -- estuvo fuera de alcance hasta conseguir cuerpos reales de correos de correcciones. Ya se consiguieron (Tarea 4).

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/mandatos_service.py` | `ZIP_NOMBRE_RE` acepta la convención de ingresos; se limpia el sufijo `(N)` de Gmail |
| `app/services/mandatos/finanzas_sync.py` | fuente nueva para lo saliente; no-op al reaplicar el mismo estado |
| `tests/test_mandatos.py` | nombres reales de la primera tanda |
| `tests/test_mandatos_finanzas_sync.py` | casos de la fuente saliente |

---

### Task 1: Reaplicar el mismo estado es un no-op

40 de 61 acciones fallaron con `transicion_invalida`, todas de la forma
`estado_previo: "firmado" → estado_destino: "firmado"`. El grafo dice que no es una
transición válida, y literalmente no lo es — pero conceptualmente no es un conflicto,
es idempotencia: a un mandato ya firmado le volvió a llegar su PDF firmado.

Hoy eso llena el panel de revisión de ruido y esconde los conflictos de verdad.

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py` (`_aplicar`, ambas ramas)
- Modify: `tests/test_mandatos_finanzas_sync.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_mandatos_finanzas_sync.py`:

```python
from types import SimpleNamespace as NS

from app.services.mandatos.finanzas_sync import _aplicar


class _DBFake:
    """Sesión mínima: devuelve la fila que se le configure."""

    def __init__(self, fila):
        self._fila = fila

    def query(self, _modelo):
        return self

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def first(self):
        return self._fila


def test_reaplicar_el_mismo_estado_no_es_error():
    """Caso real: 40 de 61 acciones de la primera tanda eran firmado→firmado.

    Volver a recibir el PDF firmado de un mandato ya firmado es idempotencia,
    no un conflicto. Reportarlo como transicion_invalida llena el panel de
    revisión de ruido y esconde los conflictos reales.
    """
    fila = NS(id=7, cmu="CMU1270", estado="firmado", periodo=None, tipo="costo",
              drive_url="https://drive/x", comentario=None, correo_ref=None,
              fecha_firma=None)
    accion = {"cmu": "CMU1270", "estado": "firmado", "periodo": None,
              "adjunto": None, "comentario": None}
    correo = NS(message_id="<x@test>", fecha=AHORA, adjuntos=[])
    r = _aplicar(_DBFake(fila), accion, correo)
    assert r["resultado"] == "sin_cambio"
    assert fila.estado == "firmado"
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -k reaplicar -v`
Expected: FAIL — devuelve `transicion_invalida` en vez de `sin_cambio`.

- [ ] **Step 3: Implementar**

En `_aplicar`, en la rama que resuelve por CMU, justo después de obtener `existente` y
antes de validar la transición:

```python
        destino = accion["estado"]
        if existente.estado == destino:
            # Idempotencia, no conflicto: llegó otra vez lo mismo. Pasa seguido
            # -- la revisoría reenvía el hilo con los mismos adjuntos. Marcarlo
            # como transición inválida llenaba el panel de revisión de ruido
            # (40 de 61 acciones en la primera tanda) y escondía los conflictos
            # de verdad.
            return {"cmu": accion["cmu"], "resultado": "sin_cambio",
                    "estado": destino}
        if not transicion_firma_valida(existente.estado, destino):
```

Y en la rama que resuelve por identidad, con el mismo criterio, después de calcular
`previo` y `destino`:

```python
    if existente and previo == destino:
        return {"cmu": accion["cmu"], "resultado": "sin_cambio", "estado": destino,
                "id": existente.id}
    if existente and not transicion_firma_valida(previo, destino):
```

`sin_cambio` no cuenta como problema: `procesar_correo_finanzas` marca
`requiere_revision` cuando algún resultado no es `"aplicado"`, así que hay que
excluirlo también. Cambiar esa línea:

```python
    problema = any(r["resultado"] not in ("aplicado", "sin_cambio") for r in registros)
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -v`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py tests/test_mandatos_finanzas_sync.py
git commit -m "fix(mandatos): reaplicar el mismo estado es no-op, no transicion invalida"
```

---

### Task 2: El parser acepta la convención de ingresos

Los mandatos de autoconsumo e ingresos se llaman `CMU####-Mandato-{Proyecto}.pdf`, sin
la palabra `Costos`. `ZIP_NOMBRE_RE` la exige, así que todos esos adjuntos quedaron sin
identificar — es la razón principal de que de 71 correos de Jessica solo se aplicaran 3.

Además Gmail agrega ` (1)`, ` (2)` a los nombres repetidos, y ese sufijo se estaba
colando dentro del nombre del inversionista, lo que partiría la identidad en dos filas.

**Files:**
- Modify: `app/services/mandatos_service.py`
- Modify: `tests/test_mandatos.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `tests/test_mandatos.py`, junto a los demás de `parsear_nombre_zip`. Todos
son nombres **reales**, tomados de la bitácora de la primera corrida:

```python
def test_parsear_nombre_zip_convencion_ingresos_sin_costos():
    """Autoconsumo/ingresos: `CMU####-Mandato-{Proyecto}.pdf`, sin 'Costos'."""
    r = parsear_nombre_zip("CMU1182-Mandato-Iml Empaques Colombia Sas.pdf")
    assert r == {"cmu": "CMU1182", "proyecto": "Iml Empaques Colombia Sas",
                 "inversionista": ""}


def test_parsear_nombre_zip_ingresos_con_inversionista():
    r = parsear_nombre_zip(
        "CMU1228-Mandato-GD Delta 1-GRANJAS SOLARES DELTA S.A.S. E.S.P.pdf")
    assert r == {"cmu": "CMU1228", "proyecto": "GD Delta 1",
                 "inversionista": "GRANJAS SOLARES DELTA S.A.S. E.S.P"}


def test_parsear_nombre_zip_proyecto_terminado_en_punto():
    r = parsear_nombre_zip("CMU0907-Mandato-Arcillas San Simon S.A.S..pdf")
    assert r == {"cmu": "CMU0907", "proyecto": "Arcillas San Simon S.A.S.",
                 "inversionista": ""}


def test_parsear_nombre_zip_limpia_el_sufijo_de_gmail():
    """Gmail agrega ' (1)' a los adjuntos repetidos. Sin limpiarlo se cuela en
    el inversionista y parte la identidad en dos filas distintas."""
    r = parsear_nombre_zip(
        "CMU1255-Mandato-Costos-Minigranja Solar Esmeralda-"
        "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA (1).pdf")
    assert r["inversionista"] == (
        "PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A SOCIEDAD FIDUCIARIA")


def test_parsear_nombre_zip_ignora_un_pdf_que_no_es_mandato():
    """De la primera tanda: una liquidación adjunta en el mismo hilo."""
    assert parsear_nombre_zip("Liquidacion_CoxEnergy_Jul2026.pdf") is None
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos.py -k parsear_nombre_zip -v`
Expected: los cuatro primeros FAIL; el último (`Liquidacion_...`) PASS.

- [ ] **Step 3: Implementar**

En `app/services/mandatos_service.py`, reemplazar `ZIP_NOMBRE_RE` y agregar la limpieza:

```python
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
```

Y en `parsear_nombre_zip`, limpiar antes de parsear:

```python
    m = ZIP_NOMBRE_RE.match(_SUFIJO_GMAIL_RE.sub("", (nombre or "").strip()))
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos.py -k parsear_nombre_zip -v`
Expected: todos PASS, incluidos los siete anteriores.

**Si alguno de los anteriores se rompe, PARAR y reportar.** Codifican nombres reales
de Fase A y deben seguir dando lo mismo.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos_service.py tests/test_mandatos.py
git commit -m "fix(mandatos): aceptar la convencion de ingresos y limpiar el sufijo de Gmail"
```

---

### Task 3: La pasada de Enviados registra el envío

El defecto más grave. Hoy:

```python
pasadas.append((REMITENTE_REVISORIA, FUENTE_REVISORIA, enviados, "TO"))
```

La pasada de **salida** usa la misma fuente que la de **entrada**, pero significan lo
contrario. `FUENTE_REVISORIA` solo genera acción cuando el PDF viene
`firmado_completo`, y **un mandato que sale hacia la revisoría está sin firmar por
definición** — para eso se manda. Resultado: se lee el correo, sus PDFs dan
`sin_firmas`, van a `sin_identidad`, y `fecha_envio` nunca se llena.

Por eso la reconciliación reporta `enviados: 1` y 62 en `sin_registro_de_envio`: no es
que falten datos, es que nadie los registra. Leer la carpeta de Enviados era todo el
propósito del Plan 3a y quedó inerte.

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py`
- Modify: `tests/test_mandatos_finanzas_sync.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_mandatos_finanzas_sync.py`:

```python
from app.services.mandatos.finanzas_sync import FUENTE_SALIENTE


def test_saliente_registra_el_envio_aunque_el_pdf_no_este_firmado():
    """Un mandato que va HACIA la revisoría está sin firmar por definición --
    justamente se manda para que lo firmen. Antes esto no producía nada y la
    reconciliación se quedaba sin denominador."""
    c = _correo("Adjunto los mandatos de julio para revisión.",
                [("CMU1255-Mandato-Costos-Minigranja Solar Esmeralda-STRADA ASOCIADOS S A S.pdf",
                  PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert len(d["acciones"]) == 1
    a = d["acciones"][0]
    assert a["estado"] == "sin_firma"
    assert a["cmu"] == "CMU1255"
    assert a["tercero"] == "STRADA ASOCIADOS S A S"


def test_saliente_ignora_adjuntos_que_no_son_mandato():
    c = _correo("Adjunto.", [("Liquidacion_CoxEnergy_Jul2026.pdf", PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []


def test_saliente_sin_periodo_en_el_asunto_no_inventa():
    c = _correo("Adjunto.",
                [("CMU1255-Mandato-Costos-Esmeralda-STRADA ASOCIADOS S A S.pdf", PDF_SIN)],
                asunto="Re: sin mes")
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -k saliente -v`
Expected: FAIL con `ImportError: cannot import name 'FUENTE_SALIENTE'`

- [ ] **Step 3: Implementar la fuente nueva**

En `app/services/mandatos/finanzas_sync.py`, junto a las otras constantes:

```python
# Lo que SALE hacia la revisoría. Necesita su propia fuente y no reusar
# FUENTE_REVISORIA: son direcciones opuestas y significan lo contrario. Un
# mandato entrante firmado dice "ya está listo"; uno saliente dice "acaba de
# pedirse la firma", y está sin firmar por definición.
FUENTE_SALIENTE = "saliente_revisoria"
```

En `decidir_finanzas`, agregar la rama antes de la de `FUENTE_ENVIO`:

```python
        if fuente == FUENTE_SALIENTE:
            # Registrar el envío. No importa si el PDF está firmado -- casi
            # nunca lo estará. Lo que se registra es que salió, para que la
            # reconciliación tenga contra qué comparar lo que vuelve.
            ident = _identidad(nombre, correo)
            if not ident:
                sin_identidad.append(nombre)
                continue
            acciones.append({**ident, "estado": "sin_firma", "adjunto": None,
                             "firmas": firmas, "comentario": None})
        elif fuente == FUENTE_ENVIO:
```

`adjunto` va en `None` a propósito: no se sube a Drive la copia sin firmar. Lo que
importa guardar es el documento firmado que vuelve, no el que salió.

- [ ] **Step 4: Que `sin_firma` no choque con la máquina de estados**

`transicion_firma_valida("firmado", "sin_firma")` es `False`, así que registrar el
envío de algo que ya volvió firmado se rechazaría. Pero `upsert_mandato` **no cambia
el estado** en la rama `sin_firma` — solo llena `fecha_envio`. Registrar el envío es
seguro siempre.

En `_aplicar`, antes de validar la transición en la rama por identidad:

```python
    # sin_firma solo estampa fecha_envio: upsert_mandato no toca el estado en esa
    # rama. Así que registrar un envío nunca puede degradar nada, y no debe pasar
    # por la validación de transiciones -- si no, un mandato que ya volvió firmado
    # rechazaría el registro de su propio envío.
    if destino == "sin_firma":
        pass
    elif existente and previo == destino:
        ...
```

Ajustar la cadena de condiciones para que `sin_firma` salte tanto el chequeo de
igualdad como el de transición, y siga derecho al `upsert_mandato`.

- [ ] **Step 5: Usar la fuente nueva en el ciclo**

En `revisar_correos_finanzas`, cambiar la tercera pasada:

```python
    if enviados:
        pasadas.append((REMITENTE_REVISORIA, FUENTE_SALIENTE, enviados, "TO"))
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -v`
Expected: todos PASS.

Run: `python -m pytest tests/ -q`
Expected: sin fallos.

- [ ] **Step 7: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py tests/test_mandatos_finanzas_sync.py
git commit -m "fix(mandatos): la pasada de Enviados registra el envio (reconciliacion)"
```

---

### Task 4: Recalibrar la compuerta de clasificación

Cero correos de 94 se clasificaron `molde_simple`, así que `extraer_observaciones`
nunca corrió y la Fuente 1 quedó muerta. Con cuatro cuerpos reales a la vista la causa
es clara, y son dos:

**La regla del `Re:` en el asunto bloqueaba todo.** Los asuntos reales son
`Re: Revisión mandatos de costos - Julio` porque son hilos de conversación. Esa sola
regla mandaba el 100% a `seguimiento`.

**Se confundió "esto es una respuesta" con "esto dice que algo se resolvió".**
`"en respuesta a"` y `"su respuesta"` solo marcan que hay hilo; no implican que ningún
CMU esté bien. El peligro real es el lenguaje de resolución -- *"Agradezco los ajustes
realizados para el mandato CMU1255"* -- que sí dice que uno quedó bien y los demás no.

Una respuesta que afirma un problema de forma uniforme es segura de interpretar. Correo
real del 1 jun: *"los mandatos CMU0746, CMU0747, CMU0748 y CMU0749 aún presentan
diferencias"*. Los cuatro tienen problema; no hay nada ambiguo que resolver.

Validado contra los cuatro cuerpos reales antes de escribirlo: **hoy acierta 1 de 4, con
el cambio acierta 4 de 4.**

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/fixtures_mandatos_correos.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Agregar el correo nuevo como fixture**

En `tests/fixtures_mandatos_correos.py`:

```python
# 2026-06-01 10:10 a.m. -- respuesta en hilo que SÍ es segura de interpretar:
# los cuatro CMU listados tienen el mismo problema, ninguno está resuelto.
# Contrasta con REVISORIA_SEGUIMIENTO, donde uno sí quedó bien. La diferencia
# no es que sea una respuesta, es si atribuye resolución a algún CMU.
REVISORIA_RESPUESTA_UNIFORME = """Hola Adhara,

Espero que te encuentres muy bien.

En respuesta a tu consulta sobre los mandatos CMU0746, CMU0747, CMU0748 y CMU0749, te informo que estos aún presentan diferencias en los valores de mantenimiento e IVA. Aunque el pasado viernes enviaron un auxiliar contable para corregir las inconsistencias, el error persiste.


Cordialmente
Vanessa Londoño Sánchez"""
```

- [ ] **Step 2: Escribir los tests que fallan**

En `tests/test_mandatos_email_parser.py` (importar el fixture nuevo arriba):

```python
def test_una_respuesta_uniforme_si_se_interpreta():
    """Correo real del 1 jun. Es una respuesta en hilo, pero los cuatro CMU
    tienen el mismo problema y ninguno está resuelto: no hay ambigüedad."""
    assert clasificar_correo(
        "Re: Revisión mandatos de costos - Junio",
        REVISORIA_RESPUESTA_UNIFORME) == CLASIF_MOLDE_SIMPLE


def test_el_asunto_re_por_si_solo_ya_no_bloquea():
    """TODOS los asuntos reales empiezan por Re:, porque son hilos. Esa regla
    sola clasificó 94 de 94 correos como seguimiento y dejó la Fuente 1 muerta."""
    assert clasificar_correo(
        "Re: Revisión mandatos de costos - Julio",
        REVISORIA_OBSERVACIONES) == CLASIF_MOLDE_SIMPLE


def test_el_correo_con_un_cmu_resuelto_sigue_bloqueado():
    """La regresión que importa: si esto se rompe, CMU1255 vuelve a marcarse
    con correcciones siendo el único que quedó bien."""
    assert clasificar_correo(
        "Re: Revisión mandatos de costos - Julio",
        REVISORIA_SEGUIMIENTO) == CLASIF_SEGUIMIENTO


def test_extrae_los_cuatro_cmu_de_la_respuesta_uniforme():
    obs = extraer_observaciones(REVISORIA_RESPUESTA_UNIFORME)
    assert [o["cmu"] for o in obs] == ["CMU0746", "CMU0747", "CMU0748", "CMU0749"]
```

- [ ] **Step 3: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_email_parser.py -k "respuesta_uniforme or asunto_re" -v`
Expected: los dos primeros y el cuarto FAIL (dan `seguimiento`); el tercero PASS.

- [ ] **Step 4: Implementar**

En `app/services/mandatos/email_parser.py`, reemplazar las señales y quitar la regla
del asunto:

```python
# Señales de que el correo declara ALGÚN CMU como resuelto. Solo estas bloquean
# la interpretación, porque solo estas crean ambigüedad sobre a cuáles aplica la
# observación. Correo real del 2026-08-10 5:50 p.m.: "Agradezco su respuesta y
# los ajustes realizados para el mandato CMU1255. Sin embargo, para los mandatos
# CMU1266... siguen siendo las mismas" -- ahí CMU1255 quedó bien y los otros no.
#
# NO van acá los marcadores de simple respuesta ("en respuesta a", "su
# respuesta"): decir que hay hilo no dice que algo se haya resuelto. Un correo
# que responde afirmando un problema uniforme -- "los mandatos CMU0746...
# CMU0749 aún presentan diferencias" -- es seguro de interpretar.
_SENALES_SEGUIMIENTO = (
    "agradezco",
    "sin embargo",
    "ajustes realizados",
    "ya se encuentra",
    "quedo corregido",
    "fueron corregid",
)

# Frases que introducen o afirman observaciones. Ampliadas con la redacción real
# vista en la bitácora de la primera corrida.
_SENALES_MOLDE = (
    "siguientes observaciones",
    "siguientes diferencias",
    "siguientes novedades",
    "siguientes inconsistencias",
    "diferencias identificadas",
    "presentan diferencias",
    "no se evidencia",
)
```

Y en `clasificar_correo`, borrar la condición del asunto:

```python
    a = _normaliza(asunto)
    c = _normaliza(cuerpo)
    # El prefijo "Re:" ya NO se usa como señal. Todos los correos reales de la
    # revisoría son respuestas dentro de un hilo, así que esa regla clasificó 94
    # de 94 como seguimiento y dejó la Fuente 1 sin ejecutarse nunca. Lo que
    # importa no es si es respuesta, sino si declara algún CMU resuelto.
    if any(s in c for s in _SENALES_SEGUIMIENTO):
        return CLASIF_SEGUIMIENTO
```

`_PREFIJOS_RESPUESTA` queda sin uso: eliminarlo. El parámetro `asunto` se conserva en
la firma —- otras partes lo pasan y puede volver a hacer falta— pero deja de leerse;
dejarlo documentado con un comentario en vez de silenciarlo.

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: todos PASS, incluidos los de clasificación anteriores.

**`test_clasificar_seguimiento_no_se_interpreta` y
`test_seguimiento_gana_sobre_molde_simple` deben seguir verdes.** Si alguno cae, el
correo con CMU1255 resuelto volvió a ser interpretable y hay que parar: ese es el caso
que toda la compuerta existe para bloquear.

- [ ] **Step 6: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/fixtures_mandatos_correos.py tests/test_mandatos_email_parser.py
git commit -m "fix(mandatos): recalibrar la compuerta -- bloqueaba el 100% de los correos"
```

---

## Verificación después del deploy

1. Correr la ingesta a demanda:
   `POST /api/v1/mandatos/ejecutar-ingesta`
   Los correos ya vistos se saltan por `Message-ID`, así que **los defectos anteriores
   no se corrigen retroactivamente**: para reprocesar hay que borrar las filas de
   `mandato_correos` de esos correos, o esperar a los correos nuevos.
2. `GET /api/v1/mandatos/correos?limite=200` — `transicion_invalida` debería caer
   drásticamente y aparecer `sin_cambio` en su lugar.
3. `GET /api/v1/finanzas/mandatos/reconciliacion?periodo=2026-08` — `enviados` debería
   dejar de ser 1.

**Sobre reprocesar el histórico:** la deduplicación por `Message-ID` es lo que hace
segura la reejecución, pero también significa que los 94 correos ya registrados no se
vuelven a mirar. Decidir aparte si vale la pena limpiarlos para reprocesar con el
parser corregido.

## Lo que queda pendiente

- El panel del frontend (Plan 4) y el retiro de la tabla vieja (Plan 5).
  `Re: Revisión mandatos de costos` real para ajustar la compuerta sin adivinar.
- El panel del frontend (Plan 4) y el retiro de la tabla vieja (Plan 5).
