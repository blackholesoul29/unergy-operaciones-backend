# Descarga de XM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the "Descarga de XM" tab in Finanzas — connect to XM's FTP with user-supplied credentials, download files of a chosen type/extension/date range, unify them (same logic as `Unificacion.ipynb`), optionally enrich grip/arrpas/tgrl/cxcsb with plant name+MW from the FTP's own monthly fronteras snapshot, and serve the result as Excel + TXT.

**Architecture:** Backend is a set of small pure/testable modules under `app/services/xm/` (type config, download planning, FTP client, fronteras parsing, unification/enrichment, in-memory job store) glued together by an orchestrator function that runs in a background thread (not `asyncio`/`BackgroundTasks`, because `ftplib` is blocking and the app runs a single uvicorn worker — blocking the event loop would freeze the status-polling endpoint too). Three REST endpoints expose start/poll/download. Frontend is one Vue view that starts a job and polls it.

**Tech Stack:** FastAPI, `ftplib.FTP_TLS` (stdlib), `pandas` (new dependency), `openpyxl` (already present), Vue 3 + PrimeVue 4, `threading` for the background job.

**Reference spec:** `docs/superpowers/specs/2026-07-02-descarga-xm-design.md`

---

## File Structure

Backend (`unergy-operaciones-backend`):
- `app/services/xm/__init__.py` — new, empty package marker
- `app/services/xm/exceptions.py` — new, FTP exception types
- `app/services/xm/tipos.py` — new, static config: routes, filename patterns, enrichment column per type
- `app/services/xm/plan_descarga.py` — new, pure function that expands a date range into a list of files to fetch
- `app/services/xm/ftp_client.py` — new, thin real-I/O wrapper around `ftplib.FTP_TLS`
- `app/services/xm/downloader.py` — new, retry/reconnect orchestration over `plan_descarga` + `ftp_client` (dependency-injected for testing)
- `app/services/xm/fronteras.py` — new, monthly fronteras snapshot: pick latest file, parse by column name, fallback to prior month
- `app/services/xm/unificador.py` — new, CSV unification, enrichment merge, xlsx/txt export
- `app/services/xm/jobs.py` — new, thread-safe in-memory job store with TTL
- `app/services/xm/orquestador.py` — new, ties everything together; runs inside the background thread
- `app/schemas/xm_descargas.py` — new, request/response Pydantic models
- `app/api/v1/xm_descargas.py` — new, the 3 endpoints
- `app/api/v1/router.py` — modify, register the new router
- `requirements.txt` — modify, add `pandas`
- `tests/test_xm_tipos.py`, `tests/test_xm_plan_descarga.py`, `tests/test_xm_fronteras.py`, `tests/test_xm_unificador.py`, `tests/test_xm_jobs.py`, `tests/test_xm_downloader.py` — new

Frontend (`unergy-operaciones-frontend`):
- `src/api/xm.js` — new, thin API wrapper
- `src/views/Finanzas/DescargaXMView.vue` — new, the form + polling UI
- `src/router/index.js` — modify, add route
- `src/components/AppSidebar.vue` — modify, add menu entry

No database changes — job state is in-memory only, per spec ("Fuera de alcance").

---

## Task 1: FTP exception types

**Files:**
- Create: `app/services/xm/__init__.py`
- Create: `app/services/xm/exceptions.py`
- Test: `tests/test_xm_exceptions.py`

- [ ] **Step 1: Create the empty package marker**

Create `app/services/xm/__init__.py` with no content (empty file).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_xm_exceptions.py
from app.services.xm.exceptions import (
    FTPConnectionError, FTPAuthenticationError, FTPPermissionError,
    FTPFileNotFoundError, FTPTimeoutError,
)


def test_http_status_codes():
    assert FTPConnectionError("x").http_status == 503
    assert FTPAuthenticationError("x").http_status == 401
    assert FTPPermissionError("x").http_status == 403
    assert FTPFileNotFoundError("x").http_status == 404
    assert FTPTimeoutError("x").http_status == 504
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_xm_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.exceptions'`

- [ ] **Step 4: Write the implementation**

```python
# app/services/xm/exceptions.py
class FTPConnectionError(Exception):
    http_status = 503


class FTPAuthenticationError(Exception):
    http_status = 401


class FTPPermissionError(Exception):
    http_status = 403


class FTPFileNotFoundError(Exception):
    http_status = 404


class FTPTimeoutError(Exception):
    http_status = 504
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_xm_exceptions.py -v`
Expected: PASS (5 assertions in 1 test)

- [ ] **Step 6: Commit**

```bash
git add app/services/xm/__init__.py app/services/xm/exceptions.py tests/test_xm_exceptions.py
git commit -m "feat(xm): add typed FTP exceptions for Descarga de XM"
```

---

## Task 2: Type config (`tipos.py`)

**Files:**
- Create: `app/services/xm/tipos.py`
- Test: `tests/test_xm_tipos.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_tipos.py
import pytest
from app.services.xm.tipos import (
    validar_tipo, TipoXMInvalido, ruta_directorio, es_mensual, nombre_archivo,
    TIPOS_ENRIQUECIBLES, COLUMNA_CODIGO_ENRIQUECIMIENTO,
)


def test_validar_tipo_conocido_no_lanza():
    validar_tipo("grip")


def test_validar_tipo_desconocido_lanza():
    with pytest.raises(TipoXMInvalido):
        validar_tipo("no_existe")


def test_ruta_directorio_publica():
    assert ruta_directorio("grip", 2026, 5) == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_ruta_directorio_privada():
    assert ruta_directorio("dspcttos", 2026, 5) == "/INFORMACION_XM/USUARIOSK/UNGG/SIC/COMERCIA/2026-05"


def test_es_mensual_cxcsb_true_y_grip_false():
    assert es_mensual("cxcsb") is True
    assert es_mensual("grip") is False


def test_nombre_archivo_diario():
    assert nombre_archivo("grip", "txf", 2026, 5, 7) == "grip0507.txf"


def test_nombre_archivo_mensual():
    assert nombre_archivo("cxcsb", "TXF", 2026, 5) == "cxcsb05.txf"


def test_nombre_archivo_diario_sin_dia_lanza():
    with pytest.raises(ValueError):
        nombre_archivo("grip", "txf", 2026, 5)


def test_tipos_enriquecibles_y_columna():
    assert TIPOS_ENRIQUECIBLES == {"grip", "arrpas", "tgrl", "cxcsb"}
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["grip"] == "PLANTA"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["arrpas"] == "SUBMERCADO"
    assert COLUMNA_CODIGO_ENRIQUECIMIENTO["cxcsb"] == "SUBMERCADO"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_tipos.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.tipos'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/tipos.py
"""Config de tipos de archivo XM soportados por la Descarga de XM.

Rutas confirmadas por la usuaria y por xm.py/aenc_reporte.py (ver spec).
"""

RUTA_PUBLICA = "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/{anio}-{mes:02d}"
RUTA_PRIVADA = "/INFORMACION_XM/USUARIOSK/UNGG/SIC/COMERCIA/{anio}-{mes:02d}"

TIPOS_CONFIG = {
    "dspcttos": {"ruta": "privada", "patron": "diario"},
    "aenc":     {"ruta": "privada", "patron": "diario"},
    "BalCttos": {"ruta": "privada", "patron": "diario"},
    "grip":     {"ruta": "publica", "patron": "diario"},
    "arrpas":   {"ruta": "publica", "patron": "diario"},
    "tgrl":     {"ruta": "publica", "patron": "diario"},
    "trsd":     {"ruta": "publica", "patron": "diario"},
    "cxcsb":    {"ruta": "publica", "patron": "mensual"},
}

# Tipos cuyo archivo trae código SIC de planta y se puede enriquecer con
# nombre + MW desde el snapshot mensual de fronteras del FTP.
TIPOS_ENRIQUECIBLES = {"grip", "arrpas", "tgrl", "cxcsb"}

# Columna del archivo XM que trae el código SIC de planta, según tipo.
COLUMNA_CODIGO_ENRIQUECIMIENTO = {
    "grip": "PLANTA",
    "tgrl": "PLANTA",
    "arrpas": "SUBMERCADO",
    "cxcsb": "SUBMERCADO",
}


class TipoXMInvalido(ValueError):
    pass


def validar_tipo(tipo: str) -> None:
    if tipo not in TIPOS_CONFIG:
        raise TipoXMInvalido(f"Tipo de archivo XM no soportado: {tipo}")


def es_mensual(tipo: str) -> bool:
    validar_tipo(tipo)
    return TIPOS_CONFIG[tipo]["patron"] == "mensual"


def ruta_directorio(tipo: str, anio: int, mes: int) -> str:
    validar_tipo(tipo)
    plantilla = RUTA_PUBLICA if TIPOS_CONFIG[tipo]["ruta"] == "publica" else RUTA_PRIVADA
    return plantilla.format(anio=anio, mes=mes)


def nombre_archivo(tipo: str, extension: str, anio: int, mes: int, dia: int | None = None) -> str:
    validar_tipo(tipo)
    if es_mensual(tipo):
        return f"{tipo}{mes:02d}.{extension.lower()}"
    if dia is None:
        raise ValueError(f"El tipo '{tipo}' requiere día (patrón diario)")
    return f"{tipo}{mes:02d}{dia:02d}.{extension.lower()}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_tipos.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/tipos.py tests/test_xm_tipos.py
git commit -m "feat(xm): add type/route config for Descarga de XM"
```

