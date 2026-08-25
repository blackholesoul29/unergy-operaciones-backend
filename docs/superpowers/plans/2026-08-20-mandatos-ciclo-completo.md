# Mandatos — cerrar el ciclo: destinatarios y estado `corregido`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la reconciliación cubra los tres tipos de mandato (costos, ingresos, autoconsumo) y que el ciclo de corrección deje de ser un callejón sin salida.

**Architecture:** Dos cambios. El cliente IMAP empieza a capturar destinatarios, y la clasificación pasa a mirar hacia dónde va el correo en vez de solo de quién viene. Y se detecta el estado `corregido`, que existía en el grafo pero nada activaba.

**Tech Stack:** Python 3.11, `imaplib`/`email` (stdlib), pytest. Sin dependencias nuevas.

**Rama:** `fix/mandatos-primera-tanda`

---

## Qué destapó la segunda corrida

Con los cuatro arreglos anteriores, la reconciliación de julio pasó de
`enviados: 1` a `enviados: 33, devueltos: 33, completo: true`. Los mandatos de
costos cuadran de punta a punta.

Pero quedan **80 sin registro de envío**, y agrupados dicen exactamente qué falta:

```
CMU1160–1182   los de AUTOCONSUMO de julio
CMU1185–1245   los de INGRESOS de julio
```

Los mandó Jessica hacia Vanessa Londoño, con copia a Adhara — correos con asunto
*"Revisión de mandatos autoconsumo - Julio"* y *"Revisión mandatos Ingresos - Julio"*.

El sistema decide qué es cada correo **solo por el remitente**: de Vanessa es
revisoría, de Jessica es envío a inversionista, y lo que esté en Enviados es
envío a revisión. Esos correos son de Jessica **hacia la revisoría**, así que se
clasifican mal y su envío nunca se registra.

Lo que los distingue es el destinatario, y `CorreoCrudo` no lo captura: tiene
remitente, asunto, cuerpo y adjuntos, pero ni `To` ni `Cc` se leen del mensaje.

## Y el estado que nunca se alcanzaba

`TRANSICIONES_FIRMA` exige pasar por `corregido` para volver de `con_comentarios`
a `firmado`. Pero **nada en el sistema emite `corregido`**, así que
`con_comentarios` es una trampa: se entra y no se sale. Por eso
`CMU1287: con_comentarios → firmado` salió rechazado.

Sí existe la señal en el mundo real (confirmado con el usuario, 2026-08-20): tras
recibir las observaciones, **Adhara o Vanessa Aguirre (`vanessag@unergy.io`)
responden compartiendo las correcciones** — *"te comparto los mandatos con
correcciones"*, *"comparto correcciones de los asientos contables"*. Eso es el
paso `corregido`.

El ciclo completo queda:

```
sin_firma → con_comentarios → corregido → firmado → enviado_inversionista
```

## Fuera de alcance

Los **27 casos de `firmado → con_comentarios`** ya se resolvieron: eran un defecto
del extractor, no una decisión de modelado. Un mandato firmado no lleva
correcciones (regla de negocio, Adhara 2026-08-20), así que esas 27 lecturas
estaban mal. Causa: el filtro de "este correo trae observaciones" era por correo
completo, y una vez pasado, toda línea con un CMU se volvía observación —
incluida la línea de cierre en la que Vanessa confirma cuáles sí quedaron bien.
Corregido con un filtro por línea (`_linea_confirma_conformidad`). La máquina de
estados había bloqueado las 27 como `transicion_invalida`, así que no llegó a
escribirse nada malo en la base.

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/mandatos/imap_client.py` | `CorreoCrudo` gana `destinatarios`; se leen `To` y `Cc` |
| `app/services/mandatos/email_parser.py` | detectar lenguaje de corrección |
| `app/services/mandatos/finanzas_sync.py` | clasificar por destino; emitir `corregido` |
| `tests/test_mandatos_email_parser.py` | tests del detector de correcciones |
| `tests/test_mandatos_finanzas_sync.py` | tests de clasificación por destino y de `corregido` |

---

### Task 1: Capturar los destinatarios

**Files:**
- Modify: `app/services/mandatos/imap_client.py`

- [x] **Step 1: Agregar el campo**

En `CorreoCrudo`, después de `remitente`:

```python
    destinatarios: str = ""   # To + Cc concatenados, en minúsculas
