# Garantías · Plan 1 — Conector SIMEM (precio de bolsa) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Traer el precio de bolsa nacional (PB_Nal) desde la API pública de SIMEM y calcular el promedio de los últimos 7 días conocidos, tomando por día la versión de liquidación más alta disponible.

**Architecture:** Módulo nuevo y aislado `app/services/simem_bolsa.py`. Parseo/agregado en funciones **puras** (sin red); la llamada HTTP se hace con `httpx` y se testea con `httpx.MockTransport` (sin red real). **NO toca** `precios_bolsa_diario`, EVO, ni ningún endpoint existente. Es solo una librería consumible; ningún router lo importa todavía.

**Tech Stack:** Python, httpx, pytest. Convención del repo: funciones puras testeables sin BD/red/reloj (ver `tests/test_balance_energia.py`).

**Contexto de dominio (de la verificación en vivo 2026-08):** SIMEM `GET https://www.simem.co/backend-files/api/PublicData?startdate=&enddate=&datasetId=EC6945` devuelve filas horarias con columnas `CodigoVariable` (PB_Nal/PB_Int/PB_Tie), `FechaHora`, `UnidadMedida` (COP/kWh), `Version` (TX1, TX2, …), `Valor`. Los días recientes solo tienen TX1; los más viejos ya tienen TX2. Unidad de salida: **COP/kWh** (la conversión a MWh es responsabilidad del motor de cálculo, plan posterior).

---

## File Structure

- **Create** `app/services/simem_bolsa.py` — conector aislado: constantes, funciones puras de agregado, fetch httpx, orquestador.
- **Create** `tests/test_simem_bolsa.py` — tests de las funciones puras + fetch con MockTransport.

Sin cambios en `app/main.py`, routers, modelos ni tablas en este plan.

---

### Task 1: Ranking de versiones + agregado diario (funciones puras)

**Files:**
- Create: `app/services/simem_bolsa.py`
- Test: `tests/test_simem_bolsa.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_simem_bolsa.py
"""Conector SIMEM del precio de bolsa. Funciones puras: sin BD, sin red, sin reloj.
El fetch se prueba con httpx.MockTransport (sin red real)."""
from app.services.simem_bolsa import (
    _version_rank,
    promedio_diario_max_version,
    promedio_ultimos_n_dias,
)


def _rec(var, fechahora, version, valor):
    return {
        "CodigoVariable": var, "FechaHora": fechahora, "CodigoDuracion": "PT1H",
        "UnidadMedida": "COP/kWh", "Version": version, "Valor": valor,
    }


def test_version_rank_ordena_tx_numericas_y_finales():
    assert _version_rank("TX1") < _version_rank("TX2")
    assert _version_rank("TX2") < _version_rank("TXR")
    assert _version_rank("TXR") < _version_rank("TXF")
    # desconocida no rompe: cae al fondo
    assert _version_rank("???") < _version_rank("TX1")


def test_promedio_diario_toma_version_mas_alta_por_dia():
    # Día 01: TX1 (valor 100) y TX2 (valor 200) -> gana TX2 = 200
    # Día 02: solo TX1 (valor 300) -> 300
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Nal", "2026-08-01 01:00:00", "TX2", 200.0),
        _rec("PB_Nal", "2026-08-02 00:00:00", "TX1", 300.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 200.0, "2026-08-02": 300.0}


def test_promedio_diario_filtra_solo_pb_nal():
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Int", "2026-08-01 00:00:00", "TX1", 999.0),
        _rec("PB_Tie", "2026-08-01 00:00:00", "TX1", 888.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 100.0}


def test_promedio_diario_promedia_las_horas_del_dia():
    recs = [
        _rec("PB_Nal", "2026-08-01 00:00:00", "TX1", 100.0),
        _rec("PB_Nal", "2026-08-01 01:00:00", "TX1", 200.0),
    ]
    out = promedio_diario_max_version(recs)
    assert out == {"2026-08-01": 150.0}


def test_promedio_ultimos_n_dias_toma_los_mas_recientes():
    daily = {f"2026-08-0{d}": float(d) for d in range(1, 9)}  # 1..8
    # últimos 7 días conocidos = 02..08 -> promedio de 2,3,4,5,6,7,8 = 5.0
    assert promedio_ultimos_n_dias(daily, 7) == 5.0


def test_promedio_ultimos_n_dias_vacio_devuelve_none():
    assert promedio_ultimos_n_dias({}, 7) is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_simem_bolsa.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.simem_bolsa'`

- [ ] **Step 3: Implementación mínima**