---

## Task 3: Download plan (`plan_descarga.py`)

**Files:**
- Create: `app/services/xm/plan_descarga.py`
- Test: `tests/test_xm_plan_descarga.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_plan_descarga.py
import pytest
from datetime import date
from app.services.xm.plan_descarga import construir_plan_descarga


def test_plan_diario_un_solo_mes():
    plan = construir_plan_descarga("grip", "txf", date(2026, 5, 1), date(2026, 5, 3))
    assert [p["nombre_archivo"] for p in plan] == ["grip0501.txf", "grip0502.txf", "grip0503.txf"]
    assert plan[0]["fecha_documento"] == "2026-05-01"
    assert plan[0]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_plan_diario_cruza_meses():
    plan = construir_plan_descarga("grip", "txf", date(2026, 4, 29), date(2026, 5, 2))
    nombres = [p["nombre_archivo"] for p in plan]
    assert nombres == ["grip0429.txf", "grip0430.txf", "grip0501.txf", "grip0502.txf"]
    assert plan[0]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-04"
    assert plan[-1]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_plan_mensual_cxcsb():
    plan = construir_plan_descarga("cxcsb", "txf", date(2026, 3, 15), date(2026, 5, 20))
    assert [p["nombre_archivo"] for p in plan] == ["cxcsb03.txf", "cxcsb04.txf", "cxcsb05.txf"]
    assert [p["fecha_documento"] for p in plan] == ["2026-03", "2026-04", "2026-05"]


def test_fecha_fin_antes_de_inicio_lanza():
    with pytest.raises(ValueError):
        construir_plan_descarga("grip", "txf", date(2026, 5, 10), date(2026, 5, 1))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_plan_descarga.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.plan_descarga'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/plan_descarga.py
import calendar
from datetime import date

from app.services.xm.tipos import validar_tipo, es_mensual, nombre_archivo, ruta_directorio


def construir_plan_descarga(tipo: str, extension: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
    """Expande un rango de fechas en la lista de archivos a intentar descargar.

    Cada item: {anio, mes, dia, directorio, nombre_archivo, fecha_documento}.
    `dia` es None para tipos mensuales (cxcsb). `fecha_documento` es
    'YYYY-MM-DD' para diarios o 'YYYY-MM' para mensuales.
    """
    validar_tipo(tipo)
    if fecha_fin < fecha_inicio:
        raise ValueError("fecha_fin no puede ser anterior a fecha_inicio")

    plan = []
    mensual = es_mensual(tipo)
    anio, mes = fecha_inicio.year, fecha_inicio.month

    while (anio, mes) <= (fecha_fin.year, fecha_fin.month):
        directorio = ruta_directorio(tipo, anio, mes)
        if mensual:
            plan.append({
                "anio": anio, "mes": mes, "dia": None,
                "directorio": directorio,
                "nombre_archivo": nombre_archivo(tipo, extension, anio, mes),
                "fecha_documento": f"{anio:04d}-{mes:02d}",
            })
        else:
            ultimo_dia = calendar.monthrange(anio, mes)[1]
            dia_desde = fecha_inicio.day if (anio, mes) == (fecha_inicio.year, fecha_inicio.month) else 1
            dia_hasta = fecha_fin.day if (anio, mes) == (fecha_fin.year, fecha_fin.month) else ultimo_dia
            for dia in range(dia_desde, dia_hasta + 1):
                plan.append({
                    "anio": anio, "mes": mes, "dia": dia,
                    "directorio": directorio,
                    "nombre_archivo": nombre_archivo(tipo, extension, anio, mes, dia),
                    "fecha_documento": f"{anio:04d}-{mes:02d}-{dia:02d}",
                })
        if mes == 12:
            anio, mes = anio + 1, 1
        else:
            mes += 1

    return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_plan_descarga.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/plan_descarga.py tests/test_xm_plan_descarga.py
git commit -m "feat(xm): expand date ranges into per-file download plans"
```

---

## Task 4: Fronteras snapshot (`fronteras.py`)

