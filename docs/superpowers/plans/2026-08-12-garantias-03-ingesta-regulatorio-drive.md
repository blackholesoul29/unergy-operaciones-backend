# Garantías · Plan 3 — Ingesta del costo regulatorio desde Drive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Obtener el costo regulatorio de un mes leyendo el archivo `Cruce facturas` desde el Drive de Estados de Resultados (ya conectado), con fallback al último período disponible.

**Architecture:** Reutiliza el plumbing existente y probado de `app/services/drive.py` (`listar_carpeta`, `er_folder_id`, `parse_nombre_er` con `TIPO_CRUCE`, `descargar_archivo`) y el parser del Plan 2 (`app/services/costo_regulatorio.py`). La selección de período/versión es una función **pura** (testeable sin Drive); la orquestación inyecta las funciones de Drive para testear sin red. **Sin tabla nueva** (YAGNI): se lee on-demand; el valor usado lo persistirá el snapshot del Plan 4.

**Tech Stack:** Python, openpyxl, pytest.

**Contexto verificado:** La carpeta de ER es plana (~1.700 archivos). `parse_nombre_er(nombre)` devuelve `{tipo, mes, anio, descripcion, version, es_copia}`. Los cruces se llaman `Cruce facturas {MES} {AÑO} {VERSION}.xlsx` → `tipo == TIPO_CRUCE` (`"cruce_facturas"`), `version` p. ej. `"txf"`, `"tx3"`…`"tx8"`. `txf` es la versión final; entre `txN` la mayor N es la más refinada. `descargar_archivo(file_id)` devuelve `bytes`.

---

## File Structure

- **Modify** `app/services/costo_regulatorio.py` — extraer el cálculo a `_costo_de_workbook(wb)` y añadir `costo_regulatorio_de_bytes(contenido)` (para el archivo bajado de Drive).
- **Create** `app/services/costo_regulatorio_drive.py` — ranking de versión, selección pura de período con fallback, y orquestador con dependencias de Drive inyectables.
- **Test** `tests/test_costo_regulatorio_drive.py`.

Sin cambios en `app/main.py`, routers ni modelos.

---

### Task 1: `costo_regulatorio_de_bytes` (parsear el xlsx bajado de Drive)

**Files:**
- Modify: `app/services/costo_regulatorio.py`
- Test: `tests/test_costo_regulatorio.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_costo_regulatorio.py
import io
import openpyxl
from app.services.costo_regulatorio import costo_regulatorio_de_bytes


def _xlsx_bytes_demo():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturas XM"
    for r in [
        ["Factura ASIC2 - GENERADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Fazni", 1, 0, 0, 999626.0],
        ["Valor total", 1, 0, 0, 999626.0],
    ]:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_costo_regulatorio_de_bytes_parsea_workbook_en_memoria():
    assert costo_regulatorio_de_bytes(_xlsx_bytes_demo()) == 999626.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_costo_regulatorio.py::test_costo_regulatorio_de_bytes_parsea_workbook_en_memoria -q`
Expected: FAIL — `ImportError: cannot import name 'costo_regulatorio_de_bytes'`

- [ ] **Step 3: Implementación mínima (refactor + nueva función)**

Reemplazar el cuerpo de `costo_regulatorio_de_archivo` para compartir la lógica de workbook y añadir la variante de bytes:

```python
# en app/services/costo_regulatorio.py, reemplazar la función costo_regulatorio_de_archivo
def _costo_de_workbook(wb) -> float:
    ws = wb[NOMBRE_HOJA] if NOMBRE_HOJA in wb.sheetnames else wb[wb.sheetnames[0]]
    return costo_regulatorio_de_facturas(extraer_facturas_xm(ws))


def costo_regulatorio_de_archivo(path: str) -> float:
    """Abre el xlsx de una ruta y devuelve su costo regulatorio."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    return _costo_de_workbook(wb)


def costo_regulatorio_de_bytes(contenido: bytes) -> float:
    """Igual que `_de_archivo` pero desde bytes (p. ej. un archivo bajado de Drive)."""
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True, read_only=True)
    return _costo_de_workbook(wb)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_costo_regulatorio.py -q`
Expected: PASS (9 passed — los 8 previos + el nuevo)

- [ ] **Step 5: Commit**

```bash
git add app/services/costo_regulatorio.py tests/test_costo_regulatorio.py
git commit -m "feat(garantias): costo_regulatorio_de_bytes (parseo desde bytes de Drive)"
```

---

### Task 2: Selección pura de período + versión con fallback

