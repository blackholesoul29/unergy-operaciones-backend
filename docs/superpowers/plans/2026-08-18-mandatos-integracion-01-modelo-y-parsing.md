# Integración Mandatos — Plan 1: modelo y parsing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar el modelo y el parsing listos para que el cron de Fase B pueda alimentar la tabla de Finanzas, sin cambiar todavía el comportamiento de nadie.

**Architecture:** Cuatro cambios independientes entre sí: el regex de nombres de ZIP acepta las dos convenciones reales; una función pura nueva extrae el P.A. del cuerpo del correo; el DDL de `finanzas_mandatos` se normaliza a `_PENDING_DDLS`; y el enum de estados crece con `corregido` y `enviado_inversionista` más un grafo de transiciones.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, PostgreSQL, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-18-mandatos-integracion-design.md`

**Rama:** `feat/mandatos-fase-b-imap` (contiene Fase B + master mergeado)

---

## Alcance y seguridad

Este plan **no cambia el comportamiento de nada en producción**. No toca el script de
Jessica, no prende ningún cron, no mueve datos. Añade capacidad y corrige una
limitación. Es el paso previo al Plan 2, que es donde se prende la ingesta automática.

**Zona sensible:** `_PENDING_DDLS` en `app/main.py` corre contra la base de producción
en cada arranque. Las tareas 3 y 4 la tocan. Todo lo que se agregue debe ser idempotente.

## Estructura de archivos

| Archivo | Cambio |
|---|---|
| `app/services/mandatos_service.py` | `ZIP_NOMBRE_RE` acepta ambas convenciones |
| `app/services/mandatos/email_parser.py` | nueva `extraer_pa_del_cuerpo()` |
| `app/models/finanzas_mandatos.py` | dos valores nuevos en `EstadoFirmaEnum` |
| `app/services/finanzas_mandatos_service.py` | nuevo grafo `TRANSICIONES_FIRMA` + `transicion_firma_valida()` |
| `app/main.py` | DDL de `finanzas_mandatos` + `ALTER TYPE` de los estados nuevos |
| `tests/test_mandatos.py` | casos de la convención de tres partes |
| `tests/test_mandatos_email_parser.py` | tests de `extraer_pa_del_cuerpo` |
| `tests/test_mandatos_integracion_contrato.py` | invertir el test que fija la limitación |
| `tests/test_finanzas_mandatos_service.py` | tests del grafo de transiciones |

---

### Task 1: `ZIP_NOMBRE_RE` acepta las dos convenciones reales

Hoy exige `-{Inversionista}` antes del `.pdf`. Cuando el mandante es un P.A. de
fiduciaria el archivo no lo trae, y `upload-zip` lo salta en silencio.

**Files:**
- Modify: `app/services/mandatos_service.py:9` y `parsear_nombre_zip` (~96)
- Modify: `tests/test_mandatos.py` (sección `parsear_nombre_zip`, ~110)
- Modify: `tests/test_mandatos_integracion_contrato.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `tests/test_mandatos.py`, junto a los tests de `parsear_nombre_zip`:

```python
def test_parsear_nombre_zip_sin_inversionista_pa_fiduciaria():
    """Convención de TRES partes: cuando el mandante es un P.A. de fiduciaria,
    el archivo no trae inversionista (carpeta 'Mandato Costos Sol de la Sierra',
    captura 2026-08-18). El inversionista queda vacío, no se inventa."""
    r = parsear_nombre_zip("CMU1140-Mandato-Costos-Minigranja Solar Merengue.pdf")
    assert r == {"cmu": "CMU1140", "proyecto": "Minigranja Solar Merengue",
                 "inversionista": ""}


def test_parsear_nombre_zip_sin_inversionista_proyecto_con_guion():
    """El caso que obliga al lookaround: sin la señal del espaciado, esto se
    partiría en ('PSF', 'Yurbaqua') e inventaría un inversionista."""
    r = parsear_nombre_zip("CMU0002-Mandato-Costos-PSF - Yurbaqua.pdf")
    assert r == {"cmu": "CMU0002", "proyecto": "PSF - Yurbaqua",
                 "inversionista": ""}


def test_parsear_nombre_zip_proyecto_con_numero_al_final():
    """'Valencia Oriente 1' no debe confundirse con un inversionista."""
    r = parsear_nombre_zip("CMU0003-Mandato-Costos-Minigranja Solar Valencia Oriente 1.pdf")
    assert r == {"cmu": "CMU0003", "proyecto": "Minigranja Solar Valencia Oriente 1",
                 "inversionista": ""}
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos.py -k parsear_nombre_zip -v`
Expected: los tres nuevos FAIL (`parsear_nombre_zip` devuelve `None` para los de
tres partes); los cuatro existentes PASS.