**Files:**
- Create: `app/services/xm/fronteras.py`
- Test: `tests/test_xm_fronteras.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_fronteras.py
import io
import openpyxl

from app.services.xm.fronteras import (
    carpeta_fronteras, elegir_ultimo_archivo, parsear_fronteras_xlsx, obtener_fronteras_mes,
)


def test_carpeta_fronteras():
    assert carpeta_fronteras(2026, 5) == "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/2026-05"


def test_elegir_ultimo_archivo_ordena_por_dia():
    nombres = [
        "UNGG_FronterasComerciales_05-05-2026.xlsx",
        "UNGG_FronterasComerciales_23-05-2026.xlsx",
        "UNGG_FronterasComerciales_10-05-2026.xlsx",
        "otro_archivo.txt",
    ]
    assert elegir_ultimo_archivo(nombres) == "UNGG_FronterasComerciales_23-05-2026.xlsx"


def test_elegir_ultimo_archivo_vacio():
    assert elegir_ultimo_archivo(["algo.txt"]) is None


def _xlsx_de_prueba():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fronteras Comerciales"
    ws.append([
        "Código SIC", "Nombre de la Frontera", "Tipo de Frontera",
        "Código SIC Submercado Exportador", "Capacidad efectiva [MW]",
    ])
    ws.append(["Frt39007", "PLANTA SOLAR BAYUNCA I", "Generacion", "3A44", 3.0])
    ws.append(["Frt51338", "GRANJA SOLAR URUACO", "Generacion", "3HYG", 0.996])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parsear_fronteras_xlsx():
    tabla = parsear_fronteras_xlsx(_xlsx_de_prueba())
    assert tabla["3A44"] == {"nombre": "PLANTA SOLAR BAYUNCA I", "tipo": "Generacion", "mw": 3.0}
    assert tabla["3HYG"]["nombre"] == "GRANJA SOLAR URUACO"


def test_obtener_fronteras_mes_usa_ultimo_archivo_del_mes():
    contenido = _xlsx_de_prueba()

    def listar_fn(directorio):
        assert directorio == "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/2026-05"
        return [
            "UNGG_FronterasComerciales_05-05-2026.xlsx",
            "UNGG_FronterasComerciales_23-05-2026.xlsx",
        ]

    def descargar_fn(directorio, nombre):
        assert nombre == "UNGG_FronterasComerciales_23-05-2026.xlsx"
        return contenido

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5)
    assert mes_usado == "2026-05"
    assert archivo_usado == "UNGG_FronterasComerciales_23-05-2026.xlsx"
    assert tabla["3A44"]["mw"] == 3.0


def test_obtener_fronteras_mes_retrocede_si_mes_vacio():
    contenido = _xlsx_de_prueba()

    def listar_fn(directorio):
        if directorio.endswith("2026-05"):
            return []
        if directorio.endswith("2026-04"):
            return ["UNGG_FronterasComerciales_30-04-2026.xlsx"]
        return []

    def descargar_fn(directorio, nombre):
        return contenido

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5)
    assert mes_usado == "2026-04"
    assert archivo_usado == "UNGG_FronterasComerciales_30-04-2026.xlsx"


def test_obtener_fronteras_mes_sin_datos_devuelve_vacio():
    def listar_fn(directorio):
        return []

    def descargar_fn(directorio, nombre):
        raise AssertionError("no debería intentar descargar nada")

    tabla, mes_usado, archivo_usado = obtener_fronteras_mes(listar_fn, descargar_fn, 2026, 5, max_retroceso=1)
    assert tabla == {}
    assert mes_usado is None
    assert archivo_usado is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_fronteras.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.fronteras'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/fronteras.py
"""Snapshot mensual de fronteras comerciales del FTP de XM.

El enriquecimiento de grip/arrpas/tgrl/cxcsb usa el ÚLTIMO archivo
UNGG_FronterasComerciales_DD-MM-YYYY.xlsx disponible en el mes del dato
(no la tabla `fronteras` de la BD, que no guarda histórico por período).
Ver docs/superpowers/specs/2026-07-02-descarga-xm-design.md sección 4.
"""
import io

FRONTERAS_DIR = "/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/{anio}-{mes:02d}"
FRONTERAS_PREFIJO = "UNGG_FronterasComerciales_"
HOJA = "Fronteras Comerciales"


def carpeta_fronteras(anio: int, mes: int) -> str:
    return FRONTERAS_DIR.format(anio=anio, mes=mes)


def elegir_ultimo_archivo(nombres: list[str]) -> str | None:
    """Los nombres empiezan por DD-MM-YYYY dentro de una carpeta de mes fijo,
    así que ordenar alfabéticamente da el día más reciente."""
    candidatos = sorted(
        n for n in nombres
        if n.startswith(FRONTERAS_PREFIJO) and n.lower().endswith(".xlsx")
    )
    return candidatos[-1] if candidatos else None


def parsear_fronteras_xlsx(contenido: bytes) -> dict:
    """Devuelve {codigo_sic_submercado_exportador: {nombre, tipo, mw}}.

    Lee por nombre de columna (no por índice fijo) para no romper si XM
    reordena columnas.
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    ws = wb[HOJA]
    filas = ws.iter_rows(values_only=True)
    header = next(filas)

    idx = {}
    for i, h in enumerate(header):
        if not h:
            continue
        h_norm = str(h).strip()
        if "Submercado Exportador" in h_norm:
            idx["codigo"] = i
        elif h_norm == "Nombre de la Frontera":
            idx["nombre"] = i
        elif h_norm == "Tipo de Frontera":
            idx["tipo"] = i
        elif h_norm.startswith("Capacidad efectiva"):
            idx["mw"] = i

    faltantes = {"codigo", "nombre", "tipo", "mw"} - idx.keys()
    if faltantes:
        raise ValueError(f"Columnas no encontradas en el Excel de fronteras: {sorted(faltantes)}")

    resultado = {}
    for fila in filas:
        codigo = fila[idx["codigo"]]
        if not codigo:
            continue
        resultado[str(codigo).strip()] = {
            "nombre": fila[idx["nombre"]],
            "tipo": fila[idx["tipo"]],
            "mw": fila[idx["mw"]],
        }
    return resultado


def obtener_fronteras_mes(listar_fn, descargar_fn, anio: int, mes: int, max_retroceso: int = 3):
    """Busca el último archivo de fronteras del mes pedido; si esa carpeta
    no tiene archivos, retrocede mes a mes hasta `max_retroceso` veces.

    `listar_fn(directorio) -> list[str]` y `descargar_fn(directorio, nombre) -> bytes`
    se inyectan para poder testear sin FTP real; en producción son
    wrappers sobre `ftp_client.listar_directorio`/`descargar_bytes`.

    Devuelve (tabla, mes_usado: 'YYYY-MM' | None, archivo_usado: str | None).
    """
    a, m = anio, mes
    for _ in range(max_retroceso + 1):
        directorio = carpeta_fronteras(a, m)
        nombres = listar_fn(directorio)
        archivo = elegir_ultimo_archivo(nombres)
        if archivo:
            contenido = descargar_fn(directorio, archivo)
            return parsear_fronteras_xlsx(contenido), f"{a:04d}-{m:02d}", archivo
        m -= 1
        if m == 0:
            m, a = 12, a - 1
    return {}, None, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_fronteras.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/fronteras.py tests/test_xm_fronteras.py
git commit -m "feat(xm): parse monthly fronteras snapshot from FTP for enrichment"
```

---

## Task 5: Unification and enrichment (`unificador.py`)

