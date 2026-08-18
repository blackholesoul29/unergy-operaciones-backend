# Garantías · Plan 4 — Motor de cálculo de la garantía Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calcular las dos estimaciones de garantía (resto del mes actual + mes siguiente) combinando el balance de energía, el precio de bolsa SIMEM y el costo regulatorio.

**Architecture:** Módulo nuevo `app/services/garantias_proyecciones.py`. Fórmula y extracción del neto en funciones **puras**; el orquestador recibe sus dependencias (balance, precio, regulatorio) **inyectadas**, así que se testea sin BD ni red. **Sin tabla ni endpoint** todavía (Plan 5). Reutiliza `calcular_balance` (balance_energia), `precio_bolsa_prom_7d` (simem_bolsa, Plan 1) y `costo_regulatorio_del_mes` (Plan 3).

**Tech Stack:** Python, pytest.

**Fórmula (confirmada):** `garantía = (ventas − compras) × precio_bolsa_7d + costo_regulatorio`.
- `ventas − compras` = `venta_bolsa − compra_bolsa_directa` (UNGG). Compras = SOLO duplicados.
- Unidad: neto en MWh, precio en COP/kWh → ×1000 (MWh→kWh).
- Planta nueva: término aditivo `plantas_nuevas × kwh_planta_nueva(180) × precio` (override MVP editable; su signo/ubicación se validará contra XM real).

**Dos ventanas (decisión — ver spec):** `calcular_balance` devuelve ceros para meses futuros, así que ambas salen del balance del **mes actual**:
- Resto del mes actual → campo `proyectado`; regulatorio = mes anterior al actual.
- Mes siguiente completo → campo `total` (proxy "mes que viene ≈ este mes a cierre"); regulatorio = mes actual.

Estructura de `calcular_balance(...)["balance"]`: `ungg.{venta_bolsa, compra_bolsa_directa, ...}`, `ungc.venta_bolsa`; cada celda `{real, proyectado, total, n_plantas}`.

---

## File Structure

- **Create** `app/services/garantias_proyecciones.py` — fórmula pura, extracción de neto, orquestador con deps inyectables.
- **Test** `tests/test_garantias_proyecciones.py`.

Sin cambios en main.py, routers, modelos ni tablas.

---

### Task 1: Fórmula pura de la garantía

**Files:**
- Create: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_garantias_proyecciones.py
"""Motor de garantía: fórmula pura, extracción de neto y orquestación con deps inyectadas.
Sin BD, sin red, sin reloj."""
from app.services.garantias_proyecciones import calcular_garantia


def test_formula_base_valoriza_neto_en_kwh_mas_regulatorio():
    # neto 10 MWh = 10_000 kWh; precio 900 COP/kWh -> 9_000_000; + reg 1_000_000 = 10_000_000
    r = calcular_garantia(neto_mwh=10.0, precio_cop_kwh=900.0, costo_regulatorio=1_000_000.0)
    assert r["valor_energia"] == 9_000_000.0
    assert r["garantia_total"] == 10_000_000.0
    assert r["energia_neta_kwh"] == 10_000.0


def test_planta_nueva_suma_termino_editable():
    # 2 plantas nuevas × 180 kWh × 900 = 324_000, aditivo
    r = calcular_garantia(neto_mwh=0.0, precio_cop_kwh=900.0, costo_regulatorio=0.0,
                          plantas_nuevas=2, kwh_planta_nueva=180.0)
    assert r["valor_plantas_nuevas"] == 324_000.0
    assert r["garantia_total"] == 324_000.0


def test_neto_negativo_permitido():
    # si compras > ventas el neto es negativo; la fórmula lo respeta (se valida vs XM luego)
    r = calcular_garantia(neto_mwh=-5.0, precio_cop_kwh=1000.0, costo_regulatorio=0.0)
    assert r["valor_energia"] == -5_000_000.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.garantias_proyecciones'`

- [ ] **Step 3: Implementación mínima**

