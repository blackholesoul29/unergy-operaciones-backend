# Garantías · Plan 8 — Proyección real del mes siguiente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Reemplazar el proxy "mes siguiente ≈ mes actual completo" (que infla ~10×) por una proyección real de la posición de bolsa del mes siguiente, usando los contratos de ese mes y una tasa de generación reciente.

**Architecture:** Nueva función `calcular_balance_proyectado(db, year, month)` en `balance_energia.py` que corre `construir_tramos`/`agregar_balance` (ya puras) sobre los contratos del mes futuro (`get_plantas_contratos` SÍ los resuelve) con la generación proyectada = tasa diaria reciente por planta × días del tramo (todo `proyectado`, `real`=0). Luego `proyecciones` calcula la ventana "mes siguiente" desde ESE balance (campo `total`), no desde el mes actual.

**Tech Stack:** Python, pytest.

**Contexto (calibración vs XM):** El proxy actual da mes-siguiente 792 MWh vs ~80 de XM. XM proyecta M+1 con una ventana base de generación reciente (~30 días, ver hoja PERIODO BASE: Jul 9–Ago 7). La caída real viene sobre todo de que en el mes siguiente hay más energía contratada (menos va a bolsa) — y eso lo capturan los contratos de ese mes vía `construir_tramos`.

**NO tocar** el regulatorio (decisión de la usuaria: en revisión) ni el saldo manual.

**Helpers existentes:** en `balance_energia.py` ya están `construir_tramos`, `agregar_balance`, `_necesita_energia`. Desde `app.api.v1.cumplimiento`: `get_plantas_contratos`, `_unergy_token`, `_fetch_range`, `_mon_id`. `calcular_balance` importa esos helpers dentro de la función (líneas 422-425) — seguir ese patrón de import diferido para evitar ciclos.

Estructura de balance (de `agregar_balance`): `{"ungg": {"venta_bolsa": celda, "compra_bolsa_directa": celda, ...}, "ungc": {...}}`, celda = `{"real","proyectado","total","n_plantas"}`.

---

## File Structure

- **Modify** `app/services/balance_energia.py` — `_energia_proyectada` (pura) + `calcular_balance_proyectado`.
- **Modify** `app/services/garantias_proyecciones.py` — `proyecciones` llama el balance-fn para AMBOS meses; `_balance_fn` despacha mes futuro → proyectado.
- **Test** `tests/test_balance_energia.py` (añadir) y `tests/test_garantias_proyecciones.py` (ajustar).

---

### Task 1: `_energia_proyectada` (pura) — proyectar tramos con una tasa diaria

**Files:**
- Modify: `app/services/balance_energia.py`
- Test: `tests/test_balance_energia.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_balance_energia.py
from app.services.balance_energia import _energia_proyectada


def test_energia_proyectada_reparte_tasa_diaria_por_dias_de_tramo():
    # planta 10 con un tramo que necesita energía, del 1 al 10 (10 días), tasa 2 MWh/día
    plantas = {10: {"nombre": "X", "tramos": [
        {"ini": date(2026, 9, 1), "fin": date(2026, 9, 10),
         "pct_ppa": 0.0, "pct_dup": 0.0, "pct_uso": 0.0, "pct_venta_bolsa": 1.0,
         "piscina_venta": "ungg", "codigo_sic_bolsa": None},
    ]}}
    energia = _energia_proyectada(plantas, {10: 2.0}, date(2026, 9, 1), date(2026, 9, 30))
    real, proy = energia[10][0]
    assert real == 0.0            # mes futuro: nada real
    assert proy == 20.0           # 2 MWh/día × 10 días
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_balance_energia.py::test_energia_proyectada_reparte_tasa_diaria_por_dias_de_tramo -q`
Expected: FAIL — `ImportError: cannot import name '_energia_proyectada'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/services/balance_energia.py (cerca de agregar_balance)
def _energia_proyectada(plantas: dict, tasa_diaria: dict, first_day, last_day) -> dict:
    """Energía por tramo para un mes 100% futuro: (real=0, proyectado=tasa×días_tramo).
    `tasa_diaria` = {proyecto_id: MWh/día}. Tramos que no necesitan energía → (0,0)."""
    energia: dict[int, dict] = {}
    for pid, planta in plantas.items():
        tasa = tasa_diaria.get(pid)
        por_tramo = {}
        for idx, t in enumerate(planta["tramos"]):
            if tasa is None or not _necesita_energia(t):
                por_tramo[idx] = (0.0, 0.0)
                continue
            ini = max(t["ini"], first_day)
            fin = min(t["fin"], last_day)
            dias = (fin - ini).days + 1 if fin >= ini else 0
            por_tramo[idx] = (0.0, tasa * dias)
        energia[pid] = por_tramo
    return energia
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_balance_energia.py -q`
Expected: PASS (los previos + el nuevo)