```python
# app/services/simem_bolsa.py
"""Conector SIMEM para el precio de bolsa nacional (PB_Nal), AISLADO de garantías.

NO toca el pipeline EVO/`precios_bolsa_diario` existente. Fuente: API pública de SIMEM,
dataset EC6945 (precio de bolsa horario, COP/kWh). Por cada día se toma la `Version` más
alta disponible (TX1, TX2, …): los días recientes solo tienen TX1, los más viejos ya
tienen TX2; tomar el máximo por día da recencia + refinamiento a la vez.

Parseo/agregado en funciones puras (sin red); `fetch_records` hace la llamada httpx;
`precio_bolsa_prom_7d` orquesta. Salida en COP/kWh.
"""
from __future__ import annotations

from collections import defaultdict

SIMEM_URL = "https://www.simem.co/backend-files/api/PublicData"
DATASET_PRECIO_BOLSA = "EC6945"
VARIABLE_NACIONAL = "PB_Nal"

# Orden de definitividad de las liquidaciones XM (menor = más preliminar). Explícito
# para evitar el bug de orden lexicográfico ('TX10' < 'TX2'). Ajustable si aparecen más.
_ORDEN_VERSIONES = ["TX1", "TX2", "TX3", "TX4", "TX5", "TXR", "TXF"]


def _version_rank(version: str) -> int:
    """Rank de definitividad; versión desconocida cae al fondo (-1)."""
    try:
        return _ORDEN_VERSIONES.index(str(version).upper())
    except ValueError:
        return -1


def promedio_diario_max_version(records: list[dict], variable: str = VARIABLE_NACIONAL) -> dict[str, float]:
    """{records SIMEM} -> {'YYYY-MM-DD': precio_promedio_dia}.

    Filtra por CodigoVariable == variable. Por cada día usa SOLO las filas de la Version
    más alta presente ese día, y promedia sus horas.
    """
    # 1) mejor versión por día
    mejor: dict[str, int] = {}
    for r in records:
        if r.get("CodigoVariable") != variable:
            continue
        dia = str(r.get("FechaHora", ""))[:10]
        if not dia:
            continue
        rank = _version_rank(r.get("Version"))
        if dia not in mejor or rank > mejor[dia]:
            mejor[dia] = rank
    # 2) acumular horas de la mejor versión
    acc: dict[str, list[float]] = defaultdict(list)
    for r in records:
        if r.get("CodigoVariable") != variable:
            continue
        dia = str(r.get("FechaHora", ""))[:10]
        if not dia or _version_rank(r.get("Version")) != mejor.get(dia):
            continue
        try:
            acc[dia].append(float(r["Valor"]))
        except (TypeError, ValueError, KeyError):
            continue
    return {dia: sum(v) / len(v) for dia, v in acc.items() if v}


def promedio_ultimos_n_dias(daily: dict[str, float], n: int = 7) -> float | None:
    """Promedio de los últimos n días CONOCIDOS (por fecha, no calendario). None si vacío."""
    if not daily:
        return None
    ultimos = sorted(daily)[-n:]
    vals = [daily[d] for d in ultimos]
    return sum(vals) / len(vals)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_simem_bolsa.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/simem_bolsa.py tests/test_simem_bolsa.py
git commit -m "feat(garantias): agregado diario del precio de bolsa SIMEM (funciones puras)"
```

---

### Task 2: Fetch httpx contra SIMEM (testeado con MockTransport)

**Files:**
- Modify: `app/services/simem_bolsa.py`
- Test: `tests/test_simem_bolsa.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_simem_bolsa.py
import httpx
from app.services.simem_bolsa import fetch_records, DATASET_PRECIO_BOLSA


def test_fetch_records_arma_url_y_parsea_result_records():
    capturado = {}

    def handler(request):
        capturado["url"] = str(request.url)
        return httpx.Response(200, json={"result": {"records": [
            {"CodigoVariable": "PB_Nal", "FechaHora": "2026-08-01 00:00:00",
             "Version": "TX1", "Valor": 100.0},
        ]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    recs = fetch_records("2026-08-01", "2026-08-14", client=client)

    assert f"datasetId={DATASET_PRECIO_BOLSA}" in capturado["url"]
    assert "startdate=2026-08-01" in capturado["url"]
    assert "enddate=2026-08-14" in capturado["url"]
    assert len(recs) == 1 and recs[0]["Valor"] == 100.0


def test_fetch_records_sin_records_devuelve_lista_vacia():
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    assert fetch_records("2026-08-01", "2026-08-14", client=client) == []
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_simem_bolsa.py::test_fetch_records_arma_url_y_parsea_result_records -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_records'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/simem_bolsa.py
import httpx

_TIMEOUT = httpx.Timeout(10.0, read=40.0)


def fetch_records(start: str, end: str, *, dataset: str = DATASET_PRECIO_BOLSA,
                  client: httpx.Client | None = None) -> list[dict]:
    """GET a SIMEM PublicData. Devuelve result.records (o [] si no hay). `client`
    inyectable para tests (MockTransport)."""
    params = {"startdate": start, "enddate": end, "datasetId": dataset}
    propio = client is None
    cli = client or httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": "unergy-ops/1.0"})
    try:
        resp = cli.get(SIMEM_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if propio:
            cli.close()
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict) and isinstance(result.get("records"), list):
        return result["records"]
    if isinstance(data, dict) and isinstance(data.get("Records"), list):
        return data["Records"]
    return []
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_simem_bolsa.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/simem_bolsa.py tests/test_simem_bolsa.py
git commit -m "feat(garantias): fetch httpx del precio de bolsa SIMEM (MockTransport)"
```