```python
# app/services/garantias_proyecciones.py
"""Motor de la garantía que XM precobra sobre compras/ventas en bolsa.

garantía = (ventas − compras) × precio_bolsa_7d + costo_regulatorio_mes_anterior
  ventas − compras = venta_bolsa − compra_bolsa_directa (UNGG); compras = solo duplicados.
  neto en MWh, precio en COP/kWh → ×1000.

Funciones puras (`calcular_garantia`, `neto_de_balance`) separadas de la orquestación
(`proyecciones`), que recibe sus dependencias inyectadas para testear sin BD ni red.
"""
from __future__ import annotations

MWH_A_KWH = 1000.0
KWH_PLANTA_NUEVA_DEFAULT = 180.0


def calcular_garantia(neto_mwh: float, precio_cop_kwh: float, costo_regulatorio: float,
                      plantas_nuevas: int = 0,
                      kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """(ventas−compras)×precio + regulatorio, con override aditivo de plantas nuevas.
    Devuelve el total y sus componentes (para el snapshot/desglose)."""
    energia_neta_kwh = neto_mwh * MWH_A_KWH
    valor_energia = energia_neta_kwh * precio_cop_kwh
    valor_plantas_nuevas = plantas_nuevas * kwh_planta_nueva * precio_cop_kwh
    return {
        "energia_neta_kwh": energia_neta_kwh,
        "valor_energia": valor_energia,
        "valor_plantas_nuevas": valor_plantas_nuevas,
        "costo_regulatorio": costo_regulatorio,
        "garantia_total": valor_energia + valor_plantas_nuevas + costo_regulatorio,
    }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones.py
git commit -m "feat(garantias): formula pura de la garantia (neto*precio + regulatorio)"
```

---

### Task 2: Extracción del neto desde el balance

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_garantias_proyecciones.py
from app.services.garantias_proyecciones import neto_de_balance


def _balance(venta, compra_directa):
    def celda(t): return {"real": 0.0, "proyectado": t["p"], "total": t["t"], "n_plantas": 1}
    return {
        "ungg": {
            "venta_bolsa": celda(venta),
            "compra_bolsa_directa": celda(compra_directa),
            "compra_bolsa_no_directa": celda({"p": 99.0, "t": 99.0}),  # NO debe influir
            "compra_bolsa_total": celda({"p": 99.0, "t": 99.0}),        # NO debe influir
            "neto": celda({"p": -1.0, "t": -1.0}),                       # NO debe influir
        },
        "ungc": {"venta_bolsa": celda({"p": 7.0, "t": 7.0})},            # NO debe influir
    }


def test_neto_proyectado_es_venta_menos_compra_directa():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})
    assert neto_de_balance(bal, "proyectado") == 26.0   # 30 - 4