- [ ] **Step 5: Commit**

```bash
git add app/services/balance_energia.py tests/test_balance_energia.py
git commit -m "feat(garantias): _energia_proyectada (proyecta tramos futuros con tasa diaria)"
```

---

### Task 2: `calcular_balance_proyectado` (integración; deps inyectables)

**Files:**
- Modify: `app/services/balance_energia.py`
- Test: `tests/test_balance_energia.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_balance_energia.py
from app.services.balance_energia import calcular_balance_proyectado


def test_calcular_balance_proyectado_usa_contratos_futuros_y_tasa(monkeypatch):
    import app.services.balance_energia as be
    # una planta al 100% en bolsa (sin contrato) todo septiembre
    data = {"venta": [], "bolsa": [{"id": 10, "nombre": "X", "pct_despacho": 1.0,
        "segmento_inicio": "2026-09-01", "segmento_fin": "2026-09-30",
        "es_duplicado": False, "uso_del_recurso": False, "codigo_sic": "700",
        "piscina": "libre"}]}
    monkeypatch.setattr(be, "_plantas_contratos_de", lambda db, y, m: data)
    monkeypatch.setattr(be, "_tasa_diaria_reciente", lambda db, plantas, hoy: {10: 3.0})

    out = calcular_balance_proyectado(db=None, year=2026, month=9, hoy=date(2026, 8, 21))
    # 30 días × 3 MWh = 90 MWh, todo venta en bolsa UNGG, proyectado
    vb = out["balance"]["ungg"]["venta_bolsa"]
    assert round(vb["total"], 1) == 90.0
    assert vb["real"] == 0.0
    assert out["periodo"]["es_proyeccion"] is True
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_balance_energia.py::test_calcular_balance_proyectado_usa_contratos_futuros_y_tasa -q`
Expected: FAIL — `ImportError: cannot import name 'calcular_balance_proyectado'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/services/balance_energia.py

# Ventana (días) hacia atrás para estimar la tasa diaria de generación del mes futuro.
_DIAS_TASA_REF = 30


def _plantas_contratos_de(db, year: int, month: int) -> dict:
    """Payload de plantas-contratos del mes (aislado para poder mockear en tests)."""
    from app.api.v1.cumplimiento import get_plantas_contratos
    return get_plantas_contratos(year=year, month=month, incluir_todos=False, db=db, _=None)


def _tasa_diaria_reciente(db, plantas: dict, hoy: date) -> dict:
    """{proyecto_id: MWh/día} desde la generación de los últimos _DIAS_TASA_REF días.
    Aislado para mockear en tests (hace red)."""
    from app.api.v1.cumplimiento import _fetch_range, _mon_id, _unergy_token
    from app.models.proyectos import Proyecto
    sub = {}
    if plantas:
        for p in db.query(Proyecto).filter(Proyecto.id.in_(list(plantas))).all():
            sp = _mon_id(p)
            if sp:
                sub[p.id] = sp
    if not sub:
        return {}
    try:
        token = _unergy_token()
    except Exception:
        logger.error("Auth Unergy failed in balance proyectado")
        return {}
    desde = hoy - timedelta(days=_DIAS_TASA_REF)
    hasta = hoy - timedelta(days=1)
    sps = sorted(set(sub.values()))
    por_sp: dict[str, float | None] = {}
    with ThreadPoolExecutor(max_workers=min(len(sps), 12)) as pool:
        for sp, res in pool.map(lambda s: (s, _fetch_range(token, s, desde, hasta)), sps):
            por_sp[sp] = res.get("mwh")
    dias = max(1, (hasta - desde).days + 1)
    return {pid: (por_sp.get(sp) / dias) for pid, sp in sub.items() if por_sp.get(sp) is not None}


def calcular_balance_proyectado(db, year: int, month: int, hoy: date | None = None) -> dict:
    """Balance de bolsa de un mes FUTURO: contratos de ese mes × tasa de generación
    reciente, todo proyectado. Misma forma de salida que `calcular_balance` (balance/periodo)."""
    hoy = hoy or date.today()
    total_dias = calendar.monthrange(year, month)[1]
    first_day = date(year, month, 1)
    last_day = date(year, month, total_dias)

    data = _plantas_contratos_de(db, year, month)
    derivado = construir_tramos(data, first_day, last_day)
    plantas = derivado["plantas"]
    tasa = _tasa_diaria_reciente(db, plantas, hoy)
    energia = _energia_proyectada(plantas, tasa, first_day, last_day)
    balance = agregar_balance(plantas, energia)
    return {
        "periodo": {"year": year, "month": month, "dias_mes": total_dias,
                    "es_proyeccion": True, "dias_tasa_ref": _DIAS_TASA_REF},
        "balance": balance,
    }
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_balance_energia.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/balance_energia.py tests/test_balance_energia.py
git commit -m "feat(garantias): calcular_balance_proyectado (mes futuro con contratos + tasa reciente)"
```