**Files:**
- Create: `app/services/xm/unificador.py`
- Test: `tests/test_xm_unificador.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_unificador.py
import pandas as pd
from datetime import date

from app.services.xm.unificador import (
    encoding_para, unificar, nombre_salida, exportar, enriquecer,
)


def test_encoding_para_aenc_es_latin1():
    assert encoding_para("aenc") == "latin1"


def test_encoding_para_otros_es_utf8_sig():
    assert encoding_para("grip") == "utf-8-sig"


def _csv_bytes(texto):
    return texto.encode("utf-8-sig")


def test_unificar_agrega_fecha_como_primera_columna_y_concatena():
    archivos = [
        ("2026-05-01", _csv_bytes("PLANTA;HORA 01\n3A44;10.5\n")),
        ("2026-05-02", _csv_bytes("PLANTA;HORA 01\n3A44;11.0\n")),
    ]
    df = unificar("grip", archivos)
    assert list(df.columns)[0] == "FechaDocumento"
    assert list(df["FechaDocumento"]) == ["2026-05-01", "2026-05-02"]
    assert len(df) == 2


def test_unificar_sin_archivos_devuelve_vacio():
    df = unificar("grip", [])
    assert df.empty


def test_nombre_salida_un_solo_mes():
    xlsx, txt = nombre_salida("grip", "txf", date(2026, 5, 1), date(2026, 5, 31))
    assert xlsx == "grip_txf_05.xlsx"
    assert txt == "grip_txf_05.txf"


def test_nombre_salida_cruza_meses():
    xlsx, txt = nombre_salida("grip", "txf", date(2026, 4, 29), date(2026, 5, 2))
    assert xlsx == "grip_txf_04-05.xlsx"
    assert txt == "grip_txf_04-05.txf"


def test_exportar_devuelve_bytes_no_vacios():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    bytes_xlsx, bytes_txt = exportar(df)
    assert len(bytes_xlsx) > 0
    assert b"a;b" in bytes_txt


def test_enriquecer_agrega_columnas_y_reporta_sin_match():
    df = pd.DataFrame({
        "FechaDocumento": ["2026-05-01", "2026-05-01"],
        "PLANTA": ["3A44", "9999"],
    })
    fronteras_por_mes = {
        "2026-05": {"3A44": {"nombre": "Bayunca I", "tipo": "Generacion", "mw": 3.0}},
    }
    df2, sin_match = enriquecer(df, "grip", fronteras_por_mes, "PLANTA")
    assert df2.loc[0, "Nombre de la Frontera"] == "Bayunca I"
    assert df2.loc[0, "Capacidad efectiva [MW]"] == 3.0
    assert sin_match == {"9999"}
    assert pd.isna(df2.loc[1, "Nombre de la Frontera"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_unificador.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.unificador'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/unificador.py
"""Unificación de archivos XM (misma lógica que Unificacion.ipynb) y
enriquecimiento opcional con datos de planta Unergy."""
import io
from datetime import date

import pandas as pd


def encoding_para(tipo: str) -> str:
    return "latin1" if tipo == "aenc" else "utf-8-sig"


def leer_csv(contenido: bytes, tipo: str) -> pd.DataFrame:
    encoding = encoding_para(tipo)
    try:
        return pd.read_csv(io.BytesIO(contenido), sep=";", encoding=encoding)
    except UnicodeDecodeError:
        return pd.read_csv(io.BytesIO(contenido), sep=";", encoding="latin1")


def unificar(tipo: str, archivos: list[tuple[str, bytes]]) -> pd.DataFrame:
    """archivos: [(fecha_documento, contenido_bytes), ...] ya en orden."""
    dataframes = []
    for fecha_documento, contenido in archivos:
        df = leer_csv(contenido, tipo)
        df.insert(0, "FechaDocumento", fecha_documento)
        dataframes.append(df)
    if not dataframes:
        return pd.DataFrame()
    return pd.concat(dataframes, ignore_index=True)


def nombre_salida(tipo: str, extension: str, fecha_inicio: date, fecha_fin: date) -> tuple[str, str]:
    if fecha_inicio.month == fecha_fin.month and fecha_inicio.year == fecha_fin.year:
        sufijo = f"{fecha_inicio.month:02d}"
    else:
        sufijo = f"{fecha_inicio.month:02d}-{fecha_fin.month:02d}"
    base = f"{tipo}_{extension.lower()}_{sufijo}"
    return f"{base}.xlsx", f"{base}.{extension.lower()}"


def exportar(df: pd.DataFrame) -> tuple[bytes, bytes]:
    buf_xlsx = io.BytesIO()
    df.to_excel(buf_xlsx, index=False, engine="openpyxl")
    buf_xlsx.seek(0)

    buf_txt = io.BytesIO()
    df.to_csv(buf_txt, sep=";", index=False, encoding="utf-8-sig")
    buf_txt.seek(0)

    return buf_xlsx.read(), buf_txt.read()


def enriquecer(df: pd.DataFrame, tipo: str, fronteras_por_mes: dict, columna_codigo: str):
    """fronteras_por_mes: {'YYYY-MM': {codigo: {nombre, tipo, mw}}, ...}.

    Cada fila se enriquece con el snapshot de fronteras de SU PROPIO mes
    (columna FechaDocumento), no uno solo para todo el rango.
    Devuelve (df_enriquecido, codigos_sin_match: set).
    """
    nombres, tipos_frontera, mws = [], [], []
    sin_match = set()

    for _, fila in df.iterrows():
        mes_dato = str(fila["FechaDocumento"])[:7]
        tabla = fronteras_por_mes.get(mes_dato, {})
        codigo = str(fila[columna_codigo]).strip()
        info = tabla.get(codigo)
        if info:
            nombres.append(info["nombre"])
            tipos_frontera.append(info["tipo"])
            mws.append(info["mw"])
        else:
            nombres.append(None)
            tipos_frontera.append(None)
            mws.append(None)
            sin_match.add(codigo)

    df = df.copy()
    df["Nombre de la Frontera"] = nombres
    df["Tipo de Frontera"] = tipos_frontera
    df["Capacidad efectiva [MW]"] = mws
    return df, sin_match
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_unificador.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/unificador.py tests/test_xm_unificador.py
git commit -m "feat(xm): unify XM files and enrich with plant data by month"
```

---

## Task 6: Job store (`jobs.py`)

**Files:**
- Create: `app/services/xm/jobs.py`
- Test: `tests/test_xm_jobs.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_jobs.py
import time
from app.services.xm import jobs


def test_crear_job_estado_inicial():
    job_id = jobs.crear_job()
    job = jobs.obtener_job(job_id)
    assert job["estado"] == "descargando"
    assert job["archivos_procesados"] == 0
    assert job["archivos_faltantes"] == []


def test_actualizar_job():
    job_id = jobs.crear_job()
    jobs.actualizar_job(job_id, estado="listo", archivos_procesados=10)
    job = jobs.obtener_job(job_id)
    assert job["estado"] == "listo"
    assert job["archivos_procesados"] == 10


def test_obtener_job_inexistente_devuelve_none():
    assert jobs.obtener_job("no-existe") is None


def test_job_expirado_se_limpia_al_crear_otro():
    job_id = jobs.crear_job()
    jobs._JOBS[job_id]["creado_en"] = time.time() - jobs._TTL_SEGUNDOS - 1
    jobs.crear_job()
    assert jobs.obtener_job(job_id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.jobs'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/jobs.py
"""Job store en memoria para la Descarga de XM.

El backend corre en un solo proceso uvicorn (sin --workers, ver
start.sh), así que un dict en memoria protegido por un lock basta —
no hace falta Redis ni tabla en BD para esto.
"""
import threading
import time
import uuid

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_TTL_SEGUNDOS = 3600


def crear_job() -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _limpiar_expirados()
        _JOBS[job_id] = {
            "estado": "descargando",
            "creado_en": time.time(),
            "archivos_procesados": 0,
            "archivos_totales": 0,
            "archivos_faltantes": [],
            "codigos_sin_match": [],
            "meses_fronteras_usados": {},
            "resultado": None,
            "error_code": None,
            "error_message": None,
        }
    return job_id


def actualizar_job(job_id: str, **campos) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(campos)


def obtener_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def _limpiar_expirados() -> None:
    ahora = time.time()
    expirados = [jid for jid, j in _JOBS.items() if ahora - j["creado_en"] > _TTL_SEGUNDOS]
    for jid in expirados:
        del _JOBS[jid]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_jobs.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/jobs.py tests/test_xm_jobs.py
git commit -m "feat(xm): add thread-safe in-memory job store with TTL"
```

---

## Task 7: FTP client (real I/O, thin wrapper)

**Files:**
- Create: `app/services/xm/ftp_client.py`

No dedicated test — this is a thin wrapper around `ftplib` with real
network I/O; it's exercised by the mandatory end-to-end test in Task 12.

- [ ] **Step 1: Write the implementation**