- [ ] **Step 3: Implementar**

En `app/services/mandatos_service.py`, reemplazar la línea 9:

```python
# Dos convenciones reales conviven (verificado 2026-08-18):
#   CMU0988-Mandato-Costos-{Proyecto}-{Inversionista}.pdf   inversionista con nombre
#   CMU1140-Mandato-Costos-{Proyecto}.pdf                   mandante es un P.A.
#
# Hacer opcional el grupo del inversionista no basta: "PSF - Yurbaqua.pdf" es un
# proyecto con guion adentro y se partiría en ('PSF', 'Yurbaqua'). La señal que
# los distingue en los nombres reales es el ESPACIADO -- el guion separador del
# inversionista va pegado ("...Uruaco-SUNO..."), y los guiones internos del
# nombre del proyecto van con espacios ("PSF - Yurbaqua"). De ahí el lookaround.
#
# La distinción es heurística, no garantizada: un proyecto con guion pegado o un
# inversionista con guion espaciado la romperían. Se acepta porque la fuente
# autoritativa del tercero pasa a ser el cuerpo del correo (extraer_pa_del_cuerpo),
# no el nombre del archivo.
ZIP_NOMBRE_RE = re.compile(
    r"^(CMU\d+)-Mandato-Costos-(.+?)(?:(?<! )-(?! )([^-]+))?\.pdf$", re.IGNORECASE)
```

Verificado contra los seis casos conocidos (los cuatro de `tests/test_mandatos.py`
más los dos de tres partes): 0 fallos.

Y en `parsear_nombre_zip` (~96), asegurar que un grupo ausente rinda `""` y no `None`:

```python
def parsear_nombre_zip(nombre: str) -> dict | None:
    """'CMU0988-Mandato-Costos-{Proyecto}[-{Inversionista}].pdf' → dict | None.

    El inversionista es opcional: los mandatos de un P.A. de fiduciaria no lo
    traen en el nombre (ahí el mandante sale del cuerpo del correo). Cuando
    falta, se devuelve cadena vacía -- nunca se inventa.
    """
    m = ZIP_NOMBRE_RE.match((nombre or "").strip())
    if not m:
        return None
    return {"cmu": m.group(1).upper(),
            "proyecto": (m.group(2) or "").strip(),
            "inversionista": (m.group(3) or "").strip()}
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos.py -k parsear_nombre_zip -v`
Expected: 7 passed.

**Si alguno de los cuatro tests preexistentes falla, PARAR y reportar.** Esos
codifican nombres reales de Fase A (SUNO, Solenium, Enexa) y el regex nuevo debe
seguir dándoles el mismo resultado. Si `PSF - Yurbaqua-Enexa S.A.S.pdf` deja de
separar bien, el `.+?` perezoso está cortando demasiado pronto — reportar el
resultado real en vez de ajustar la aserción.

- [ ] **Step 5: Invertir el test de la limitación**

En `tests/test_mandatos_integracion_contrato.py`, reemplazar
`test_zip_de_fase_a_no_parsea_los_nombres_de_tres_partes` por:

