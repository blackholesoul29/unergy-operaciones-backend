# Integración Mandatos — Plan 3a: reconciliación por conteo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la plataforma pueda responder "de los 32 mandatos que se enviaron en julio, faltan 2 por volver, y son estos" — hoy no puede, porque solo se entera de un mandato cuando regresa firmado.

**Architecture:** Tres piezas nuevas, todas de solo lectura. El cliente IMAP aprende a leer la carpeta de Enviados (detectada por la bandera `\Sent`, no por nombre). Una función pura saca de un correo saliente qué mandatos salieron. Otra función pura compara enviados contra devueltos. Un endpoint de solo lectura lo expone.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, `imaplib` (stdlib), pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-mandatos-integracion-design.md` §4

**Rama:** `feat/mandatos-fase-b-imap`

---

## Por qué hace falta leer Enviados

Los correos **hacia** la revisoría no están en la bandeja de entrada de `adhara@`: los
manda ella. Se comprueba en el correo real del 10 ago, donde Vanessa responde
*"Revisando la información que me compartes"* — o sea que Adhara se lo envió antes.

Sin leer Enviados, la plataforma solo conoce un mandato **cuando vuelve**, y entonces no
puede detectar los que nunca volvieron. Que es exactamente lo que la reconciliación
tiene que encontrar, y lo que hoy solo hace el script de Jessica.

## Alcance y seguridad

**Solo lectura, y nada se prende.** Este plan no escribe en ninguna tabla, no toca el
script de Jessica, no modifica `upsert_mandato`, no registra ningún cron. Construye
capacidad que el Plan 2 va a usar. El endpoint nuevo es un `GET`.

Se mantiene la garantía de Fase B: **la bandeja de `adhara@` nunca se modifica.** Todo
`select` va con `readonly=True` y no se usa `UNSEEN` ni se marca nada.

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/mandatos/imap_client.py` | `carpeta_enviados()` + `buscar_correos()` acepta carpeta y dirección |
| `app/services/mandatos/email_parser.py` | `mandatos_enviados_en_correo()` |
| `app/services/mandatos/reconciliacion.py` | **nuevo** — `reconciliar()`, puro |
| `app/api/v1/finanzas_mandatos.py` | `GET /finanzas/mandatos/reconciliacion` |
| `tests/test_mandatos_reconciliacion.py` | **nuevo** |
| `tests/test_mandatos_email_parser.py` | tests de `mandatos_enviados_en_correo` |

---

### Task 1: Encontrar la carpeta de Enviados sin depender del idioma

**Files:**
- Modify: `app/services/mandatos/imap_client.py`

- [ ] **Step 1: Implementar**

Agregar a `app/services/mandatos/imap_client.py`, antes de `buscar_correos`:

```python
# Nombres de respaldo, por si el servidor no publica la bandera \Sent. El orden
# importa: primero los de Gmail, que es lo que usamos.
_ENVIADOS_CONOCIDOS = (
    "[Gmail]/Enviados",
    "[Gmail]/Sent Mail",
    "[Google Mail]/Enviados",
    "Enviados",
    "Sent",
)


def carpeta_enviados(imap: imaplib.IMAP4_SSL) -> str | None:
    """Nombre de la carpeta de Enviados, o None si no se puede determinar.

    Se busca por la bandera `\\Sent` del RFC 6154, no por nombre: el nombre
    depende del idioma de la cuenta ("Enviados" vs "Sent Mail") y cambiaría si
    alguien toca la configuración de Gmail. La bandera no.

    Si el servidor no publica la bandera, se cae a una lista de nombres
    conocidos. Si tampoco, se devuelve None y el llamador decide -- preferimos
    no leer nada a leer la carpeta equivocada.
    """
    try:
        status, lineas = imap.list()
    except Exception as exc:
        logger.error("IMAP mandatos: no se pudo listar carpetas: %s", exc)
        return None
    if status != "OK" or not lineas:
        return None

    disponibles: list[str] = []
    for linea in lineas:
        texto = linea.decode("utf-8", errors="replace") if isinstance(linea, bytes) else str(linea)
        # Formato: (\HasNoChildren \Sent) "/" "[Gmail]/Enviados"
        nombre = texto.split(' "/" ')[-1].strip().strip('"')
        disponibles.append(nombre)
        if "\\Sent" in texto:
            return nombre

    for candidato in _ENVIADOS_CONOCIDOS:
        if candidato in disponibles:
            logger.info("IMAP mandatos: sin bandera \\Sent, usando %r", candidato)
            return candidato

    logger.error("IMAP mandatos: no se encontró la carpeta de Enviados. Disponibles: %s",
                 disponibles)
    return None
```