```

Va como una sola cadena y no como lista a propósito: lo único que se necesita es
preguntar "¿está esta dirección entre los destinatarios?", y sobre una cadena eso
es un `in`. Parsear direcciones RFC bien es sorprendentemente peludo (nombres con
comas, comillas, grupos) y acá no hace falta.

- [x] **Step 2: Leerlos del mensaje**

Donde se construye el `CorreoCrudo`, junto a `remitente`:

```python
                destinatarios=_destinatarios_de(msg),
```

Y la función auxiliar, junto a `_decodifica`:

```python
def _destinatarios_de(msg: email.message.Message) -> str:
    """To + Cc en una sola cadena en minúsculas, para buscar por substring.

    Se usa para saber HACIA DÓNDE va un correo, que es lo que distingue un envío
    a la revisoría de uno a un inversionista cuando ambos salen de la misma
    persona. Mirar solo el remitente no alcanza.
    """
    partes = [_decodifica(msg.get(cab)) for cab in ("To", "Cc")]
    return " ".join(p for p in partes if p).lower()
```

- [x] **Step 3: Verificar**

Run: `python -c "from app.services.mandatos.imap_client import CorreoCrudo; print(CorreoCrudo('<a>', __import__('datetime').datetime.now(), 'x', 'y', 'z').destinatarios == '')"`
Expected: `True` (el campo por defecto no rompe a los llamadores existentes)

Run: `python -m pytest tests/ -q` → sin fallos.

- [x] **Step 4: Commit**

```bash
git add app/services/mandatos/imap_client.py
git commit -m "feat(mandatos): CorreoCrudo captura los destinatarios (To + Cc)"
```

---

### Task 2: Clasificar por destino, no solo por remitente

Un correo que lleva a la revisoría entre sus destinatarios y trae mandatos
adjuntos **es un envío a revisión**, sin importar quién lo firme.

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py`
- Modify: `tests/test_mandatos_finanzas_sync.py`

- [x] **Step 1: Escribir los tests que fallan**

```python
def test_correo_de_jessica_hacia_la_revisoria_es_un_envio():
    """Caso real: 'Revisión de mandatos autoconsumo - Julio', mandado por Jessica
    a Vanessa con copia a Adhara. Llega al INBOX como correo de Jessica, así que
    antes se trataba como envío a inversionista y su envío nunca se registraba
    -- 80 CMU de julio quedaron sin denominador por esto."""
    c = _correo("Adjunto los mandatos de autoconsumo para revisión.",
                [("CMU1182-Mandato-Iml Empaques Colombia Sas-Ayurá S.A.S.pdf", PDF_SIN)],
                asunto="Revisión de mandatos autoconsumo - Julio",
                remitente="jessica@unergy.io")
    c.destinatarios = "vlondono@jbp.com.co, adhara@unergy.io"
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(False))
    assert [a["estado"] for a in d["acciones"]] == ["sin_firma"]


def test_correo_de_jessica_a_un_inversionista_sigue_siendo_envio():
    """Sin la revisoría entre destinatarios, se comporta como antes."""
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    c.destinatarios = "juliana@solenium.co, adhara@unergy.io"
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert [a["estado"] for a in d["acciones"]] == ["enviado_inversionista"]


def test_sin_destinatarios_se_comporta_como_antes():
    """Los correos ya registrados no traen destinatarios. No deben cambiar de
    interpretación solo porque el campo llegue vacío."""
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert [a["estado"] for a in d["acciones"]] == ["enviado_inversionista"]
```