```python
# app/services/xm/ftp_client.py
"""Cliente FTPS real contra el servidor de XM.

Contexto SSL relajado (check_hostname/verify_mode desactivados) porque
el servidor de XM no pasa verificación TLS estricta — patrón tomado de
aenc_reporte.py, que ya corre en producción contra este mismo servidor.
"""
import ftplib
import io
import ssl

from app.services.xm.exceptions import (
    FTPAuthenticationError, FTPConnectionError, FTPFileNotFoundError,
    FTPPermissionError, FTPTimeoutError,
)


def conectar_ftp(host: str, usuario: str, clave: str, directorio: str,
                  puerto: int = 210, timeout: int = 30) -> ftplib.FTP_TLS:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    ftp = ftplib.FTP_TLS(context=ctx)
    try:
        ftp.connect(host, puerto, timeout=timeout)
    except TimeoutError as e:
        raise FTPTimeoutError(f"Conexión a {host}:{puerto} agotó el tiempo de espera: {e}")
    except OSError as e:
        raise FTPConnectionError(f"No se pudo conectar a {host}:{puerto}: {e}")

    try:
        ftp.auth()
        ftp.login(user=usuario, passwd=clave)
        ftp.prot_p()
    except ftplib.error_perm as e:
        raise FTPAuthenticationError(f"Autenticación FTP fallida para '{usuario}': {e}")

    try:
        ftp.cwd(directorio)
    except ftplib.error_perm as e:
        if "550" in str(e):
            raise FTPFileNotFoundError(f"Directorio no encontrado: {directorio}: {e}")
        raise FTPPermissionError(f"Sin acceso a {directorio}: {e}")

    return ftp


def listar_directorio(ftp: ftplib.FTP_TLS) -> list[str]:
    try:
        return ftp.nlst()
    except ftplib.error_perm:
        return []


def descargar_bytes(ftp: ftplib.FTP_TLS, nombre_archivo: str) -> bytes:
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {nombre_archivo}", buf.write)
    except ftplib.error_perm as e:
        raise FTPFileNotFoundError(f"Archivo no encontrado: {nombre_archivo}: {e}")
    buf.seek(0)
    return buf.read()
```

- [ ] **Step 2: Sanity-check it imports cleanly**

Run: `python -c "from app.services.xm.ftp_client import conectar_ftp, listar_directorio, descargar_bytes; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/services/xm/ftp_client.py
git commit -m "feat(xm): add FTPS client wrapper for XM's server"
```

---

## Task 8: Download orchestration with retries (`downloader.py`)

**Files:**
- Create: `app/services/xm/downloader.py`
- Test: `tests/test_xm_downloader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_xm_downloader.py
from datetime import date
from app.services.xm.downloader import ejecutar_descarga


def test_descarga_exitosa_sin_reintentos():
    llamadas = []

    def conectar_fn(host, usuario, clave, directorio):
        return {"directorio": directorio}

    def descargar_fn(ftp, nombre):
        llamadas.append(nombre)
        return b"contenido"

    archivos, faltantes = ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 2),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
    )
    assert llamadas == ["grip0501.txf", "grip0502.txf"]
    assert archivos == [("2026-05-01", b"contenido"), ("2026-05-02", b"contenido")]
    assert faltantes == []


def test_descarga_agota_reintentos_y_reporta_faltante():
    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        raise Exception("archivo no existe")

    archivos, faltantes = ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 1),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        max_reintentos=2, sleep_fn=lambda s: None,
    )
    assert archivos == []
    assert faltantes == ["grip0501.txf"]


def test_descarga_reporta_progreso():
    progresos = []

    def conectar_fn(host, usuario, clave, directorio):
        return object()

    def descargar_fn(ftp, nombre):
        return b"x"

    ejecutar_descarga(
        {"host": "h", "usuario": "u", "clave": "c"}, "grip", "txf",
        date(2026, 5, 1), date(2026, 5, 3),
        conectar_fn=conectar_fn, descargar_fn=descargar_fn,
        on_progreso=lambda hechos, total: progresos.append((hechos, total)),
    )
    assert progresos == [(1, 3), (2, 3), (3, 3)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_xm_downloader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.xm.downloader'`

- [ ] **Step 3: Write the implementation**

```python
# app/services/xm/downloader.py
"""Descarga con reintentos/reconexión sobre el plan de plan_descarga.

conectar_fn/descargar_fn/sleep_fn son inyectables para poder testear la
lógica de reintentos y progreso sin tocar la red real; en producción son
ftp_client.conectar_ftp / ftp_client.descargar_bytes / time.sleep.
"""
import time

from app.services.xm.ftp_client import conectar_ftp, descargar_bytes
from app.services.xm.plan_descarga import construir_plan_descarga


def ejecutar_descarga(ftp_params: dict, tipo: str, extension: str, fecha_inicio, fecha_fin,
                       on_progreso=None, max_reintentos: int = 3, espera_reintento: int = 10,
                       conectar_fn=conectar_ftp, descargar_fn=descargar_bytes, sleep_fn=time.sleep):
    plan = construir_plan_descarga(tipo, extension, fecha_inicio, fecha_fin)
    archivos = []
    faltantes = []
    ftp = None
    directorio_actual = None

    for i, item in enumerate(plan):
        if ftp is None or directorio_actual != item["directorio"]:
            ftp = conectar_fn(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], item["directorio"])
            directorio_actual = item["directorio"]

        contenido = None
        for intento in range(max_reintentos):
            try:
                contenido = descargar_fn(ftp, item["nombre_archivo"])
                break
            except Exception:
                if intento < max_reintentos - 1:
                    sleep_fn(espera_reintento)
                    ftp = conectar_fn(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], item["directorio"])
                    directorio_actual = item["directorio"]

        if contenido is None:
            faltantes.append(item["nombre_archivo"])
        else:
            archivos.append((item["fecha_documento"], contenido))

        if on_progreso:
            on_progreso(i + 1, len(plan))

    return archivos, faltantes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_xm_downloader.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app/services/xm/downloader.py tests/test_xm_downloader.py
git commit -m "feat(xm): add download orchestration with retry/reconnect"
```

---

## Task 9: Job orchestrator (`orquestador.py`)

**Files:**
- Create: `app/services/xm/orquestador.py`

No dedicated unit test — this is integration glue over already-tested
modules plus real FTP I/O; verified by the end-to-end test in Task 12.

- [ ] **Step 1: Write the implementation**

```python
# app/services/xm/orquestador.py
"""Orquesta un job completo de Descarga de XM: descarga -> unifica ->
(opcional) enriquece -> exporta. Corre dentro de un hilo en background
(ver api/v1/xm_descargas.py) porque ftplib es bloqueante."""
from app.services.xm import jobs, tipos
from app.services.xm.downloader import ejecutar_descarga
from app.services.xm.exceptions import (
    FTPAuthenticationError, FTPConnectionError, FTPFileNotFoundError,
    FTPPermissionError, FTPTimeoutError,
)
from app.services.xm.ftp_client import conectar_ftp, descargar_bytes, listar_directorio
from app.services.xm.fronteras import obtener_fronteras_mes
from app.services.xm.unificador import enriquecer, exportar, nombre_salida, unificar

ERRORES_FTP = (FTPConnectionError, FTPAuthenticationError, FTPPermissionError,
               FTPFileNotFoundError, FTPTimeoutError)

CODIGO_ERROR = {
    "FTPConnectionError": "FTP_CONNECTION_FAILED",
    "FTPAuthenticationError": "FTP_AUTH_FAILED",
    "FTPPermissionError": "FTP_PERMISSION_DENIED",
    "FTPFileNotFoundError": "FTP_FILE_NOT_FOUND",
    "FTPTimeoutError": "FTP_TIMEOUT",
}


def _listar_fn(ftp_params, directorio):
    ftp = conectar_ftp(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], directorio)
    try:
        return listar_directorio(ftp)
    finally:
        ftp.quit()


def _descargar_fn(ftp_params, directorio, nombre):
    ftp = conectar_ftp(ftp_params["host"], ftp_params["usuario"], ftp_params["clave"], directorio)
    try:
        return descargar_bytes(ftp, nombre)
    finally:
        ftp.quit()


def ejecutar_job(job_id: str, ftp_params: dict, tipo: str, extension: str,
                  fecha_inicio, fecha_fin, enriquecer_flag: bool) -> None:
    try:
        def on_progreso(hechos, totales):
            jobs.actualizar_job(job_id, archivos_procesados=hechos, archivos_totales=totales)

        archivos, faltantes = ejecutar_descarga(
            ftp_params, tipo, extension, fecha_inicio, fecha_fin, on_progreso=on_progreso,
        )
        jobs.actualizar_job(job_id, estado="unificando", archivos_faltantes=faltantes)

        df = unificar(tipo, archivos)
        codigos_sin_match: list[str] = []
        meses_usados: dict = {}

        if enriquecer_flag and tipo in tipos.TIPOS_ENRIQUECIBLES and not df.empty:
            meses = sorted({fecha_doc[:7] for fecha_doc, _ in archivos})
            fronteras_por_mes = {}
            for mes_str in meses:
                anio, mes = int(mes_str[:4]), int(mes_str[5:7])
                tabla, mes_usado, archivo_usado = obtener_fronteras_mes(
                    lambda d, _fp=ftp_params: _listar_fn(_fp, d),
                    lambda d, n, _fp=ftp_params: _descargar_fn(_fp, d, n),
                    anio, mes,
                )
                fronteras_por_mes[mes_str] = tabla
                meses_usados[mes_str] = {"mes_usado": mes_usado, "archivo": archivo_usado}

            columna = tipos.COLUMNA_CODIGO_ENRIQUECIMIENTO[tipo]
            df, sin_match_set = enriquecer(df, tipo, fronteras_por_mes, columna)
            codigos_sin_match = sorted(sin_match_set)

        nombre_xlsx, nombre_txt = nombre_salida(tipo, extension, fecha_inicio, fecha_fin)
        bytes_xlsx, bytes_txt = exportar(df)

        jobs.actualizar_job(
            job_id, estado="listo",
            codigos_sin_match=codigos_sin_match,
            meses_fronteras_usados=meses_usados,
            resultado={
                "nombre_xlsx": nombre_xlsx, "bytes_xlsx": bytes_xlsx,
                "nombre_txt": nombre_txt, "bytes_txt": bytes_txt,
            },
        )
    except ERRORES_FTP as e:
        jobs.actualizar_job(
            job_id, estado="error",
            error_code=CODIGO_ERROR.get(type(e).__name__, type(e).__name__),
            error_message=str(e),
        )
    except Exception as e:
        jobs.actualizar_job(job_id, estado="error", error_code="INTERNAL_ERROR", error_message=str(e))
```