- [ ] **Step 2: Verificar que importa y que sin credenciales no revienta**

Run: `python -c "from app.services.mandatos.imap_client import carpeta_enviados; print('ok')"`
Expected: `ok`

No se puede probar contra un servidor real desde local (las credenciales viven en
Railway y no se conecta a producción desde acá). La verificación real es el log
`IMAP mandatos: no se encontró la carpeta de Enviados. Disponibles: [...]` tras el
primer deploy — si aparece, la lista de nombres disponibles dice exactamente qué poner.

- [ ] **Step 3: Commit**

```bash
git add app/services/mandatos/imap_client.py
git commit -m "feat(mandatos): detectar la carpeta de Enviados por la bandera \\Sent"
```

---

### Task 2: `buscar_correos` acepta carpeta y dirección

Hoy siempre lee `INBOX` y filtra por `FROM`. Para los salientes hace falta leer
Enviados y filtrar por `TO`.

**Files:**
- Modify: `app/services/mandatos/imap_client.py`

- [ ] **Step 1: Cambiar la firma**

Reemplazar la definición de `buscar_correos`:

```python
def buscar_correos(direccion: str, dias: int = 30, *,
                   carpeta: str = "INBOX", campo: str = "FROM") -> list[CorreoCrudo]:
    """Correos de/para `direccion` en los últimos `dias`, dentro de `carpeta`.

    `campo` es "FROM" para lo que llega y "TO" para lo que sale. Los salientes
    viven en la carpeta de Enviados, no en INBOX -- ver carpeta_enviados().

    Devuelve [] ante cualquier fallo de conexión, autenticación o búsqueda --
    nunca lanza hacia el llamador, para no tumbar el scheduler.
    """
```

Dentro, cambiar el `select` y el criterio:

```python
        imap.select(carpeta, readonly=True)
        desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE "{desde}" {campo} "{direccion}")')
```

Y en el `CorreoCrudo` que se construye, el campo `remitente` deja de poder asumirse.
Reemplazar `remitente=direccion` por la cabecera real:

```python
                remitente=_decodifica(msg.get("From")) or direccion,
```

**Ojo:** ese último cambio afecta a los llamadores existentes en `email_sync.py`, que
hoy reciben `remitente` igual al parámetro que pasaron. Ahora recibirán la cabecera
`From` real, que trae la forma `Nombre <correo@dominio>` en vez de solo el correo.
`email_sync` guarda ese valor en `MandatoCorreo.remitente`, que es informativo y de
500 caracteres, así que no rompe nada — pero **verificar que
`tests/test_mandatos_email_sync.py` sigue verde** y, si alguna aserción compara el
remitente exacto, reportarlo en vez de ajustarla.

- [ ] **Step 2: Verificar que los llamadores existentes siguen funcionando**

Run: `python -m pytest tests/test_mandatos_email_sync.py tests/test_mandatos_email_parser.py -q`
Expected: todos PASS.

Run: `python -c "from app.services.mandatos.imap_client import buscar_correos; print(buscar_correos('x@y.com'))"`
Expected: `[]` (sin credenciales locales)

- [ ] **Step 3: Commit**

```bash
git add app/services/mandatos/imap_client.py
git commit -m "feat(mandatos): buscar_correos acepta carpeta y direccion de busqueda"
```

---