- [x] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -k "hacia_la_revisoria" -v`
Expected: FAIL — devuelve `enviado_inversionista` en vez de `sin_firma`.

- [x] **Step 3: Implementar**

En `decidir_finanzas`, al inicio, antes del bucle de adjuntos:

```python
    # Hacia dónde va el correo manda sobre quién lo mandó. Un correo de Jessica
    # con la revisoría entre destinatarios es una PETICIÓN DE FIRMA, no una
    # entrega a un inversionista, aunque salga de la misma persona. Clasificar
    # solo por remitente dejó 80 mandatos de julio (los de ingresos y
    # autoconsumo) sin registrar su envío.
    #
    # Si `destinatarios` viene vacío -- correos leídos antes de que se
    # capturara el campo -- se conserva la fuente original en vez de adivinar.
    if (fuente == FUENTE_ENVIO and correo.destinatarios
            and REMITENTE_REVISORIA in correo.destinatarios):
        fuente = FUENTE_SALIENTE
```

- [x] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -v`
Expected: todos PASS.

- [x] **Step 5: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py tests/test_mandatos_finanzas_sync.py
git commit -m "fix(mandatos): un correo hacia la revisoria es un envio, lo mande quien lo mande"
```

---

### Task 3: Detectar el estado `corregido`

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [x] **Step 1: Escribir los tests que fallan**

```python
from app.services.mandatos.email_parser import es_correo_de_correcciones


def test_reconoce_que_se_comparten_correcciones():
    assert es_correo_de_correcciones(
        "Hola Vanessa, te comparto los mandatos con correcciones. CMU1255, CMU1266")


def test_reconoce_correcciones_de_asientos_contables():
    assert es_correo_de_correcciones(
        "Comparto correcciones de los asientos contables para CMU1270")


def test_no_confunde_una_observacion_con_una_correccion():
    """El correo de Vanessa REPORTA diferencias; no las corrige. Confundirlos
    marcaría como corregido justo lo que acaba de ser observado."""
    assert not es_correo_de_correcciones(REVISORIA_OBSERVACIONES)


def test_no_confunde_pedir_correccion_con_haberla_hecho():
    assert not es_correo_de_correcciones(
        "Por favor realizar las correcciones correspondientes en CMU1255")


def test_correcciones_vacio():
    assert not es_correo_de_correcciones("")
    assert not es_correo_de_correcciones(None)
```

- [x] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_email_parser.py -k correccion -v`
Expected: FAIL con `ImportError`.

- [x] **Step 3: Implementar**

En `email_parser.py`:

```python
# Frases con las que un correo saliente declara que las correcciones YA se
# hicieron. Confirmado con el usuario (2026-08-20): tras recibir las
# observaciones, Adhara o Vanessa Aguirre responden compartiéndolas corregidas,
# y ese es el paso que faltaba para salir de `con_comentarios`.
#
# Cada frase exige un verbo de ENTREGA ("comparto", "envío", "adjunto") junto a
# la corrección. Buscar solo "correcciones" marcaría también los correos que las
# PIDEN -- "por favor realizar las correcciones" -- que son lo contrario.
_SENALES_CORRECCION = (
    "comparto los mandatos con correcciones",
    "comparto correcciones",
    "comparto las correcciones",
    "envio las correcciones",
    "adjunto las correcciones",
    "con las correcciones realizadas",
    "correcciones de los asientos",
)


def es_correo_de_correcciones(cuerpo: str | None) -> bool:
    """Si el correo declara que las correcciones ya se hicieron y se comparten.

    Solo tiene sentido sobre correos SALIENTES hacia la revisoría. Un correo de
    la revisoría que reporta diferencias no es una corrección -- es lo contrario.
    """
    return any(s in _normaliza(cuerpo) for s in _SENALES_CORRECCION)
```

- [x] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: todos PASS.

- [x] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): reconocer un correo que comparte correcciones"
```

---

### Task 4: Emitir `corregido` desde los correos salientes

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py`
- Modify: `tests/test_mandatos_finanzas_sync.py`

- [x] **Step 1: Escribir los tests que fallan**