```python
@pytest.mark.parametrize("nombre", ADJUNTOS_REALES_DRIVE)
def test_zip_ya_parsea_las_dos_convenciones(nombre):
    """Antes solo aceptaba la forma con inversionista. Ahora acepta ambas y
    deja el inversionista vacío cuando el mandante es un P.A."""
    r = parsear_nombre_zip(nombre)
    assert r is not None
    assert r["inversionista"] == ""
    assert r["proyecto"].startswith("Minigranja Solar")
```

- [ ] **Step 6: Correr toda la suite**

Run: `python -m pytest tests/ -q`
Expected: 1224+ passed, 0 failed.

- [ ] **Step 7: Commit**

```bash
git add app/services/mandatos_service.py tests/test_mandatos.py tests/test_mandatos_integracion_contrato.py
git commit -m "fix(mandatos): aceptar nombres de ZIP sin inversionista (P.A. de fiduciaria)"
```

---

### Task 2: `extraer_pa_del_cuerpo` — el tercero sale del correo

La identidad de Finanzas necesita `tercero`, y el nombre del adjunto no lo trae
cuando el mandante es un P.A. Sí está en el cuerpo, con un **código numérico
estable** que sirve mejor que cualquier cruce difuso de nombres.

**Files:**
- Modify: `app/services/mandatos/email_parser.py`
- Modify: `tests/test_mandatos_email_parser.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `tests/test_mandatos_email_parser.py` (importar `extraer_pa_del_cuerpo`
en el bloque de imports de arriba, junto a los demás):

```python
# ── extraer_pa_del_cuerpo ─────────────────────────────────────────────────────

def test_extraer_pa_del_correo_real_de_jessica():
    assert extraer_pa_del_cuerpo(ENVIO_INVERSIONISTA) == {
        "codigo": "17844", "nombre": "P.A SOL DE LA SIERRA"}


def test_extraer_pa_tolera_puntuacion_y_tildes():
    cuerpo = "asociados al 18254 - P.A.  AUTOCONSUMO NESTLÉ del mes de julio ya"
    assert extraer_pa_del_cuerpo(cuerpo) == {
        "codigo": "18254", "nombre": "P.A. AUTOCONSUMO NESTLÉ"}


def test_extraer_pa_no_confunde_el_saludo_sin_codigo():
    """El saludo nombra la fiduciaria sin código -- no es la identidad."""
    cuerpo = "Cordial saludo equipo de PATRIMONIOS AUTONOMOS FIDUCIARIA BANCOLOMBIA S A"
    assert extraer_pa_del_cuerpo(cuerpo) is None


def test_extraer_pa_en_liquidacion_preliminar_es_none():
    assert extraer_pa_del_cuerpo(LIQUIDACION_PRELIMINAR) is None


