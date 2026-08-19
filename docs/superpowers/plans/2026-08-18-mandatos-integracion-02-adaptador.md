# Integración Mandatos — Plan 2: adaptador de ingesta

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el cron lea el correo y alimente solo la tabla `finanzas_mandatos`, para que el script local de Jessica deje de ser necesario.

**Architecture:** Un adaptador nuevo compone piezas que ya existen y están probadas: el parser de Fase B decide qué dice el correo, el detector de firmas decide si un PDF está firmado, y el servicio de Finanzas hace el upsert y sube a Drive. La bitácora `mandato_correos` registra todo. La validación de transiciones vive en el adaptador, no en `upsert_mandato`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, APScheduler, pdfplumber. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-mandatos-integracion-design.md`

**Rama:** `feat/mandatos-fase-b-imap`

---

## ESTE ES EL PLAN QUE PRENDE LA ESCRITURA

Los planes 1, 3a y 3b son de solo lectura: se pueden desplegar sin consecuencias. **Este
no.** Al terminarlo, un cron escribe cada hora en una tabla con datos reales de
producción.

**Recomendación: desplegar 1, 3a y 3b primero** y confirmar en los logs de Railway que
IMAP autentica y que la carpeta de Enviados se detecta, antes de ejecutar este plan. Si
la autenticación falla, es mejor saberlo con el sistema en modo lectura.

**La Tarea 5 es el interruptor.** Todo lo anterior es inerte: código que existe y nadie
llama. Se puede parar antes de la Tarea 5 y desplegar sin que pase nada.

**El primer arranque procesa 30 días de correo de una sola vez.** Es intencional, pero
esa primera tanda hay que revisarla con calma.

## Piezas que ya existen y se reusan

| Pieza | De dónde | Qué aporta |
|---|---|---|
| `clasificar_correo`, `_sin_cita`, `extraer_observaciones` | Fase B | interpretar el texto sin morder citas |
| `extraer_pa_del_cuerpo` | Plan 1 | el tercero, con código estable |
| `parsear_nombre_zip` | Plan 1 | CMU, proyecto, inversionista del adjunto |
| `mandatos_enviados_en_correo` | Plan 3a | qué salió en un correo |
| `carpeta_enviados`, `buscar_correos` | Plan 3a | leer INBOX y Enviados |
| `verificar_firmas` | Plan 3b | firmado de verdad, leyendo el PDF |
| `upsert_mandato`, `subir_pdf` | Finanzas | escribir y guardar en Drive |
| `TRANSICIONES_FIRMA` | Plan 1 | la red de seguridad |
| `MandatoCorreo` | Fase B | bitácora reversible |

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/finanzas_mandatos_service.py` | `upsert_mandato` atiende los estados nuevos |
| `app/services/mandatos/adjuntos.py` | **nuevo** — expandir ZIP a PDFs |
| `app/services/mandatos/finanzas_sync.py` | **nuevo** — decisión pura + aplicación |
| `app/main.py` | cron |
| `tests/test_mandatos_adjuntos.py` | **nuevo** |
| `tests/test_mandatos_finanzas_sync.py` | **nuevo** |
| `tests/test_finanzas_mandatos_service.py` | casos de los estados nuevos |

---

### Task 1: `upsert_mandato` deja de ignorar los estados nuevos

Hoy solo ramifica sobre `firmado` y `con_comentarios`. Si le llega `corregido` o
`enviado_inversionista` cae en el `else` de `sin_firma` y **no asigna el estado, en
silencio**.

**Files:**
- Modify: `app/services/finanzas_mandatos_service.py` (`upsert_mandato`)
- Modify: `tests/test_finanzas_mandatos_ingest.py`