---

### Task 3: `proyecciones` usa balance por-mes; `_balance_fn` despacha el futuro

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones.py`

- [ ] **Step 1: Ajustar el test del orquestador**

Reemplazar `test_proyecciones_arma_dos_ventanas_con_deps_inyectadas` para que el fn devuelva un balance DISTINTO según el mes (así se prueba que la ventana siguiente NO sale del mes actual):

```python
def test_proyecciones_usa_balance_por_mes():
    bal_actual = _balance(venta={"p": 30.0, "t": 50.0}, compra_directa={"p": 4.0, "t": 6.0})
    bal_sig = _balance(venta={"p": 0.0, "t": 8.0}, compra_directa={"p": 0.0, "t": 1.0})

    def calcular_balance_fn(anio, mes):
        return {"balance": bal_actual if (anio, mes) == (2026, 8) else bal_sig, "periodo": {}}

    regs = {(2026, 7): 1_000_000.0, (2026, 8): 2_000_000.0}

    out = proyecciones(date(2026, 8, 14), calcular_balance_fn=calcular_balance_fn,
                       precio_fn=lambda: 900.0,
                       regulatorio_fn=lambda a, m: {"valor": regs[(a, m)], "anio": a, "mes": m, "fallback": False})
    v1, v2 = out["ventanas"]
    # resto mes actual: proyectado del balance ACTUAL = 30-4 = 26
    assert v1["neto_mwh"] == 26.0
    assert v1["garantia_total"] == 26.0 * 1000 * 900.0 + 1_000_000.0
    # mes siguiente: TOTAL del balance SIGUIENTE = 8-1 = 7 (NO del actual)
    assert (v2["anio"], v2["mes"]) == (2026, 9)
    assert v2["neto_mwh"] == 7.0
    assert v2["garantia_total"] == 7.0 * 1000 * 900.0 + 2_000_000.0