- [ ] **Step 2: Sanity-check it imports cleanly**

Run: `python -c "from app.services.xm.orquestador import ejecutar_job; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/services/xm/orquestador.py
git commit -m "feat(xm): add job orchestrator tying download/unify/enrich together"
```

---

## Task 10: Schemas and endpoints

**Files:**
- Create: `app/schemas/xm_descargas.py`
- Create: `app/api/v1/xm_descargas.py`
- Modify: `app/api/v1/router.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add `pandas` to requirements**

Edit `requirements.txt`, add this line after `openpyxl>=3.1.0`:

```
pandas>=2.2.0
```

- [ ] **Step 2: Install it locally**

Run: `pip install pandas>=2.2.0`
Expected: install succeeds (or already satisfied, since pandas 3.0.1 is already present locally)

- [ ] **Step 3: Write the schemas**

```python
# app/schemas/xm_descargas.py
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class XMDescargaRequest(BaseModel):
    ftp_usuario: str
    ftp_clave: str
    ftp_host: str = "xmftps.xm.com.co"
    tipo: str
    extension: str
    fecha_inicio: date
    fecha_fin: date
    enriquecer: bool = False


class XMJobResponse(BaseModel):
    job_id: str


class XMJobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    estado: Literal["descargando", "unificando", "listo", "error"]
    archivos_procesados: int
    archivos_totales: int
    archivos_faltantes: list[str]
    codigos_sin_match: list[str]
    meses_fronteras_usados: dict
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

- [ ] **Step 4: Write the endpoints**

```python
# app/api/v1/xm_descargas.py
import io
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.v1.auth import get_current_user
from app.schemas.xm_descargas import XMDescargaRequest, XMJobResponse, XMJobStatus
from app.services.xm import jobs, tipos
from app.services.xm.orquestador import ejecutar_job

router = APIRouter(prefix="/xm", tags=["Descarga XM"])

EXTENSIONES_VALIDAS = {"txf", "txr", "tx1", "tx2", "tx3", "tx4", "tx5", "tx6", "tx7", "tx8"}


@router.post("/descargas", response_model=XMJobResponse)
def iniciar_descarga(body: XMDescargaRequest, _=Depends(get_current_user)):
    if body.tipo not in tipos.TIPOS_CONFIG:
        raise HTTPException(400, f"Tipo de archivo no soportado: {body.tipo}")
    if body.extension.lower() not in EXTENSIONES_VALIDAS:
        raise HTTPException(400, f"Extensión no soportada: {body.extension}")
    if body.fecha_fin < body.fecha_inicio:
        raise HTTPException(400, "fecha_fin no puede ser anterior a fecha_inicio")

    job_id = jobs.crear_job()
    ftp_params = {"host": body.ftp_host, "usuario": body.ftp_usuario, "clave": body.ftp_clave}

    hilo = threading.Thread(
        target=ejecutar_job,
        args=(job_id, ftp_params, body.tipo, body.extension, body.fecha_inicio, body.fecha_fin, body.enriquecer),
        daemon=True,
    )
    hilo.start()
    return XMJobResponse(job_id=job_id)


@router.get("/descargas/{job_id}", response_model=XMJobStatus)
def estado_descarga(job_id: str, _=Depends(get_current_user)):
    job = jobs.obtener_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado o expirado")
    campos = {k: v for k, v in job.items() if k not in ("resultado", "creado_en")}
    return XMJobStatus(job_id=job_id, **campos)


@router.get("/descargas/{job_id}/archivo")
def descargar_archivo(job_id: str, formato: str = "xlsx", _=Depends(get_current_user)):
    job = jobs.obtener_job(job_id)
    if job is None:
        raise HTTPException(404, "Job no encontrado o expirado")
    if job["estado"] != "listo":
        raise HTTPException(409, f"El job aún no está listo (estado actual: {job['estado']})")

    resultado = job["resultado"]
    if formato == "xlsx":
        contenido, nombre = resultado["bytes_xlsx"], resultado["nombre_xlsx"]
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif formato == "txt":
        contenido, nombre = resultado["bytes_txt"], resultado["nombre_txt"]
        media_type = "text/plain"
    else:
        raise HTTPException(400, "formato debe ser 'xlsx' o 'txt'")

    return StreamingResponse(
        io.BytesIO(contenido), media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
```

- [ ] **Step 5: Register the router**

In `app/api/v1/router.py`, add the import near the other `app.api.v1` imports and the `include_router` call at the end of the existing list (exact line depends on current file — append after the last `api_router.include_router(...)` line):

```python
from app.api.v1 import xm_descargas
```
```python
api_router.include_router(xm_descargas.router)
```

- [ ] **Step 6: Verify the app still boots**

Run: `python -c "from app.main import app; print('ok')"`
Expected: `ok` (no import errors)

- [ ] **Step 7: Commit**

```bash
git add app/schemas/xm_descargas.py app/api/v1/xm_descargas.py app/api/v1/router.py requirements.txt
git commit -m "feat(xm): add Descarga de XM REST endpoints"
```

---

## Task 11: Frontend — API wrapper, view, routing

**Files:**
- Create: `src/api/xm.js`
- Create: `src/views/Finanzas/DescargaXMView.vue`
- Modify: `src/router/index.js`
- Modify: `src/components/AppSidebar.vue`

- [ ] **Step 1: Write the API wrapper**

```javascript
// src/api/xm.js
import api from './client'

export function iniciarDescargaXM(payload) {
  return api.post('/xm/descargas', payload).then((r) => r.data)
}

export function consultarEstadoXM(jobId) {
  return api.get(`/xm/descargas/${jobId}`).then((r) => r.data)
}

export function descargarArchivoXM(jobId, formato) {
  return api
    .get(`/xm/descargas/${jobId}/archivo`, { params: { formato }, responseType: 'blob' })
    .then((r) => r.data)
}
```