**Files:**
- Create: `app/services/costo_regulatorio_drive.py`
- Test: `tests/test_costo_regulatorio_drive.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_costo_regulatorio_drive.py
"""Ingesta del costo regulatorio desde el Drive de ER. La selección de período/versión
es pura; la orquestación inyecta las funciones de Drive (sin red)."""
from app.services.costo_regulatorio_drive import _rank_version, seleccionar_cruce


def _cruce(anio, mes, version, fid):
    return {"id": fid, "anio": anio, "mes": mes, "version": version}


def test_rank_version_txf_es_la_mas_alta_y_txN_por_numero():
    assert _rank_version("txf") > _rank_version("tx8")
    assert _rank_version("tx8") > _rank_version("tx3")
    assert _rank_version("???") < _rank_version("tx3")


def test_selecciona_periodo_exacto_prefiriendo_txf():
    cruces = [
        _cruce(2026, 7, "tx3", "a"),
        _cruce(2026, 7, "txf", "b"),
        _cruce(2026, 6, "txf", "c"),
    ]
    elegido = seleccionar_cruce(cruces, 2026, 7)
    assert elegido["id"] == "b"
    assert elegido["fallback"] is False


def test_fallback_al_ultimo_periodo_no_mayor_al_pedido():
    # Se pide agosto (aún no cerrado, no hay cruce) -> cae a julio, el último <= agosto.
    cruces = [
        _cruce(2026, 6, "txf", "jun"),
        _cruce(2026, 7, "txf", "jul"),
    ]
    elegido = seleccionar_cruce(cruces, 2026, 8)
    assert elegido["id"] == "jul"
    assert elegido["fallback"] is True
    assert (elegido["anio"], elegido["mes"]) == (2026, 7)


def test_sin_cruces_devuelve_none():
    assert seleccionar_cruce([], 2026, 8) is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_costo_regulatorio_drive.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.costo_regulatorio_drive'`

- [ ] **Step 3: Implementación mínima**

```python
# app/services/costo_regulatorio_drive.py
"""Ingesta del costo regulatorio del mes desde el Drive de Estados de Resultados.

Reutiliza el plumbing de `app/services/drive.py` (listar la carpeta de ER, parsear el
nombre, bajar el archivo) y el parser de `app/services/costo_regulatorio.py`. La
selección de período/versión es pura; `costo_regulatorio_del_mes` inyecta las funciones
de Drive para poder testear sin red.

Regla: para (año, mes) se toma el `Cruce facturas` de ESE período con la versión más
definitiva (txf > txN por número). Si no existe, fallback al último período disponible
que no sea posterior al pedido ("último disponible").
"""
from __future__ import annotations


def _rank_version(version) -> int:
    """txf es la final (más alta); txN vale N; desconocida cae al fondo."""
    v = str(version or "").strip().lower()
    if v == "txf":
        return 1000
    if v.startswith("tx"):
        try:
            return int(v[2:])
        except ValueError:
            return -1
    return -1


def seleccionar_cruce(cruces: list[dict], anio: int, mes: int) -> dict | None:
    """cruces = [{'id','anio','mes','version'}, ...] -> el cruce elegido con flag
    'fallback', o None si no hay ninguno.

    Elige el período == (anio, mes); si no hay, el mayor período <= (anio, mes). Dentro
    del período, la versión de mayor rank.
    """
    con_periodo = [c for c in cruces if c.get("anio") and c.get("mes")]
    if not con_periodo:
        return None
    objetivo = (anio, mes)
    exactos = [c for c in con_periodo if (c["anio"], c["mes"]) == objetivo]
    if exactos:
        elegido = max(exactos, key=lambda c: _rank_version(c["version"]))
        return {**elegido, "fallback": False}
    previos = [c for c in con_periodo if (c["anio"], c["mes"]) <= objetivo]
    if not previos:
        return None
    ultimo_periodo = max((c["anio"], c["mes"]) for c in previos)
    candidatos = [c for c in previos if (c["anio"], c["mes"]) == ultimo_periodo]
    elegido = max(candidatos, key=lambda c: _rank_version(c["version"]))
    return {**elegido, "fallback": True}
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_costo_regulatorio_drive.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/costo_regulatorio_drive.py tests/test_costo_regulatorio_drive.py
git commit -m "feat(garantias): seleccion pura de cruce por periodo+version con fallback"
```

---

### Task 3: Orquestador `costo_regulatorio_del_mes` (Drive inyectable)

**Files:**
- Modify: `app/services/costo_regulatorio_drive.py`
- Test: `tests/test_costo_regulatorio_drive.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_costo_regulatorio_drive.py
import io
import openpyxl
from app.services.costo_regulatorio_drive import costo_regulatorio_del_mes


def _xlsx_generador_bytes(valor):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Facturas XM"
    for r in [
        ["Factura ASIC9 - GENERADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Fazni", 1, 0, 0, float(valor)],
        ["Valor total", 1, 0, 0, float(valor)],
    ]:
        ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _listar_fake():
    # Simula lo que devuelve listar_carpeta ya "crudo": dicts con name/id/mimeType.
    return [
        {"id": "jul", "name": "Cruce facturas 7 2026 txf.xlsx", "mimeType": "x"},
        {"id": "jun", "name": "Cruce facturas 6 2026 txf.xlsx", "mimeType": "x"},
        {"id": "er1", "name": "Estado resultados Cliente Proyecto 7 2026.xlsx", "mimeType": "x"},
    ]


def test_del_mes_exacto_baja_y_parsea():
    bajados = {"jul": _xlsx_generador_bytes(500000), "jun": _xlsx_generador_bytes(111)}
    r = costo_regulatorio_del_mes(2026, 7, listar=_listar_fake, descargar=bajados.get)
    assert r["valor"] == 500000.0
    assert r["fallback"] is False
    assert (r["anio"], r["mes"]) == (2026, 7)


def test_del_mes_con_fallback_usa_ultimo_disponible():
    bajados = {"jul": _xlsx_generador_bytes(500000), "jun": _xlsx_generador_bytes(111)}
    r = costo_regulatorio_del_mes(2026, 8, listar=_listar_fake, descargar=bajados.get)
    assert r["valor"] == 500000.0    # julio, el último <= agosto
    assert r["fallback"] is True
    assert (r["anio"], r["mes"]) == (2026, 7)


def test_del_mes_sin_cruces_devuelve_none_valor():
    r = costo_regulatorio_del_mes(2026, 8, listar=lambda: [], descargar=lambda i: b"")
    assert r["valor"] is None
    assert r["cruce"] is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_costo_regulatorio_drive.py::test_del_mes_exacto_baja_y_parsea -q`