def test_extraer_pa_vacio():
    assert extraer_pa_del_cuerpo("") is None
    assert extraer_pa_del_cuerpo(None) is None
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_mandatos_email_parser.py -k extraer_pa -v`
Expected: FAIL con `ImportError: cannot import name 'extraer_pa_del_cuerpo'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/mandatos/email_parser.py`:

```python
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
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_mandatos_email_parser.py -v`
Expected: todos PASS, incluidos los 5 nuevos.

- [ ] **Step 5: Commit**

```bash
git add app/services/mandatos/email_parser.py tests/test_mandatos_email_parser.py
git commit -m "feat(mandatos): extraer el P.A. (codigo + nombre) del cuerpo del correo"
```

---

### Task 3: Normalizar el DDL de `finanzas_mandatos`

Hoy la tabla se crea por `Base.metadata.create_all()` y no aparece en
`_PENDING_DDLS`, así que es invisible para quien audite el esquema ahí. La Tarea 4
va a agregar un `ALTER TYPE` sobre su enum, y conviene que la tabla esté declarada
en el mismo lugar.

**Files:**
- Modify: `app/main.py` → `_PENDING_DDLS`

- [ ] **Step 1: Agregar el DDL**

En `_PENDING_DDLS`, después del bloque de `mandato_correos`:

```python
    # La tabla ya existe en producción, creada por Base.metadata.create_all().
    # Se declara acá por consistencia con el resto del esquema y para que un
    # ALTER TYPE sobre su enum (ver más abajo) tenga su tabla al lado. El
    # IF NOT EXISTS la vuelve un no-op donde ya está.
    """CREATE TABLE IF NOT EXISTS finanzas_mandatos (
        id BIGSERIAL PRIMARY KEY,
        proyecto VARCHAR(255) NOT NULL,
        tercero VARCHAR(255) NOT NULL DEFAULT '',
        periodo DATE NOT NULL,
        tipo tipo_mandato_fin_enum NOT NULL,
        cmu VARCHAR(20),
        cmu_anterior VARCHAR(20),
        estado estado_firma_fin_enum NOT NULL DEFAULT 'sin_firma',
        comentario TEXT,
        fecha_envio DATE,
        fecha_firma DATE,
        drive_file_id VARCHAR(255),
        drive_url VARCHAR(1000),
        correo_ref VARCHAR(500),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finmandato_identidad ON finanzas_mandatos (proyecto, tercero, periodo, tipo)",
    "CREATE INDEX IF NOT EXISTS ix_finmandatos_periodo ON finanzas_mandatos (periodo)",
    "CREATE INDEX IF NOT EXISTS ix_finmandatos_cmu ON finanzas_mandatos (cmu)",
```

- [ ] **Step 2: Verificar que la app arranca**

Run: `python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Verificar que el DDL coincide con el modelo, columna por columna**

Run:
```bash
python -c "
from app.models.finanzas_mandatos import FinanzasMandato as F
for c in F.__table__.columns:
    print(f'{c.name:18} {str(c.type):28} null={c.nullable}')
"
```
Comparar contra el DDL escrito. Tipos, longitudes y nulabilidad deben coincidir.
**Si algo no coincide, PARAR y reportar** — un DDL que discrepe del modelo crea
tablas distintas en desarrollo y producción.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "chore(mandatos): declarar finanzas_mandatos en _PENDING_DDLS"
```

---

### Task 4: Estados nuevos y grafo de transiciones

El envío a inversionistas sigue en alcance, así que el modelo de Finanzas necesita
`enviado_inversionista` y el ciclo `con_comentarios` → `corregido`.

**Files:**
- Modify: `app/models/finanzas_mandatos.py` (`EstadoFirmaEnum`, ~17)
- Modify: `app/services/finanzas_mandatos_service.py`
- Modify: `app/main.py` → `_PENDING_DDLS`
- Modify: `tests/test_finanzas_mandatos_service.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `tests/test_finanzas_mandatos_service.py`:

```python
from app.services.finanzas_mandatos_service import transicion_firma_valida


# ── grafo de transiciones ─────────────────────────────────────────────────────

def test_ciclo_de_correccion():
    assert transicion_firma_valida("sin_firma", "con_comentarios")
    assert transicion_firma_valida("con_comentarios", "corregido")
    assert transicion_firma_valida("corregido", "firmado")


def test_entrega_al_inversionista_solo_desde_firmado():
    assert transicion_firma_valida("firmado", "enviado_inversionista")
    assert not transicion_firma_valida("sin_firma", "enviado_inversionista")


def test_no_se_entrega_un_mandato_con_comentarios_abiertos():
    """Anomalía real: mandar al inversionista algo que la revisoría objetó.
    Nunca se aplica solo; tiene que verlo una persona."""
    assert not transicion_firma_valida("con_comentarios", "enviado_inversionista")


def test_enviado_inversionista_es_terminal():
    for destino in ("sin_firma", "con_comentarios", "corregido", "firmado"):
        assert not transicion_firma_valida("enviado_inversionista", destino)


def test_nunca_se_degrada_un_firmado():
    assert not transicion_firma_valida("firmado", "sin_firma")
    assert not transicion_firma_valida("firmado", "con_comentarios")
```

- [ ] **Step 2: Correr para ver el fallo**

Run: `python -m pytest tests/test_finanzas_mandatos_service.py -v`
Expected: FAIL con `ImportError: cannot import name 'transicion_firma_valida'`

- [ ] **Step 3: Ampliar el enum**

En `app/models/finanzas_mandatos.py`:

```python
class EstadoFirmaEnum(str, enum.Enum):
    sin_firma = "sin_firma"
    firmado = "firmado"
    con_comentarios = "con_comentarios"
    # Agregados 2026-08-18 para la integración con Fase B: el ciclo de
    # corrección y la entrega al inversionista, que el diseño original de
    # Finanzas dejó fuera de la v1.
    corregido = "corregido"
    enviado_inversionista = "enviado_inversionista"
```

- [ ] **Step 4: Agregar el grafo**

En `app/services/finanzas_mandatos_service.py`, junto a las demás constantes de
arriba:

```python
# Transiciones permitidas del estado de firma. Mismo criterio que TRANSICIONES en
# mandatos_service.py: el grafo es la red de seguridad de la ingesta automática --
# si un correo propone un salto que no está acá, no se aplica y queda registrado.
TRANSICIONES_FIRMA = {
    "sin_firma":             {"con_comentarios", "firmado"},
    "con_comentarios":       {"corregido"},
    "corregido":             {"firmado", "sin_firma"},
    "firmado":               {"enviado_inversionista"},
    "enviado_inversionista": set(),
}


def transicion_firma_valida(estado_actual: str, estado_nuevo: str) -> bool:
    return estado_nuevo in TRANSICIONES_FIRMA.get(estado_actual, set())
```

**No cablear todavía `transicion_firma_valida` dentro de `upsert_mandato`.** Hoy esa
función la usa el script de Jessica vía `/ingest`, y meterle una validación nueva
cambiaría su comportamiento — que es justo lo que este plan promete no hacer. El
cableado va en el Plan 2, junto con el adaptador.

- [ ] **Step 5: Agregar los valores del enum en la base**

En `_PENDING_DDLS` de `app/main.py`, junto a los demás `ADD VALUE`:

```python
    "ALTER TYPE estado_firma_fin_enum ADD VALUE IF NOT EXISTS 'corregido'",
    "ALTER TYPE estado_firma_fin_enum ADD VALUE IF NOT EXISTS 'enviado_inversionista'",
```

`_run_create_tables` ya separa los `ADD VALUE` del resto (`app/main.py:1400-1401`)
porque Postgres no admite agregar valores a un enum dentro de la misma transacción
que los usa. No hay que hacer nada extra, solo poner las sentencias en la lista.

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_finanzas_mandatos_service.py -v`
Expected: todos PASS.

- [ ] **Step 7: Verificar que no se rompió la ingesta actual**

Run: `python -m pytest tests/ -q`
Expected: 1230+ passed, 0 failed. En particular
`tests/test_finanzas_mandatos_ingest.py` debe seguir verde: el script de Jessica no
puede haber cambiado de comportamiento.

- [ ] **Step 8: Commit**

```bash
git add app/models/finanzas_mandatos.py app/services/finanzas_mandatos_service.py app/main.py tests/test_finanzas_mandatos_service.py
git commit -m "feat(mandatos): estados corregido/enviado_inversionista + grafo de transiciones"
```

---

## Verificación después del deploy

Este plan no cambia comportamiento, así que la verificación es que **nada se movió**:

1. En Railway → Deploy Logs, confirmar que el arranque no reporta errores de DDL.
   Los `ALTER TYPE ... ADD VALUE IF NOT EXISTS` son idempotentes y silenciosos.
2. Confirmar que `/finanzas/mandatos?periodo=YYYY-MM` sigue respondiendo igual.
3. Si Jessica corre su script, debe seguir funcionando exactamente como antes.

## Lo que este plan deja listo para el Plan 2

- Un parser de nombres que acepta las dos convenciones reales
- `extraer_pa_del_cuerpo()` para armar el `tercero` de la identidad
- Los estados que faltaban, con un grafo que los valida
- El esquema declarado donde el resto del proyecto lo declara

Lo que **no** hace, a propósito: no prende el cron, no escribe en la tabla de
Jessica, no valida transiciones dentro de `upsert_mandato`, no toca el frontend.