def test_neto_total_usa_campo_total():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})
    assert neto_de_balance(bal, "total") == 44.0        # 50 - 6
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones.py::test_neto_proyectado_es_venta_menos_compra_directa -q`
Expected: FAIL — `ImportError: cannot import name 'neto_de_balance'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/garantias_proyecciones.py
def neto_de_balance(balance: dict, campo: str) -> float:
    """venta_bolsa − compra_bolsa_directa (UNGG) del campo dado ('proyectado' | 'total').
    'compras' = SOLO duplicados (compra_bolsa_directa), no el compra_bolsa_total."""
    ungg = balance["ungg"]
    venta = ungg["venta_bolsa"].get(campo, 0.0)
    compra_directa = ungg["compra_bolsa_directa"].get(campo, 0.0)
    return venta - compra_directa
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones.py
git commit -m "feat(garantias): extraccion del neto (venta - compra_directa) del balance"
```

---

### Task 3: Orquestador `proyecciones` (deps inyectadas)

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_garantias_proyecciones.py
from datetime import date
from app.services.garantias_proyecciones import proyecciones


def test_proyecciones_arma_dos_ventanas_con_deps_inyectadas():
    bal = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})

    def calcular_balance_fn(anio, mes):
        assert (anio, mes) == (2026, 8)   # siempre el mes actual
        return {"balance": bal, "periodo": {"fecha_corte": "2026-08-14"}}

    def precio_fn():
        return 900.0

    regs = {(2026, 7): 1_000_000.0, (2026, 8): 2_000_000.0}
    def regulatorio_fn(anio, mes):
        return {"valor": regs[(anio, mes)], "anio": anio, "mes": mes, "fallback": False}

    out = proyecciones(date(2026, 8, 14), calcular_balance_fn=calcular_balance_fn,
                       precio_fn=precio_fn, regulatorio_fn=regulatorio_fn)

    assert out["precio_bolsa_cop_kwh"] == 900.0
    v1, v2 = out["ventanas"]
    # Ventana 1: resto mes actual (proyectado 26 MWh) × 900 × 1000 + reg julio 1_000_000
    assert v1["clave"] == "resto_mes_actual"
    assert (v1["anio"], v1["mes"]) == (2026, 8)
    assert v1["garantia_total"] == 26.0 * 1000 * 900.0 + 1_000_000.0
    # Ventana 2: mes siguiente (total 44 MWh) × 900 × 1000 + reg agosto 2_000_000
    assert v2["clave"] == "mes_siguiente"
    assert (v2["anio"], v2["mes"]) == (2026, 9)
    assert v2["garantia_total"] == 44.0 * 1000 * 900.0 + 2_000_000.0


def test_proyecciones_maneja_rollover_de_diciembre():
    bal = _balance(venta={"p": 1.0, "t": 1.0}, compra_directa={"p": 0.0, "t": 0.0})
    calls = {}
    def regulatorio_fn(anio, mes):
        calls[(anio, mes)] = True
        return {"valor": 0.0, "anio": anio, "mes": mes, "fallback": False}
    out = proyecciones(date(2026, 12, 10),
                       calcular_balance_fn=lambda a, m: {"balance": bal, "periodo": {}},
                       precio_fn=lambda: 100.0, regulatorio_fn=regulatorio_fn)
    v1, v2 = out["ventanas"]
    assert (v1["anio"], v1["mes"]) == (2026, 12)
    assert (v2["anio"], v2["mes"]) == (2027, 1)          # rollover de año
    assert (2026, 11) in calls and (2026, 12) in calls   # regulatorio del mes anterior a cada ventana
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones.py::test_proyecciones_arma_dos_ventanas_con_deps_inyectadas -q`
Expected: FAIL — `ImportError: cannot import name 'proyecciones'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/garantias_proyecciones.py
from datetime import date


def _mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def proyecciones(hoy: date, *, calcular_balance_fn, precio_fn, regulatorio_fn,
                 plantas_nuevas: int = 0,
                 kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Las dos estimaciones de garantía al corte `hoy`. Todas las dependencias externas
    (balance, precio, regulatorio) se inyectan para poder testear sin BD ni red.

    Ambas ventanas salen del balance del MES ACTUAL (calcular_balance da ceros a futuro):
    resto del mes = campo 'proyectado'; mes siguiente = campo 'total' (proxy).
    """
    anio_act, mes_act = hoy.year, hoy.month
    balance = calcular_balance_fn(anio_act, mes_act)["balance"]
    precio = precio_fn()

    a_prev, m_prev = _mes_anterior(anio_act, mes_act)
    a_sig, m_sig = _mes_siguiente(anio_act, mes_act)
    reg_actual = regulatorio_fn(a_prev, m_prev)
    reg_siguiente = regulatorio_fn(anio_act, mes_act)

    def ventana(clave, anio, mes, campo, reg):
        neto = neto_de_balance(balance, campo)
        calc = calcular_garantia(neto, precio, (reg or {}).get("valor") or 0.0,
                                 plantas_nuevas, kwh_planta_nueva)
        return {"clave": clave, "anio": anio, "mes": mes, "neto_mwh": neto,
                "regulatorio_periodo": {"anio": (reg or {}).get("anio"),
                                        "mes": (reg or {}).get("mes"),
                                        "fallback": (reg or {}).get("fallback")},
                **calc}

    return {
        "fecha_corte": hoy.isoformat(),
        "precio_bolsa_cop_kwh": precio,
        "plantas_nuevas": plantas_nuevas,
        "kwh_planta_nueva": kwh_planta_nueva,
        "ventanas": [
            ventana("resto_mes_actual", anio_act, mes_act, "proyectado", reg_actual),
            ventana("mes_siguiente", a_sig, m_sig, "total", reg_siguiente),
        ],
    }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones.py
git commit -m "feat(garantias): orquestador de las dos ventanas de proyeccion (deps inyectadas)"
```

---

## Self-Review

- **Cobertura del spec:** fórmula `(venta−compra_directa)×precio×1000 + regulatorio` ✓, compras = solo duplicados ✓, MWh→kWh ✓, dos ventanas (proyectado / total-proxy) ✓, regulatorio anclado al mes anterior de cada ventana ✓, rollover de año ✓, override planta nueva aditivo editable ✓, deps inyectadas → testeable sin BD/red ✓, aislado (nadie lo importa; sin tabla/endpoint) ✓.
- **Placeholders:** ninguno.
- **Consistencia de tipos:** `calcular_garantia(...)->dict`, `neto_de_balance(dict,str)->float`, `proyecciones(date, *, fns...)->dict` con `ventanas: list[dict]`. Estable.

## Fuera de alcance (Plan 5 y 6)
- Tabla `garantia_snapshot` + persistencia del snapshot semanal.
- Router `garantias_proyecciones.py` (GET calcula en vivo cableando `calcular_balance`/`precio_bolsa_prom_7d`/`costo_regulatorio_del_mes`; POST guarda snapshot) + registro en `router.py`/`main.py`.
- Sub-pestaña **Proyecciones** (frontend).