Expected: FAIL — `ImportError: cannot import name 'costo_regulatorio_del_mes'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/costo_regulatorio_drive.py
from app.services.costo_regulatorio import costo_regulatorio_de_bytes


def _cruces_de_carpeta(listar) -> list[dict]:
    """Lista la carpeta de ER y deja solo los cruces, con período/versión parseados."""
    from app.services.drive import TIPO_CRUCE, parse_nombre_er
    cruces = []
    for f in listar():
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            continue
        info = parse_nombre_er(f.get("name", ""))
        if info["tipo"] == TIPO_CRUCE:
            cruces.append({"id": f.get("id"), "anio": info["anio"],
                           "mes": info["mes"], "version": info["version"]})
    return cruces


def costo_regulatorio_del_mes(anio: int, mes: int, *, listar=None, descargar=None) -> dict:
    """Costo regulatorio de (anio, mes) desde el Drive de ER, con fallback al último
    período disponible. Devuelve {'valor', 'anio', 'mes', 'version', 'fallback', 'cruce'}.
    `valor` es None si no hay ningún cruce. `listar`/`descargar` son inyectables (tests);
    por defecto usan `app.services.drive`.
    """
    if listar is None or descargar is None:
        from app.services.drive import descargar_archivo, er_folder_id, listar_carpeta
        if listar is None:
            listar = lambda: listar_carpeta(er_folder_id())
        if descargar is None:
            descargar = descargar_archivo

    cruces = _cruces_de_carpeta(listar)
    elegido = seleccionar_cruce(cruces, anio, mes)
    if elegido is None:
        return {"valor": None, "anio": anio, "mes": mes,
                "version": None, "fallback": False, "cruce": None}
    contenido = descargar(elegido["id"])
    valor = costo_regulatorio_de_bytes(contenido)
    return {
        "valor": valor,
        "anio": elegido["anio"],
        "mes": elegido["mes"],
        "version": elegido["version"],
        "fallback": elegido["fallback"],
        "cruce": elegido,
    }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_costo_regulatorio_drive.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Smoke test opcional contra el Drive real (no en CI)**

Run (manual, requiere `GOOGLE_SERVICE_ACCOUNT_JSON` en el entorno):
```bash
python -c "from app.services.costo_regulatorio_drive import costo_regulatorio_del_mes; print(costo_regulatorio_del_mes(2026,7))"
```
Expected: `{'valor': 67191598.0, 'anio': 2026, 'mes': 7, 'version': 'txf', 'fallback': False, ...}`. Si falta la credencial de Drive, el import de `drive` fallará al ejecutar — es esperado fuera del entorno de prod; NO es un fallo del código.

- [ ] **Step 6: Commit**

```bash
git add app/services/costo_regulatorio_drive.py tests/test_costo_regulatorio_drive.py
git commit -m "feat(garantias): orquestador costo_regulatorio_del_mes (Drive inyectable)"
```

---

## Self-Review

- **Cobertura del spec:** leer el `Cruce facturas` del Drive de ER por (año, mes) ✓, reusar `drive.py` sin duplicar ✓, versión más definitiva (txf > txN) ✓, fallback al último período disponible ✓, sin tabla nueva ✓, aislado (nuevo módulo + método nuevo en `costo_regulatorio.py`; no toca main/routers) ✓.
- **Placeholders:** ninguno.
- **Consistencia de tipos:** `_rank_version(x)->int`, `seleccionar_cruce(list,int,int)->dict|None` (con clave `fallback`), `costo_regulatorio_del_mes(int,int)->dict` con claves `{valor, anio, mes, version, fallback, cruce}`. `costo_regulatorio_de_bytes(bytes)->float`. Estable.

## Fuera de alcance de este plan
- Motor de garantía (usa `costo_regulatorio_del_mes` + `balance_energia` + SIMEM), `garantia_snapshot`, endpoint (Plan 4 — requiere mini-diseño del enganche con `balance_energia`).
- Sub-pestaña Proyecciones (Plan 5).