```python
def test_un_correo_de_correcciones_marca_corregido():
    """Confirmado con el usuario: la corrección aplica a los CMU que el correo
    nombra. Sin esto, con_comentarios era un callejón sin salida -- nada emitía
    `corregido`, así que un mandato observado no podía volver a firmarse."""
    c = _correo("Hola Vanessa, te comparto los mandatos con correcciones: "
                "CMU1255, CMU1266 y CMU1270.",
                asunto="Re: Revisión mandatos de costos - Julio",
                remitente="adhara@unergy.io")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert sorted(a["cmu"] for a in d["acciones"]) == ["CMU1255", "CMU1266", "CMU1270"]
    assert all(a["estado"] == "corregido" for a in d["acciones"])


def test_un_saliente_sin_lenguaje_de_correccion_no_marca_corregido():
    c = _correo("Adjunto los mandatos de julio para su revisión.",
                [("CMU1255-Mandato-Costos-Esmeralda-STRADA ASOCIADOS S A S.pdf", PDF_SIN)],
                asunto="Revisión mandatos de costos - Julio")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert [a["estado"] for a in d["acciones"]] == ["sin_firma"]


def test_correcciones_sin_cmu_nombrado_no_inventa():
    """Si el correo dice que comparte correcciones pero no nombra ninguno, no se
    adivina a cuáles aplica: se deja para revisión."""
    c = _correo("Te comparto los mandatos con correcciones.",
                asunto="Re: Revisión mandatos de costos - Julio")
    c.destinatarios = "vlondono@jbp.com.co"
    d = decidir_finanzas(c, FUENTE_SALIENTE, verificador=_firmas_fake(False))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True
```

- [x] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -k correccion -v`
Expected: FAIL.

- [x] **Step 3: Implementar**

En `decidir_finanzas`, después del bucle de adjuntos y antes del bloque de
observaciones de la revisoría:

```python
    # Correcciones compartidas hacia la revisoría → `corregido`, para los CMU
    # que el correo nombra. Se leen del cuerpo SIN la cita del hilo: un correo
    # de correcciones casi siempre responde al que traía las observaciones, y
    # sin recortar se marcarían como corregidos los CMU citados de ese hilo.
    if fuente == FUENTE_SALIENTE and es_correo_de_correcciones(correo.cuerpo):
        con_pdf = {a["cmu"] for a in acciones}
        nombrados = [c for c in extraer_cmus(_sin_cita(correo.cuerpo or ""))
                     if c not in con_pdf]
        for cmu in nombrados:
            acciones.append({"cmu": cmu, "estado": "corregido", "comentario": None,
                             "adjunto": None, "proyecto": None, "tercero": None,
                             "tipo": None, "periodo": None, "pa_codigo": None,
                             "firmas": None})
        if not nombrados and not acciones:
            # Dice que comparte correcciones pero no nombra ninguno. No se
            # adivina el lote: se deja visible para que alguien lo mire.
            sin_identidad.append("correo de correcciones sin CMU identificable")
```

Agregar al import de `email_parser` en la cabecera del archivo:
`es_correo_de_correcciones`, `extraer_cmus` y `_sin_cita`.

`extraer_cmus` viene de `mandatos_service` (ya existe); `_sin_cita` es privada de
`email_parser` pero se usa acá a propósito, por la razón del comentario.

- [x] **Step 4: Correr los tests**

Run: `python -m pytest tests/ -q`
Expected: sin fallos.

- [x] **Step 5: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py tests/test_mandatos_finanzas_sync.py
git commit -m "feat(mandatos): los correos de correcciones marcan corregido"
```

---

## Verificación después del deploy

Reprocesar y comparar:

```
POST /api/v1/mandatos/ejecutar-ingesta?dias=90&reprocesar_desde=2026-07-01
```

Lo que debería moverse:

| | Antes | Esperado |
|---|---|---|
| `sin_registro_de_envio` (julio) | 80 | cerca de cero |
| Acciones `corregido` | 0 | algunas |
| `transicion_invalida` | 29 | cerca de cero |

Los 29 `transicion_invalida` deberían casi desaparecer por dos vías distintas:
los 27 `firmado → con_comentarios` porque ya no se leen (filtro de conformidad
por línea), y `con_comentarios → firmado` porque se desbloquea el paso
intermedio `corregido`.