### Task 3: `mandatos_enviados_en_correo` — qué salió en un correo

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_mandatos_email_parser.py` (importar `mandatos_enviados_en_correo`
arriba, con los demás):

```python
# ── mandatos_enviados_en_correo ───────────────────────────────────────────────

def test_enviados_saca_un_cmu_por_adjunto():
    enviados = mandatos_enviados_en_correo(ADJUNTOS_REALES_DRIVE)
    assert [e["cmu"] for e in enviados] == [
        "CMU1135", "CMU1140", "CMU1147", "CMU1148"]
    assert all(e["tipo"] == "costo" for e in enviados)


def test_enviados_trae_el_proyecto_de_cada_adjunto():
    enviados = {e["cmu"]: e["proyecto"] for e in mandatos_enviados_en_correo(ADJUNTOS_REALES_DRIVE)}
    assert enviados["CMU1140"] == "Minigranja Solar Merengue"


def test_enviados_ignora_lo_que_no_es_pdf_de_mandato():
    assert mandatos_enviados_en_correo(["REGISTRO MANDATOS.xlsx", "foto.png"]) == []


def test_enviados_ignora_un_pdf_que_no_es_mandato():
    """Un PDF suelto sin la convención de nombre no es un mandato enviado.
    Sin esta guarda, cualquier adjunto inflaría el conteo de la reconciliación."""
    assert mandatos_enviados_en_correo(["cotizacion.pdf"]) == []


def test_enviados_sin_adjuntos():
    assert mandatos_enviados_en_correo([]) == []
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_email_parser.py -k enviados -v`
Expected: FAIL con `ImportError: cannot import name 'mandatos_enviados_en_correo'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/email_parser.py`:

```python
def mandatos_enviados_en_correo(nombres_adjuntos: list[str]) -> list[dict]:
    """Los mandatos que salieron en un correo, uno por adjunto reconocible.

    [{'cmu': 'CMU1140', 'proyecto': 'Minigranja Solar Merengue',
      'inversionista': '', 'tipo': 'costo'}, ...]

    Solo cuenta adjuntos que cumplen la convención de nombre. Un PDF suelto que
    no la cumple NO entra: esta lista alimenta el conteo de la reconciliación, y
    un adjunto de más ahí inventa un mandato que nadie envió y que después
    aparece eternamente como "falta por volver".
    """
    from app.services.mandatos_service import parsear_nombre_zip

    salida: list[dict] = []
    for nombre in solo_pdfs(nombres_adjuntos):
        parsed = parsear_nombre_zip(nombre)
        if not parsed:
            continue
        salida.append({
            "cmu": parsed["cmu"],
            "proyecto": parsed["proyecto"],
            "inversionista": parsed["inversionista"],
            # La convención solo distingue Costos; los de ingresos usan otra
            # palabra en el nombre y hoy no hay muestra real. Se marca 'costo'
            # porque es lo único verificado -- cuando aparezca un adjunto de
            # ingresos, agregarlo como fixture y ajustar acá.
            "tipo": "costo",
        })
    return salida
```

`parsear_nombre_zip` se importa dentro de la función a propósito: `email_parser` ya
importa `CMU_RE` desde `mandatos_service` al tope, y agregar más acoplamiento al tope
haría más difícil separarlos después. El import local mantiene la dependencia visible
justo donde se usa.

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): identificar que mandatos salieron en un correo"
```

---

### Task 4: `reconciliar()` y su endpoint

**Files:**
- Create: `app/services/mandatos/reconciliacion.py`
- Create: `tests/test_mandatos_reconciliacion.py`
- Modify: `app/api/v1/finanzas_mandatos.py`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_mandatos_reconciliacion.py`:

```python
"""Reconciliación por conteo -- lógica pura, sin BD.

Responde "de los N que se enviaron, cuáles no han vuelto". Es la capacidad que
hoy solo tiene el script local de Jessica, y la condición para retirarlo.
"""
from datetime import date
from types import SimpleNamespace as NS