---

### Task 3: Orquestador `precio_bolsa_prom_7d`

**Files:**
- Modify: `app/services/simem_bolsa.py`
- Test: `tests/test_simem_bolsa.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_simem_bolsa.py
from app.services.simem_bolsa import precio_bolsa_prom_7d


def test_precio_bolsa_prom_7d_integra_fetch_agregado_y_promedio():
    # 8 días, PB_Nal, una hora por día, valor = número de día. Dos versiones el día 1.
    recs = []
    for d in range(1, 9):
        recs.append({"CodigoVariable": "PB_Nal", "FechaHora": f"2026-08-0{d} 00:00:00",
                     "Version": "TX1", "Valor": float(d)})
    recs.append({"CodigoVariable": "PB_Nal", "FechaHora": "2026-08-01 00:00:00",
                 "Version": "TX2", "Valor": 100.0})  # gana TX2 el día 1, pero cae fuera de los últimos 7

    client = httpx.Client(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json={"result": {"records": recs}})))
    # últimos 7 días conocidos = 02..08 -> promedio 5.0
    val = precio_bolsa_prom_7d("2026-08-01", "2026-08-14", n_dias=7, client=client)
    assert val == 5.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_simem_bolsa.py::test_precio_bolsa_prom_7d_integra_fetch_agregado_y_promedio -q`
Expected: FAIL — `ImportError: cannot import name 'precio_bolsa_prom_7d'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/simem_bolsa.py
def precio_bolsa_prom_7d(start: str, end: str, *, n_dias: int = 7,
                         client: httpx.Client | None = None) -> float | None:
    """Orquesta: fetch SIMEM -> promedio diario (versión más alta por día) -> promedio de
    los últimos n días conocidos. Devuelve COP/kWh (o None si SIMEM no trae datos)."""
    records = fetch_records(start, end, client=client)
    daily = promedio_diario_max_version(records)
    return promedio_ultimos_n_dias(daily, n_dias)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_simem_bolsa.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Smoke test opcional contra SIMEM real (no en CI)**

Run (manual, requiere red):
```bash
python -c "from app.services.simem_bolsa import precio_bolsa_prom_7d; from datetime import date, timedelta; hoy=date(2026,8,14); print(precio_bolsa_prom_7d((hoy-timedelta(days=20)).isoformat(), hoy.isoformat()))"
```
Expected: un número ~900–1050 (COP/kWh). Si SIMEM está caído, devuelve None sin romper.

- [ ] **Step 6: Commit**

```bash
git add app/services/simem_bolsa.py tests/test_simem_bolsa.py
git commit -m "feat(garantias): orquestador precio_bolsa_prom_7d (SIMEM)"
```

---

## Self-Review

- **Cobertura del spec (parte precio bolsa):** dataset EC6945 ✓, PB_Nal ✓, versión más alta por día ✓, promedio últimos 7 días conocidos ✓, aislado de `precios_bolsa_diario`/EVO ✓ (módulo nuevo, nadie lo importa). Unidad COP/kWh documentada; conversión a MWh queda para el plan del motor de cálculo.
- **Placeholders:** ninguno; todo el código y los tests están completos.
- **Consistencia de tipos:** `fetch_records -> list[dict]`, `promedio_diario_max_version -> dict[str,float]`, `promedio_ultimos_n_dias -> float|None`, `precio_bolsa_prom_7d -> float|None`. Nombres estables entre tareas.

## Fuera de alcance de este plan (planes siguientes)
- Tabla cache `simem_precio_bolsa_diario` + persistencia (va con el motor/persistencia).
- Parser del `Cruce facturas` → `costo_regulatorio_mensual` (Plan 2).
- Motor de garantía (neto × precio + regulatorio), `garantia_snapshot`, endpoint (Plan 3).
- Sub-pestaña **Proyecciones** en frontend (Plan 4).