- [ ] **Step 2: Write the view**

```vue
<!-- src/views/Finanzas/DescargaXMView.vue -->
<template>
  <div class="gf-page">
    <div class="mon-tab-bar">
      <i class="pi pi-cloud-download text-sm" style="color:#915BD8" />
      <span class="text-base font-bold text-gray-800 whitespace-nowrap mr-2">Descarga de XM</span>
    </div>

    <div class="max-w-3xl mx-auto mt-4 space-y-4">
      <div class="rounded-xl border bg-white p-5" style="border-color:#ECE7F2">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Usuario FTP</label>
            <input v-model="form.ftpUsuario" type="text" class="xm-input" autocomplete="off" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Clave FTP</label>
            <input v-model="form.ftpClave" type="password" class="xm-input" autocomplete="off" />
          </div>

          <div class="col-span-2 flex items-center gap-2">
            <Checkbox v-model="recordarCredenciales" binary inputId="xm-recordar" />
            <label for="xm-recordar" class="text-xs text-gray-500">
              Recordar en esta sesión del navegador
            </label>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Tipo de archivo</label>
            <Select v-model="form.tipo" :options="TIPOS" placeholder="Selecciona…" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Extensión</label>
            <Select v-model="form.extension" :options="EXTENSIONES" placeholder="Selecciona…" />
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Fecha inicio</label>
            <input v-model="form.fechaInicio" type="date" class="xm-input" />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-xs font-medium text-gray-500">Fecha fin</label>
            <input v-model="form.fechaFin" type="date" class="xm-input" />
          </div>

          <div class="col-span-2 flex items-center gap-2" v-if="tipoEsEnriquecible">
            <Checkbox v-model="form.enriquecer" binary inputId="xm-enriquecer" />
            <label for="xm-enriquecer" class="text-xs text-gray-500">
              Enriquecer con datos de planta Unergy (nombre + MW)
            </label>
          </div>
        </div>

        <div class="mt-4">
          <Button
            label="Descargar y unificar"
            icon="pi pi-download"
            :loading="enProceso"
            :disabled="!formularioValido || enProceso"
            @click="onDescargar"
            style="background:#915BD8;border-color:#915BD8"
          />
        </div>
      </div>

      <div v-if="estado" class="rounded-xl border p-4" style="border-color:#ECE7F2">
        <div v-if="estado.estado === 'descargando'" class="text-sm text-gray-600">
          <i class="pi pi-spin pi-spinner mr-2" style="color:#915BD8" />
          Descargando archivos… {{ estado.archivos_procesados }}/{{ estado.archivos_totales }}
        </div>

        <div v-else-if="estado.estado === 'unificando'" class="text-sm text-gray-600">
          <i class="pi pi-spin pi-spinner mr-2" style="color:#915BD8" />
          Unificando archivos…
        </div>

        <div v-else-if="estado.estado === 'listo'" class="space-y-2">
          <div class="text-sm font-semibold" style="color:#2C2039">Listo</div>
          <div v-if="estado.archivos_faltantes?.length" class="text-xs text-amber-600">
            {{ estado.archivos_faltantes.length }} archivo(s) no encontrados en el FTP para el rango.
          </div>
          <div v-if="estado.codigos_sin_match?.length" class="text-xs text-amber-600">
            Códigos sin match en fronteras: {{ estado.codigos_sin_match.join(', ') }}
          </div>
          <div class="flex gap-2">
            <Button label="Descargar Excel" icon="pi pi-file-excel" size="small" @click="onDescargarArchivo('xlsx')" />
            <Button label="Descargar TXT" icon="pi pi-file" size="small" outlined @click="onDescargarArchivo('txt')" />
          </div>
        </div>

        <div v-else-if="estado.estado === 'error'" class="text-sm text-red-600">
          <i class="pi pi-exclamation-circle mr-2" />
          {{ estado.error_message || 'Ocurrió un error al procesar la descarga.' }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import Select from 'primevue/select'
import Checkbox from 'primevue/checkbox'
import Button from 'primevue/button'
import { iniciarDescargaXM, consultarEstadoXM, descargarArchivoXM } from '@/api/xm'

const TIPOS = ['dspcttos', 'aenc', 'BalCttos', 'grip', 'arrpas', 'tgrl', 'trsd', 'cxcsb']
const EXTENSIONES = ['txf', 'txr', 'tx1', 'tx2', 'tx3', 'tx4', 'tx5', 'tx6', 'tx7', 'tx8']
const TIPOS_ENRIQUECIBLES = ['grip', 'arrpas', 'tgrl', 'cxcsb']
const STORAGE_KEY = 'xm_credenciales_sesion'

const form = ref({
  ftpUsuario: '',
  ftpClave: '',
  tipo: null,
  extension: null,
  fechaInicio: '',
  fechaFin: '',
  enriquecer: false,
})
const recordarCredenciales = ref(false)

const guardadas = sessionStorage.getItem(STORAGE_KEY)
if (guardadas) {
  try {
    const { usuario, clave } = JSON.parse(guardadas)
    form.value.ftpUsuario = usuario || ''
    form.value.ftpClave = clave || ''
    recordarCredenciales.value = true
  } catch {
    // ignorar sesión corrupta
  }
}

watch(
  [recordarCredenciales, () => form.value.ftpUsuario, () => form.value.ftpClave],
  () => {
    if (recordarCredenciales.value) {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ usuario: form.value.ftpUsuario, clave: form.value.ftpClave })
      )
    } else {
      sessionStorage.removeItem(STORAGE_KEY)
    }
  }
)

const tipoEsEnriquecible = computed(() => TIPOS_ENRIQUECIBLES.includes(form.value.tipo))
watch(
  () => form.value.tipo,
  () => {
    if (!tipoEsEnriquecible.value) form.value.enriquecer = false
  }
)

const formularioValido = computed(
  () =>
    form.value.ftpUsuario &&
    form.value.ftpClave &&
    form.value.tipo &&
    form.value.extension &&
    form.value.fechaInicio &&
    form.value.fechaFin
)

const jobId = ref(null)
const estado = ref(null)
const enProceso = computed(() => estado.value && ['descargando', 'unificando'].includes(estado.value.estado))
let polling = null

async function onDescargar() {
  estado.value = null
  const payload = {
    ftp_usuario: form.value.ftpUsuario,
    ftp_clave: form.value.ftpClave,
    tipo: form.value.tipo,
    extension: form.value.extension,
    fecha_inicio: form.value.fechaInicio,
    fecha_fin: form.value.fechaFin,
    enriquecer: form.value.enriquecer,
  }
  try {
    const { job_id: id } = await iniciarDescargaXM(payload)
    jobId.value = id
    estado.value = { estado: 'descargando', archivos_procesados: 0, archivos_totales: 0 }
    iniciarPolling()
  } catch (e) {
    estado.value = { estado: 'error', error_message: e.response?.data?.detail || 'No se pudo iniciar la descarga.' }
  }
}

function iniciarPolling() {
  detenerPolling()
  polling = setInterval(async () => {
    try {
      const data = await consultarEstadoXM(jobId.value)
      estado.value = data
      if (data.estado === 'listo' || data.estado === 'error') detenerPolling()
    } catch {
      detenerPolling()
    }
  }, 2000)
}

function detenerPolling() {
  if (polling) {
    clearInterval(polling)
    polling = null
  }
}

async function onDescargarArchivo(formato) {
  const blob = await descargarArchivoXM(jobId.value, formato)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = formato === 'xlsx' ? `${form.value.tipo}.xlsx` : `${form.value.tipo}.${form.value.extension}`
  a.click()
  URL.revokeObjectURL(url)
}

onBeforeUnmount(detenerPolling)
</script>

<style scoped>
.xm-input {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
}
.xm-input:focus {
  outline: none;
  border-color: #915bd8;
  box-shadow: 0 0 0 2px rgba(145, 91, 216, 0.15);
}
</style>
```