from app.services.mandatos.reconciliacion import reconciliar

PERIODO = date(2026, 7, 1)


def _m(cmu, estado, enviado=True, firmado=False):
    return NS(cmu=cmu, estado=estado, periodo=PERIODO, tipo="costo",
              proyecto=f"Proyecto {cmu}", tercero="P.A X",
              fecha_envio=PERIODO if enviado else None,
              fecha_firma=PERIODO if firmado else None)


def test_todo_devuelto():
    filas = [_m("CMU1", "firmado", firmado=True), _m("CMU2", "firmado", firmado=True)]
    r = reconciliar(filas)
    assert r["enviados"] == 2
    assert r["devueltos"] == 2
    assert r["pendientes"] == []
    assert r["completo"] is True


def test_faltan_dos_y_dice_cuales():
    filas = [_m("CMU1", "firmado", firmado=True),
             _m("CMU2", "sin_firma"),
             _m("CMU3", "sin_firma")]
    r = reconciliar(filas)
    assert r["enviados"] == 3
    assert r["devueltos"] == 1
    assert sorted(r["pendientes"]) == ["CMU2", "CMU3"]
    assert r["completo"] is False


def test_con_comentarios_cuenta_como_devuelto_pero_se_lista_aparte():
    """Volvió, pero con observaciones: no está pendiente de retorno, sí de trabajo."""
    filas = [_m("CMU1", "con_comentarios")]
    r = reconciliar(filas)
    assert r["devueltos"] == 1
    assert r["pendientes"] == []
    assert r["con_comentarios"] == ["CMU1"]
    assert r["completo"] is True


def test_enviado_inversionista_tambien_es_devuelto():
    filas = [_m("CMU1", "enviado_inversionista", firmado=True)]
    r = reconciliar(filas)
    assert r["devueltos"] == 1
    assert r["completo"] is True


def test_una_fila_sin_fecha_envio_no_cuenta_como_enviada():
    """Si apareció sin haberse enviado, es una anomalía -- se reporta aparte
    en vez de inflar el denominador."""
    filas = [_m("CMU1", "firmado", enviado=False, firmado=True)]
    r = reconciliar(filas)
    assert r["enviados"] == 0
    assert r["sin_registro_de_envio"] == ["CMU1"]


def test_periodo_vacio():
    r = reconciliar([])
    assert r == {"enviados": 0, "devueltos": 0, "pendientes": [],
                 "con_comentarios": [], "sin_registro_de_envio": [],
                 "completo": True}
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_reconciliacion.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.mandatos.reconciliacion'`

- [ ] **Step 3: Implementar**

Crear `app/services/mandatos/reconciliacion.py`:

```python
"""Reconciliación por conteo: qué se envió contra qué volvió.

Puro -- recibe filas ya cargadas y devuelve el balance. Sin BD, sin red.

Responde la pregunta que hoy solo contesta el script local de Jessica: "envié 32
mandatos de julio, ¿volvieron los 32?". Poder responderla en la plataforma es la
condición que ella puso para dejar de correr su script.
"""
from __future__ import annotations

# Estados que significan "la revisoría ya se pronunció sobre este mandato".
# con_comentarios cuenta como devuelto: volvió, aunque con trabajo pendiente.
_DEVUELTOS = {"firmado", "con_comentarios", "corregido", "enviado_inversionista"}


def reconciliar(filas) -> dict:
    """Balance de un período. `filas` son registros con cmu, estado y fecha_envio.

    - enviados: los que constan como enviados a la revisoría
    - devueltos: los que ya volvieron, en cualquier forma
    - pendientes: enviados que no han vuelto -- la lista que importa
    - con_comentarios: volvieron pero hay que corregirlos
    - sin_registro_de_envio: aparecieron sin constar como enviados. Anomalía:
      o se envió por fuera del canal, o el correo de salida no se leyó. Se
      reporta aparte para no inflar el denominador y esconder el problema.
    """
    enviados, devueltos = [], []
    con_comentarios, sin_envio = [], []

    for f in filas:
        if not getattr(f, "fecha_envio", None):
            sin_envio.append(f.cmu)
            continue
        enviados.append(f.cmu)
        if f.estado in _DEVUELTOS:
            devueltos.append(f.cmu)
        if f.estado == "con_comentarios":
            con_comentarios.append(f.cmu)

    pendientes = [c for c in enviados if c not in set(devueltos)]
    return {
        "enviados": len(enviados),
        "devueltos": len(devueltos),
        "pendientes": pendientes,
        "con_comentarios": con_comentarios,
        "sin_registro_de_envio": sin_envio,
        "completo": not pendientes,
    }
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_reconciliacion.py -v`
Expected: 6 passed.