Los tests van en `test_finanzas_mandatos_ingest.py`, no en `..._service.py`: ahí ya vive
la fixture `db_session` (SQLite en memoria con `FinanzasMandato.__table__`), y ahí están
los demás tests de `upsert_mandato`. No hay que montar arnés nuevo.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_finanzas_mandatos_ingest.py`:

```python
def test_upsert_asigna_corregido(db_session):
    kw = dict(proyecto="P", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU1")
    upsert_mandato(db_session, estado="con_comentarios", comentario="ajustar", **kw)
    m, _ = upsert_mandato(db_session, estado="corregido", **kw)
    assert m.estado == "corregido"
    assert m.comentario is None


def test_upsert_asigna_enviado_inversionista_y_su_fecha(db_session):
    kw = dict(proyecto="P2", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU2")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="enviado_inversionista",
                          fecha=date(2026, 8, 1), **kw)
    assert m.estado == "enviado_inversionista"
    assert m.fecha_envio_inversionista == date(2026, 8, 1)


def test_upsert_sigue_sin_degradar_un_firmado(db_session):
    """Comportamiento existente que NO debe cambiar."""
    kw = dict(proyecto="P3", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU3")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="sin_firma", **kw)
    assert m.estado == "firmado"
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_finanzas_mandatos_ingest.py -v`
Expected: los dos primeros FAIL (el estado se queda en `sin_firma`, y
`fecha_envio_inversionista` ni siquiera existe todavía); el tercero PASS.

- [ ] **Step 3: Agregar la columna que falta**

`enviado_inversionista` necesita su fecha. En `app/models/finanzas_mandatos.py`, junto a
`fecha_firma`:

```python
    fecha_envio_inversionista: Mapped[date | None] = mapped_column(Date, nullable=True)
```

Y en `_PENDING_DDLS` de `app/main.py`, junto al bloque de `finanzas_mandatos`:

```python
    "ALTER TABLE finanzas_mandatos ADD COLUMN IF NOT EXISTS fecha_envio_inversionista DATE",
```

- [ ] **Step 4: Ampliar la ramificación**

En `upsert_mandato`, reemplazar el bloque `if estado == "firmado": ... else: ...` por:

```python
    if estado == "firmado":
        m.estado = "firmado"
        m.fecha_firma = m.fecha_firma or hoy
        if drive_file_id:
            m.drive_file_id, m.drive_url = drive_file_id, drive_url
    elif estado == "con_comentarios":
        if m.estado != "firmado":
            m.estado = "con_comentarios"
        m.comentario = comentario
    elif estado == "corregido":
        # Se rehizo lo que la revisoría objetó; vuelve a estar en juego.
        m.estado = "corregido"
        m.comentario = None
    elif estado == "enviado_inversionista":
        m.estado = "enviado_inversionista"
        m.fecha_envio_inversionista = m.fecha_envio_inversionista or hoy
        if drive_file_id:
            m.drive_file_id, m.drive_url = drive_file_id, drive_url
    else:  # sin_firma
        m.fecha_envio = m.fecha_envio or hoy
```

**No agregar validación de transiciones acá.** Esta función es la que alcanza el script
de Jessica por `POST /ingest`, y meterle una regla nueva podría rechazar algo que ella
hace hoy y romperle el flujo antes de que lo retire. La red de seguridad va en el
adaptador (Tarea 4), que es donde vive la automatización. Los tres casos existentes
(`firmado`, `con_comentarios`, `sin_firma`) quedan **idénticos**.

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_finanzas_mandatos_service.py tests/test_finanzas_mandatos_ingest.py -v`
Expected: todos PASS, incluidos los de ingesta.

- [ ] **Step 6: Commit**

```bash
git add app/services/finanzas_mandatos_service.py app/models/finanzas_mandatos.py app/main.py tests/test_finanzas_mandatos_service.py
git commit -m "fix(mandatos): upsert_mandato asigna corregido y enviado_inversionista"
```

---

### Task 2: Expandir los ZIP de la revisoría

Vanessa manda los PDFs dentro de un ZIP. Hoy el cliente IMAP devuelve el ZIP como un
adjunto más y nadie lo abre.

**Files:**
- Create: `app/services/mandatos/adjuntos.py`
- Create: `tests/test_mandatos_adjuntos.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_mandatos_adjuntos.py`:

```python
"""Expansión de adjuntos: un ZIP de la revisoría rinde los PDFs de adentro."""
import io
import zipfile

from app.services.mandatos.adjuntos import expandir_adjuntos


def _zip(nombres: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, c in nombres.items():
            zf.writestr(n, c)
    return buf.getvalue()


def test_un_pdf_suelto_pasa_igual():
    adj = [("CMU1-Mandato-Costos-X.pdf", b"%PDF-1.4")]
    assert expandir_adjuntos(adj) == adj


def test_zip_rinde_sus_pdfs():
    z = _zip({"CMU1-Mandato-Costos-X.pdf": b"%PDF-a",
              "CMU2-Mandato-Costos-Y.pdf": b"%PDF-b"})
    r = dict(expandir_adjuntos([("mandatos.zip", z)]))
    assert sorted(r) == ["CMU1-Mandato-Costos-X.pdf", "CMU2-Mandato-Costos-Y.pdf"]
    assert r["CMU1-Mandato-Costos-X.pdf"] == b"%PDF-a"


def test_zip_descarta_lo_que_no_es_pdf():
    z = _zip({"CMU1-Mandato-Costos-X.pdf": b"%PDF-a", "notas.txt": b"hola"})
    assert [n for n, _ in expandir_adjuntos([("z.zip", z)])] == [
        "CMU1-Mandato-Costos-X.pdf"]


def test_zip_ignora_rutas_de_carpeta_internas():
    """Un ZIP con carpetas adentro debe rendir solo el nombre del archivo."""
    z = _zip({"julio/CMU1-Mandato-Costos-X.pdf": b"%PDF-a"})
    assert [n for n, _ in expandir_adjuntos([("z.zip", z)])] == [
        "CMU1-Mandato-Costos-X.pdf"]


def test_zip_corrupto_no_revienta():
    assert expandir_adjuntos([("roto.zip", b"esto no es un zip")]) == []


def test_mezcla_de_zip_y_pdf_suelto():
    z = _zip({"CMU1-Mandato-Costos-X.pdf": b"%PDF-a"})
    r = expandir_adjuntos([("z.zip", z), ("CMU2-Mandato-Costos-Y.pdf", b"%PDF-b")])
    assert sorted(n for n, _ in r) == [
        "CMU1-Mandato-Costos-X.pdf", "CMU2-Mandato-Costos-Y.pdf"]
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_adjuntos.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Crear `app/services/mandatos/adjuntos.py`:

```python
"""Expansión de adjuntos de correo: un ZIP rinde los PDFs que trae adentro.

La revisoría manda los mandatos firmados dentro de un ZIP, con la misma
convención de nombres que los sueltos. Para el resto del sistema no debería
haber diferencia entre "vino en un ZIP" y "vino suelto", así que se aplana acá.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import PurePosixPath

logger = logging.getLogger("mandatos.adjuntos")

# Un ZIP de mandatos ronda unos pocos MB. El tope evita que un adjunto absurdo
# se descomprima en memoria dentro del cron.
_MAX_DESCOMPRIMIDO = 50 * 1024 * 1024


def expandir_adjuntos(adjuntos: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """[(nombre, contenido)] con los ZIP reemplazados por los PDFs de adentro.

    Los nombres se aplanan: `julio/CMU1-....pdf` sale como `CMU1-....pdf`, porque
    el resto del sistema parsea el nombre del archivo y no le sirve la ruta.

    Un ZIP corrupto se descarta con un log y no interrumpe los demás adjuntos:
    perder un adjunto ilegible es preferible a perder toda la corrida.
    """
    salida: list[tuple[str, bytes]] = []
    for nombre, contenido in adjuntos:
        if not nombre.lower().endswith(".zip"):
            salida.append((nombre, contenido))
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
                total = sum(i.file_size for i in zf.infolist())
                if total > _MAX_DESCOMPRIMIDO:
                    logger.warning("Adjuntos: %r descomprime a %d bytes, se omite",
                                   nombre, total)
                    continue
                for info in zf.infolist():
                    if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                        continue
                    salida.append((PurePosixPath(info.filename).name, zf.read(info)))
        except Exception as exc:
            logger.warning("Adjuntos: no se pudo abrir %r: %s", nombre, exc)
    return salida
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_adjuntos.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/adjuntos.py tests/test_mandatos_adjuntos.py
git commit -m "feat(mandatos): expandir los ZIP de la revisoria a sus PDFs"
```

---

### Task 3: `decidir_finanzas()` — la decisión, pura

**Files:**
- Create: `app/services/mandatos/finanzas_sync.py`
- Create: `tests/test_mandatos_finanzas_sync.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_mandatos_finanzas_sync.py`:

```python
"""Decisión de qué escribir en finanzas_mandatos a partir de un correo. Pura."""
from datetime import date, datetime, timezone

from app.services.mandatos.finanzas_sync import FUENTE_ENVIO, FUENTE_REVISORIA, decidir_finanzas
from app.services.mandatos.imap_client import CorreoCrudo
from tests.fixtures_mandatos_correos import ENVIO_INVERSIONISTA, REVISORIA_SEGUIMIENTO

AHORA = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
PDF_FIRMADO = b"%PDF-firmado"
PDF_SIN = b"%PDF-sin"


def _correo(cuerpo, adjuntos=(), asunto="Certificados junio 2026", remitente="x@y.com"):
    return CorreoCrudo(message_id="<t@test>", fecha=AHORA, remitente=remitente,
                       asunto=asunto, cuerpo=cuerpo, adjuntos=list(adjuntos))


def _firmas_fake(resultado):
    return lambda _contenido: {"lineas": 2, "firmadas": 2 if resultado else 0,
                               "estado": "firmado_completo" if resultado else "sin_firmas"}


def test_pdf_firmado_de_la_revisoria_da_firmado():
    c = _correo("Adjunto los certificados firmados.",
                [("CMU1140-Mandato-Costos-Minigranja Solar Merengue.pdf", PDF_FIRMADO)])
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(True))
    assert len(d["acciones"]) == 1
    a = d["acciones"][0]
    assert a["estado"] == "firmado"
    assert a["cmu"] == "CMU1140"
    assert a["proyecto"] == "Minigranja Solar Merengue"
    assert a["tipo"] == "costo"


def test_pdf_sin_firmas_no_se_marca_firmado():
    """El PDF llegó, pero abrirlo dice que no está firmado. Manda el documento,
    no el hecho de que haya adjunto."""
    c = _correo("Adjunto.", [("CMU1140-Mandato-Costos-X.pdf", PDF_SIN)])
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(False))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_correo_de_seguimiento_no_se_interpreta():
    c = _correo(REVISORIA_SEGUIMIENTO)
    d = decidir_finanzas(c, FUENTE_REVISORIA, verificador=_firmas_fake(True))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_envio_a_inversionista_usa_el_pa_del_cuerpo_como_tercero():
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-Minigranja Solar La Paz Levende.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    a = d["acciones"][0]
    assert a["estado"] == "enviado_inversionista"
    assert a["tercero"] == "P.A SOL DE LA SIERRA"
    assert a["periodo"] == date(2026, 6, 1)


def test_sin_pa_en_el_cuerpo_no_se_inventa_identidad():
    """Sin tercero no hay identidad completa. Antes que adivinar, se marca para
    revisión: una identidad equivocada crea una fila fantasma que nadie limpia."""
    c = _correo("Adjunto los certificados de junio.",
                [("CMU1135-Mandato-Costos-X.pdf", PDF_FIRMADO)],
                remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert d["acciones"] == []
    assert d["requiere_revision"] is True


def test_sin_periodo_en_el_asunto_no_se_inventa():
    c = _correo(ENVIO_INVERSIONISTA,
                [("CMU1135-Mandato-Costos-X.pdf", PDF_FIRMADO)],
                asunto="RE: sin mes", remitente="jessica@unergy.io")
    d = decidir_finanzas(c, FUENTE_ENVIO, verificador=_firmas_fake(True))
    assert d["acciones"] == []
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Implementar**

Crear `app/services/mandatos/finanzas_sync.py`:

```python
"""Correo → qué escribir en finanzas_mandatos.

Compone piezas ya probadas: el parser de Fase B interpreta el texto, el detector
de firmas mira el PDF, el servicio de Finanzas escribe. Acá solo se decide.

`decidir_finanzas` es pura: recibe un correo y un verificador de firmas
inyectado, y devuelve qué habría que hacer. No consulta la base ni escribe
archivos, para poder probar las reglas sin montar un arnés.
"""
from __future__ import annotations

import logging
from datetime import date

from app.services.finanzas_mandatos_service import (
    extraer_periodo_de_asunto, tipo_de_nombre,
)
from app.services.mandatos.adjuntos import expandir_adjuntos
from app.services.mandatos.email_parser import (
    CLASIF_MOLDE_SIMPLE, clasificar_correo, extraer_observaciones,
    extraer_pa_del_cuerpo,
)
from app.services.mandatos.firmas import verificar_firmas
from app.services.mandatos.imap_client import CorreoCrudo
from app.services.mandatos_service import parsear_nombre_zip

logger = logging.getLogger("mandatos.finanzas_sync")

FUENTE_REVISORIA = "revisoria"
FUENTE_ENVIO = "envio_inversionista"


def _identidad(nombre_archivo: str, correo: CorreoCrudo) -> dict | None:
    """(cmu, proyecto, tercero, tipo, periodo) o None si falta algo.

    El tercero NO está en el nombre del archivo cuando el mandante es un P.A.:
    sale del cuerpo. Si falta el tercero o el período, se devuelve None en vez de
    completar con un valor por defecto -- la identidad es la llave única de la
    tabla, y una identidad inventada crea una fila fantasma que después nadie
    reconoce ni limpia.
    """
    parsed = parsear_nombre_zip(nombre_archivo)
    if not parsed:
        return None
    periodo = extraer_periodo_de_asunto(correo.asunto or "", correo.fecha.date())
    if not periodo:
        return None
    pa = extraer_pa_del_cuerpo(correo.cuerpo)
    tercero = parsed["inversionista"] or (pa["nombre"] if pa else "")
    if not tercero:
        return None
    return {
        "cmu": parsed["cmu"],
        "proyecto": parsed["proyecto"],
        "tercero": tercero,
        "tipo": tipo_de_nombre(nombre_archivo),
        "periodo": periodo,
        "pa_codigo": pa["codigo"] if pa else None,
    }


def decidir_finanzas(correo: CorreoCrudo, fuente: str, *, verificador=verificar_firmas) -> dict:
    """{'clasificacion', 'acciones', 'requiere_revision', 'sin_identidad'}.

    `verificador` se inyecta para poder probar sin PDFs reales.
    """
    adjuntos = expandir_adjuntos(list(correo.adjuntos))
    acciones: list[dict] = []
    sin_identidad: list[str] = []
    clasificacion = clasificar_correo(correo.asunto, correo.cuerpo)

    for nombre, contenido in adjuntos:
        if not nombre.lower().endswith(".pdf"):
            continue
        ident = _identidad(nombre, correo)
        if not ident:
            sin_identidad.append(nombre)
            continue
        firmas = verificador(contenido)
        if fuente == FUENTE_ENVIO:
            # Jessica manda al inversionista lo que ya está firmado.
            acciones.append({**ident, "estado": "enviado_inversionista",
                             "adjunto": nombre, "firmas": firmas})
        elif firmas["estado"] == "firmado_completo":
            acciones.append({**ident, "estado": "firmado",
                             "adjunto": nombre, "firmas": firmas})
        else:
            # Llegó el PDF pero no está firmado (o no se pudo verificar). No se
            # marca firmado por el mero hecho de que haya adjunto: manda el
            # documento, no el sobre.
            sin_identidad.append(f"{nombre} ({firmas['estado']})")

    # Observaciones de texto, solo si el correo encaja en el molde conocido.
    if fuente == FUENTE_REVISORIA and clasificacion == CLASIF_MOLDE_SIMPLE:
        con_pdf = {a["cmu"] for a in acciones}
        for obs in extraer_observaciones(correo.cuerpo):
            if obs["cmu"] in con_pdf:
                continue
            # Sin adjunto no hay nombre de archivo, así que no hay proyecto ni
            # tipo: la acción sale incompleta y el aplicador la resuelve por CMU
            # contra lo que ya exista en la tabla.
            acciones.append({"cmu": obs["cmu"], "estado": "con_comentarios",
                             "comentario": obs["observacion"], "adjunto": None,
                             "proyecto": None, "tercero": None, "tipo": None,
                             "periodo": None, "pa_codigo": None, "firmas": None})

    requiere = bool(sin_identidad) or (
        fuente == FUENTE_REVISORIA and clasificacion != CLASIF_MOLDE_SIMPLE)
    return {"clasificacion": clasificacion, "acciones": acciones,
            "requiere_revision": requiere, "sin_identidad": sin_identidad}
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_finanzas_sync.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py tests/test_mandatos_finanzas_sync.py
git commit -m "feat(mandatos): decidir que escribir en finanzas a partir de un correo"
```

---

### Task 4: Aplicar a la base, con bitácora y red de seguridad

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py`

- [ ] **Step 1: Implementar**

Agregar a `app/services/mandatos/finanzas_sync.py`:

```python
def _aplicar(db, accion: dict, correo: CorreoCrudo) -> dict:
    """Aplica una acción y devuelve su registro para la bitácora.

    La validación de transiciones vive acá y no en upsert_mandato: esa función
    la sigue usando el script de Jessica por /ingest, y meterle una regla nueva
    podría rechazar algo que ella hace hoy. La red de seguridad va donde está la
    automatización.
    """
    from app.models.finanzas_mandatos import FinanzasMandato
    from app.services import finanzas_mandatos_service as svc
    from app.services.finanzas_mandatos_service import transicion_firma_valida

    if not accion.get("periodo"):
        # Observación de texto sin adjunto: se resuelve por CMU.
        existente = (db.query(FinanzasMandato)
                     .filter(FinanzasMandato.cmu == accion["cmu"])
                     .order_by(FinanzasMandato.periodo.desc()).first())
        if not existente:
            return {"cmu": accion["cmu"], "resultado": "cmu_no_encontrado"}
        destino = accion["estado"]
        if not transicion_firma_valida(existente.estado, destino):
            return {"cmu": accion["cmu"], "resultado": "transicion_invalida",
                    "estado_previo": existente.estado, "estado_destino": destino}
        previo = existente.estado
        existente.estado = destino
        existente.comentario = accion.get("comentario")
        return {"cmu": accion["cmu"], "resultado": "aplicado", "id": existente.id,
                "estado_previo": previo, "estado_nuevo": destino}

    existente = (db.query(FinanzasMandato)
                 .filter(FinanzasMandato.proyecto == accion["proyecto"],
                         FinanzasMandato.tercero == accion["tercero"],
                         FinanzasMandato.periodo == accion["periodo"],
                         FinanzasMandato.tipo == accion["tipo"]).first())
    previo = existente.estado if existente else None
    destino = accion["estado"]
    if existente and not transicion_firma_valida(previo, destino):
        return {"cmu": accion["cmu"], "resultado": "transicion_invalida",
                "estado_previo": previo, "estado_destino": destino}

    drive_id = drive_url = None
    if accion.get("adjunto"):
        contenido = dict(expandir_adjuntos(list(correo.adjuntos))).get(accion["adjunto"])
        if contenido:
            from app.services.finanzas_mandatos_drive import subir_pdf
            sub = f"{accion['periodo'].strftime('%Y-%m')}-{accion['tipo']}"
            res = subir_pdf(contenido, accion["adjunto"], sub)
            drive_id, drive_url = res["id"], res["url"]

    m, creado = svc.upsert_mandato(
        db, proyecto=accion["proyecto"], tercero=accion["tercero"],
        periodo=accion["periodo"], tipo=accion["tipo"], cmu=accion["cmu"],
        estado=destino, comentario=accion.get("comentario"),
        fecha=correo.fecha.date(), correo_ref=correo.message_id,
        drive_file_id=drive_id, drive_url=drive_url)
    return {"cmu": accion["cmu"], "resultado": "aplicado", "id": m.id,
            "creado": creado, "estado_previo": previo, "estado_nuevo": destino}


def procesar_correo_finanzas(db, correo: CorreoCrudo, fuente: str):
    """Procesa un correo y devuelve su fila de bitácora, sin commit."""
    from app.models.mandatos import MandatoCorreo

    d = decidir_finanzas(correo, fuente)
    registros = [_aplicar(db, a, correo) for a in d["acciones"]]
    aplicado = any(r["resultado"] == "aplicado" for r in registros)
    problema = any(r["resultado"] != "aplicado" for r in registros)
    return MandatoCorreo(
        message_id=correo.message_id, fecha=correo.fecha,
        remitente=(correo.remitente or "")[:255],
        asunto=(correo.asunto or "")[:1000], fuente=fuente,
        clasificacion=d["clasificacion"],
        resultado="aplicado" if aplicado else "omitido",
        requiere_revision=d["requiere_revision"] or problema,
        detalle={"acciones": registros, "sin_identidad": d["sin_identidad"]})
```

- [ ] **Step 2: Verificar que importa y que la suite sigue verde**

Run: `python -c "from app.services.mandatos.finanzas_sync import procesar_correo_finanzas; print('ok')"`
Expected: `ok`

Run: `python -m pytest tests/ -q`
Expected: 1276+ passed, 0 failed.

- [ ] **Step 3: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py
git commit -m "feat(mandatos): aplicar a finanzas_mandatos con bitacora y validacion"
```

---

### Task 5: El interruptor — el cron

**Hasta acá nada corre.** Esta tarea es la que lo prende.

**Files:**
- Modify: `app/services/mandatos/finanzas_sync.py`
- Modify: `app/main.py`

- [ ] **Step 1: El ciclo completo**

Agregar a `app/services/mandatos/finanzas_sync.py`:

```python
REMITENTE_REVISORIA = "vlondono@jbp.com.co"
REMITENTE_ENVIO = "jessica@unergy.io"


def revisar_correos_finanzas() -> None:
    """Punto de entrada del cron. Nunca lanza hacia el scheduler.

    Tres pasadas: lo que llega de la revisoría (INBOX), lo que Jessica manda a
    inversionistas (INBOX, va en copia), y lo que sale hacia la revisoría
    (Enviados) -- esta última es la que permite saber cuántos se enviaron, sin
    lo cual la reconciliación no puede detectar los que nunca volvieron.

    Transacción POR CORREO: uno que reviente no arrastra a los demás.
    """
    import imaplib

    from sqlalchemy import select

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.mandatos import MandatoCorreo
    from app.services.mandatos.imap_client import buscar_correos, carpeta_enviados

    if not settings.MANDATOS_IMAP_USER or not settings.MANDATOS_IMAP_PASSWORD:
        logger.info("Finanzas mandatos: credenciales no configuradas, se omite")
        return

    pasadas = [(REMITENTE_REVISORIA, FUENTE_REVISORIA, "INBOX", "FROM"),
               (REMITENTE_ENVIO, FUENTE_ENVIO, "INBOX", "FROM")]

    # La carpeta de Enviados hay que preguntarla al servidor; su nombre depende
    # del idioma de la cuenta.
    try:
        imap = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        imap.login(settings.MANDATOS_IMAP_USER, settings.MANDATOS_IMAP_PASSWORD)
        enviados = carpeta_enviados(imap)
        imap.logout()
    except Exception as exc:
        logger.error("Finanzas mandatos: no se pudo consultar Enviados: %s", exc)
        enviados = None
    if enviados:
        pasadas.append((REMITENTE_REVISORIA, FUENTE_REVISORIA, enviados, "TO"))

    db = SessionLocal()
    try:
        vistos = {mid for (mid,) in db.execute(select(MandatoCorreo.message_id)).all()}
        for direccion, fuente, carpeta, campo in pasadas:
            for correo in buscar_correos(direccion, carpeta=carpeta, campo=campo):
                if correo.message_id in vistos:
                    continue
                try:
                    fila = procesar_correo_finanzas(db, correo, fuente)
                    db.add(fila)
                    db.commit()
                    vistos.add(correo.message_id)
                    logger.info("Finanzas mandatos: %s -- %s/%s",
                                correo.message_id, fila.clasificacion, fila.resultado)
                except Exception as exc:
                    db.rollback()
                    logger.error("Finanzas mandatos: fallo en %s: %s",
                                 correo.message_id, exc)
                    try:
                        db.add(MandatoCorreo(
                            message_id=correo.message_id, fecha=correo.fecha,
                            remitente=(correo.remitente or "")[:255],
                            asunto=(correo.asunto or "")[:1000], fuente=fuente,
                            clasificacion="desconocido", resultado="error",
                            requiere_revision=True, detalle={"error": str(exc)}))
                        db.commit()
                        vistos.add(correo.message_id)
                    except Exception:
                        db.rollback()
    finally:
        db.close()
```

- [ ] **Step 2: Reemplazar el cron de Fase B**

En `app/main.py`, `_scheduled_correos_mandatos` hoy llama a
`revisar_correos_mandatos` (Fase B, escribe en la tabla vieja). Cambiar el cuerpo para
que llame al nuevo:

```python
def _scheduled_correos_mandatos():
    """Lee el correo y actualiza finanzas_mandatos.

    Cada hora de 7am a 7pm: los correos de la revisoría y los envíos a
    inversionistas llegan en horario laboral. Sin correos nuevos la corrida es
    solo un IMAP SEARCH que no toca la base."""
    from app.services.mandatos.finanzas_sync import revisar_correos_finanzas

    revisar_correos_finanzas()
```

El registro del job y su guarda por credenciales ya existen y no cambian.

- [ ] **Step 3: Verificar**

Run: `python -c "import app.main; print('ok')"` → `ok`
Run: `python -m pytest tests/ -q` → 1276+ passed, 0 failed.

- [ ] **Step 4: Commit**

```bash
git add app/services/mandatos/finanzas_sync.py app/main.py
git commit -m "feat(mandatos): el cron alimenta finanzas_mandatos (interruptor)"
```

---

## Verificación después del deploy

**El primer arranque procesa 30 días de correo.** Revisar esa tanda antes de confiar.

1. Railway → Deploy Logs, buscar `Finanzas mandatos`. Cada correo procesado imprime una
   línea con su clasificación y resultado.
2. `GET /api/v1/finanzas/mandatos/correos?solo_revision=true` (bitácora de Fase B) para
   ver qué quedó marcado para revisión.
3. `GET /api/v1/finanzas/mandatos/reconciliacion?periodo=2026-07` — ahora sí debería dar
   números reales, porque `fecha_envio` se llena desde la carpeta de Enviados.
4. Comparar contra lo que diga el script de Jessica **antes de retirarlo**. Si los dos
   coinciden un ciclo completo, el script se puede apagar.
5. Si algo quedó mal, `POST /api/v1/mandatos/correos/{id}/revertir`.

## Lo que queda después

- **Plan 4** — frontend: Finanzas > Mandatos con subpestañas, y sale Costos > Mandatos.
- **Plan 5** — borrar la tabla `mandatos` y su API. Irreversible: esperar a que esto
  lleve un par de semanas corriendo.
- Confirmar la plantilla de un mandato **sin firmar** y de uno de **ingresos**.