```

(Mantener `test_proyecciones_maneja_rollover_de_diciembre`; su fn ya ignora el mes, así que sigue pasando.)

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones.py::test_proyecciones_usa_balance_por_mes -q`
Expected: FAIL (hoy la ventana siguiente sale del balance del mes actual → neto 44, no 7)

- [ ] **Step 3: Implementación — `proyecciones` llama el fn por cada mes**

Reemplazar el cuerpo de `proyecciones` (en `app/services/garantias_proyecciones.py`) para pedir el balance de cada ventana a su propio mes:

```python
def proyecciones(hoy: date, *, calcular_balance_fn, precio_fn, regulatorio_fn,
                 plantas_nuevas: int = 0,
                 kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Las dos estimaciones al corte `hoy`. Cada ventana pide su balance a SU mes:
    resto del mes actual = campo 'proyectado' del mes actual; mes siguiente = campo
    'total' del balance (proyectado) del mes siguiente. Deps inyectadas."""
    anio_act, mes_act = hoy.year, hoy.month
    precio = precio_fn()
    a_prev, m_prev = _mes_anterior(anio_act, mes_act)
    a_sig, m_sig = _mes_siguiente(anio_act, mes_act)

    bal_actual = calcular_balance_fn(anio_act, mes_act)["balance"]
    bal_sig = calcular_balance_fn(a_sig, m_sig)["balance"]
    reg_actual = regulatorio_fn(a_prev, m_prev)
    reg_siguiente = regulatorio_fn(anio_act, mes_act)

    def ventana(clave, anio, mes, balance, campo, reg):
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
            ventana("resto_mes_actual", anio_act, mes_act, bal_actual, "proyectado", reg_actual),
            ventana("mes_siguiente", a_sig, m_sig, bal_sig, "total", reg_siguiente),
        ],
    }
```

- [ ] **Step 4: Actualizar `_balance_fn` para despachar el mes futuro a la proyección**

En `app/services/garantias_proyecciones.py`, reemplazar `_balance_fn`:

```python
def _balance_fn(db, anio: int, mes: int) -> dict:
    from datetime import date as _d
    from app.services.balance_energia import calcular_balance, calcular_balance_proyectado
    hoy = _d.today()
    if (anio, mes) > (hoy.year, hoy.month):
        return calcular_balance_proyectado(db, anio, mes)
    return calcular_balance(db, anio, mes)
```

(El resto de `construir_proyecciones_live` no cambia: sigue pasando `lambda a, m: _balance_fn(db, a, m)`.)

- [ ] **Step 5: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones.py tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (todos; el test de `construir_live` mockea `_balance_fn`, así que no llama a la API real)

- [ ] **Step 6: Suite completa + import**

Run: `python -m pytest -q` (esperar ~1020+ passed) y `python -c "import app.main"`.

- [ ] **Step 7: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones.py
git commit -m "feat(garantias): ventana mes siguiente desde su propio balance proyectado (no proxy)"
```

---

## Self-Review

- **Cobertura:** proxy reemplazado por proyección real del mes siguiente (contratos del mes + tasa reciente) ✓; resto-del-mes intacto ✓; regulatorio y saldo sin tocar ✓; deps inyectables → testeable sin red ✓.
- **Placeholders:** ninguno.
- **Consistencia:** `_energia_proyectada(plantas, tasa, first, last)->dict`; `calcular_balance_proyectado(db,y,m,hoy=None)->{periodo,balance}` (misma forma que `calcular_balance`); `proyecciones` ahora llama el fn 2 veces (mes actual y siguiente).

## Validación post-deploy (no se puede offline)
- Tras desplegar, en la vista, el "mes siguiente" debe caer de ~848M a un orden comparable a XM (Valor Garantía ~124M para SEPT). Comparar contra el archivo de XM. Si el número de energía sigue lejos, el siguiente ajuste es la ventana `_DIAS_TASA_REF` o alinear el precio con el PB de XM.
- El resto-del-mes no debería cambiar.