- [ ] **Step 3: Add the route**

In `src/router/index.js`, add this line inside the "── Finanzas ──" block, right after the `validador-mandatos` route:

```javascript
{ path: '/finanzas/descarga-xm',     name: 'DescargaXM',     component: () => import('@/views/Finanzas/DescargaXMView.vue'),        meta: { roles: ['admin', 'liquidaciones'] } },
```

- [ ] **Step 4: Add the sidebar entry**

In `src/components/AppSidebar.vue`, inside the `Finanzas` section's `items` array, add this entry right after the `Validador de Mandatos` entry:

```javascript
{ to: '/finanzas/descarga-xm', label: 'Descarga de XM', icon: 'pi pi-cloud-download', roles: ['admin', 'liquidaciones'] },
```

- [ ] **Step 5: Commit**

```bash
git add src/api/xm.js src/views/Finanzas/DescargaXMView.vue src/router/index.js src/components/AppSidebar.vue
git commit -m "feat(xm): add Descarga de XM tab in Finanzas"
```

---

## Task 12: Run the full backend test suite

**Files:** none (verification only)

- [ ] **Step 1: Run all new tests together**

Run: `pytest tests/test_xm_exceptions.py tests/test_xm_tipos.py tests/test_xm_plan_descarga.py tests/test_xm_fronteras.py tests/test_xm_unificador.py tests/test_xm_jobs.py tests/test_xm_downloader.py -v`
Expected: all PASS (31 tests)

- [ ] **Step 2: Run the full existing suite to check for regressions**

Run: `pytest -q`
Expected: no new failures introduced (pre-existing failures, if any, are unrelated to this feature)

---

## Task 13: End-to-end validation against the real XM FTP (mandatory before closing)

**Files:** none (uses the already-implemented modules directly; no throwaway script committed)

The user requires two real tests before this feature is considered done. Run
both from a Python shell in the backend repo, using real XM credentials
supplied by the user at run time (never hardcoded, never committed):

- [ ] **Step 1: Test (a) — private route, `dspcttos` for May 2026**

```python
from datetime import date
from app.services.xm.downloader import ejecutar_descarga
from app.services.xm.unificador import unificar, nombre_salida, exportar

ftp_params = {"host": "xmftps.xm.com.co", "usuario": "<usuario real>", "clave": "<clave real>"}
archivos, faltantes = ejecutar_descarga(ftp_params, "dspcttos", "txf", date(2026, 5, 1), date(2026, 5, 31))
print("archivos descargados:", len(archivos), "faltantes:", faltantes)

df = unificar("dspcttos", archivos)
print(df.shape)
print(df.head())

nombre_xlsx, nombre_txt = nombre_salida("dspcttos", "txf", date(2026, 5, 1), date(2026, 5, 31))
bytes_xlsx, bytes_txt = exportar(df)
open(nombre_xlsx, "wb").write(bytes_xlsx)
open(nombre_txt, "wb").write(bytes_txt)
print("guardado:", nombre_xlsx, nombre_txt)
```

Expected: connects via the private route, downloads ~31 files (fewer if
some days are missing — check `faltantes`), unifies into one DataFrame
with `FechaDocumento` as the first column, and writes both output files.

- [ ] **Step 2: Test (b) — public route with enrichment, `grip` or `arrpas` for one month**

```python
from datetime import date
from app.services.xm.downloader import ejecutar_descarga
from app.services.xm.fronteras import obtener_fronteras_mes
from app.services.xm.orquestador import _listar_fn, _descargar_fn
from app.services.xm.unificador import unificar, enriquecer, nombre_salida, exportar
from app.services.xm import tipos

ftp_params = {"host": "xmftps.xm.com.co", "usuario": "<usuario real>", "clave": "<clave real>"}
tipo, ext = "grip", "txf"
fecha_inicio, fecha_fin = date(2026, 5, 1), date(2026, 5, 31)

archivos, faltantes = ejecutar_descarga(ftp_params, tipo, ext, fecha_inicio, fecha_fin)
df = unificar(tipo, archivos)

tabla, mes_usado, archivo_usado = obtener_fronteras_mes(
    lambda d: _listar_fn(ftp_params, d), lambda d, n: _descargar_fn(ftp_params, d, n),
    fecha_inicio.year, fecha_inicio.month,
)
print("mes de fronteras usado:", mes_usado, "archivo:", archivo_usado)
print("3A44 en tabla:", tabla.get("3A44"))

df2, sin_match = enriquecer(df, tipo, {f"{fecha_inicio.year}-{fecha_inicio.month:02d}": tabla},
                             tipos.COLUMNA_CODIGO_ENRIQUECIMIENTO[tipo])
print(df2[df2["PLANTA"] == "3A44"][["FechaDocumento", "PLANTA", "Nombre de la Frontera", "Capacidad efectiva [MW]"]].head())
print("códigos sin match:", sorted(sin_match))
```

Expected: `mes_usado` equals the requested month (or falls back one month
with a clear print if the exact month has no snapshot yet), and rows with
`PLANTA == "3A44"` show `Nombre de la Frontera == "PLANTA SOLAR BAYUNCA I"`
(or whatever plant `3A44` maps to that month) with a non-null MW value —
matching the example confirmed earlier (`3A44 → Bayunca I, 3 MW`).

- [ ] **Step 3: Report both results to the user**

Summarize: file counts, any missing days, the `mes_usado`/`archivo_usado`
for fronteras, and the concrete before/after enrichment example — before
telling the user the feature is done.

---

## Task 14: Deploy

**Files:** none (git operations only)

- [ ] **Step 1: Pull latest on both repos before pushing (team works in parallel)**

```bash
cd unergy-operaciones-backend && git pull origin master
cd ../unergy-operaciones-frontend && git pull origin master
```

- [ ] **Step 2: Push backend (one commit history already built task-by-task above — just push)**

```bash
cd unergy-operaciones-backend && git push origin master
```

- [ ] **Step 3: Push frontend**

```bash
cd unergy-operaciones-frontend && git push origin master
```

- [ ] **Step 4: Confirm Railway deploy picked up the backend push**

Check the Railway deploy log/health endpoint after push:
`curl https://backend-production-63d8.up.railway.app/health/` (or the
project's actual health route) to confirm the new revision is live before
telling the user it's deployed.

---

## Self-Review Notes

- **Spec coverage:** every numbered section of the spec (FTP connection,
  type config, download, unification, enrichment source/column/multi-month
  rule, async job endpoints, frontend form/polling/errors, end-to-end
  validation) maps to a task above. The two corrections from the user's
  last two messages (cxcsb público, enrichment from the FTP monthly
  snapshot instead of the DB) are reflected in Tasks 2 and 4.
- **Deviation flagged:** `ftp_host` defaults to `"xmftps.xm.com.co"` in
  the request schema instead of always being a required form field — the
  hostname isn't a secret (it's the same for every XM user) and was
  confirmed real during this session, so the frontend only asks for
  usuario/clave. The field still exists in the API if a host override is
  ever needed.
- **Type consistency check:** `ejecutar_descarga` signature (Task 8) is
  called identically in Task 9's `orquestador.py` and in both Task 13
  scripts. `obtener_fronteras_mes(listar_fn, descargar_fn, anio, mes, ...)`
  signature (Task 4) matches its usage in Task 9 and Task 13. `enriquecer`,
  `unificar`, `nombre_salida`, `exportar` signatures (Task 5) match their
  call sites in Task 9's orchestrator and Task 13's validation scripts.