- [ ] **Step 5: Agregar el endpoint**

En `app/api/v1/finanzas_mandatos.py`, junto a los demás `GET` y **antes** de cualquier
ruta con `/{...}` (si la hubiera):

```python
@router.get("/reconciliacion")
def reconciliacion(periodo: str = Query(...), tipo: str = Query(None),
                   db: Session = Depends(get_db), _=Depends(get_current_user)):
    """De los mandatos enviados en el período, cuáles no han vuelto."""
    from app.services.mandatos.reconciliacion import reconciliar

    try:
        per = datetime.strptime(periodo.strip()[:7], "%Y-%m").date()
    except ValueError:
        raise HTTPException(422, "periodo debe ser YYYY-MM")

    q = db.query(FinanzasMandato).filter(FinanzasMandato.periodo == per)
    if tipo:
        q = q.filter(FinanzasMandato.tipo == tipo)
    return {"periodo": periodo, "tipo": tipo, **reconciliar(q.all())}
```

- [ ] **Step 6: Verificar la ruta y la suite**

Run:
```bash
python -c "import app.main; [print(r.methods, r.path) for r in app.main.app.routes if 'finanzas/mandatos' in getattr(r,'path','')]"
```
Expected: aparece `GET /api/v1/finanzas/mandatos/reconciliacion`, y **antes** de
cualquier ruta con parámetro de path en ese mismo prefijo.

Run: `python -m pytest tests/ -q`
Expected: 1245+ passed, 0 failed. `tests/test_finanzas_mandatos_ingest.py` debe seguir
verde — nada de este plan cambia la ingesta actual.

- [ ] **Step 7: Commit**

```bash
git add app/services/mandatos/reconciliacion.py tests/test_mandatos_reconciliacion.py app/api/v1/finanzas_mandatos.py
git commit -m "feat(mandatos): reconciliacion por conteo + endpoint de solo lectura"
```

---

## Verificación después del deploy

1. `GET /api/v1/finanzas/mandatos/reconciliacion?periodo=2026-07` debe responder. Con
   los datos actuales dirá `enviados: 0` y todo en `sin_registro_de_envio`, porque
   `fecha_envio` solo se llena cuando la ingesta lea la carpeta de Enviados — eso es el
   Plan 2. **Que salga en cero al principio es lo esperado, no una falla.**
2. En los logs de Railway, si aparece
   `IMAP mandatos: no se encontró la carpeta de Enviados. Disponibles: [...]`, la lista
   dice exactamente qué nombre agregar a `_ENVIADOS_CONOCIDOS`.
3. Nada más debe cambiar. El script de Jessica sigue igual.

## Lo que queda pendiente

- **Plan 3b — verificación de las dos firmas.** Bloqueado: hace falta un PDF de mandato
  firmado, o que Jessica cuente cómo lo detecta su script. Sin eso no se sabe si las
  firmas son digitales (`/Sig` en el `AcroForm`), imágenes escaneadas, o texto.
- **Adjuntos de ingresos.** `mandatos_enviados_en_correo` marca todo como `costo`
  porque es lo único verificado. Falta un adjunto real de ingresos.
- **Plan 2** conecta esto: cuando la ingesta lea Enviados, llenará `fecha_envio` y la
  reconciliación empezará a dar números reales.
