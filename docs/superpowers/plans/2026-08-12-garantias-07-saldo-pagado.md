# Garantías · Plan 7 — Saldo (pagado vs necesidad) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Registrar cuánto se pagó/precobró de garantía por período y mostrar el saldo (pagado − garantía estimada) por ventana, para ver si hay saldo a favor o en contra.

**Architecture:** Tabla nueva `garantia_pagado` (valor por año-mes). Función pura que anexa `pagado` + `saldo` a cada ventana del resultado. Endpoints para fijar/leer el pagado. La vista muestra un input "Pagado" y el "Saldo" con color. Reutiliza el motor del Plan 4/5 sin cambiarlo.

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest (sqlite); Vue 3 + PrimeVue.

**Semántica MVP (a calibrar con datos reales):** `saldo = pagado − garantia_total` por ventana. Positivo = saldo a favor (se pagó de más); negativo = falta. El `pagado` se ingresa a mano por (año, mes); se compara contra la `garantia_total` de la ventana cuyo período es ese (año, mes).

**Contexto verificado (Planes 4-5):** `proyecciones(...)` devuelve `{..., "ventanas": [{clave, anio, mes, garantia_total, ...}]}`. `construir_proyecciones_live(db, hoy=None, *, plantas_nuevas, kwh_planta_nueva)` cablea las deps reales. Router `app/api/v1/garantias_proyecciones.py` (prefix `/garantias/proyecciones`), registrado en `api_router`. Modelo `GarantiaSnapshot` en `app/models/garantias_proyecciones.py`. Harness de tests sqlite con `@compiles` para BigInteger/JSONB (ver `tests/test_garantias_proyecciones_api.py`).

---

## File Structure

- **Modify** `app/models/garantias_proyecciones.py` — añadir modelo `GarantiaPagado`.
- **Modify** `app/models/__init__.py` — registrar `GarantiaPagado`.
- **Modify** `app/services/garantias_proyecciones.py` — `aplicar_pagado` (pura), `pagado_por_periodo`, `set_pagado`, y cablear el pagado en `construir_proyecciones_live`.
- **Modify** `app/api/v1/garantias_proyecciones.py` — endpoints GET/PUT `/pagado`; el GET principal ya devolverá pagado+saldo vía el service.
- **Test** `tests/test_garantias_proyecciones_api.py` (añadir).
- **Frontend Modify** `src/api/garantiasProyecciones.js` — `setPagado`.
- **Frontend Modify** `src/views/Garantias/Proyecciones/ProyeccionesView.vue` — input Pagado + Saldo.

---

### Task 1: Modelo `GarantiaPagado`

**Files:**
- Modify: `app/models/garantias_proyecciones.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.models.garantias_proyecciones import GarantiaPagado


def test_guardar_y_leer_pagado(db):
    db.add(GarantiaPagado(anio=2026, mes=8, valor=80_000_000.0))
    db.commit()
    leido = db.query(GarantiaPagado).one()
    assert leido.anio == 2026 and float(leido.valor) == 80_000_000.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_guardar_y_leer_pagado -q`
Expected: FAIL — `ImportError: cannot import name 'GarantiaPagado'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/models/garantias_proyecciones.py
from sqlalchemy import UniqueConstraint  # añadir al import de sqlalchemy si falta


class GarantiaPagado(Base):
    """Monto de garantía efectivamente precobrado/pagado por período (ingreso manual)."""
    __tablename__ = "garantia_pagado"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("anio", "mes", name="uq_garantia_pagado_periodo"),)
```

En `app/models/__init__.py`, junto al import de `GarantiaSnapshot`:

```python
from app.models.garantias_proyecciones import GarantiaSnapshot, GarantiaPagado  # noqa: F401
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (los previos + el nuevo)

- [ ] **Step 5: Commit**

```bash
git add app/models/garantias_proyecciones.py app/models/__init__.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): modelo GarantiaPagado (pagado por periodo)"
```

---

### Task 2: `aplicar_pagado` (pura) + saldo

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones.py
from app.services.garantias_proyecciones import aplicar_pagado


def test_aplicar_pagado_calcula_saldo_por_ventana():
    resultado = {"ventanas": [
        {"clave": "resto_mes_actual", "anio": 2026, "mes": 8, "garantia_total": 70.0},
        {"clave": "mes_siguiente", "anio": 2026, "mes": 9, "garantia_total": 100.0},
    ]}
    # pagado 80 para agosto, nada para septiembre
    out = aplicar_pagado(resultado, {(2026, 8): 80.0})
    v1, v2 = out["ventanas"]
    assert v1["pagado"] == 80.0 and v1["saldo"] == 10.0   # 80 - 70 = +10 (a favor)
    assert v2["pagado"] is None and v2["saldo"] is None    # sin pagado -> sin saldo
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones.py::test_aplicar_pagado_calcula_saldo_por_ventana -q`
Expected: FAIL — `ImportError: cannot import name 'aplicar_pagado'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/services/garantias_proyecciones.py
def aplicar_pagado(resultado: dict, pagado_por_periodo: dict) -> dict:
    """Anexa `pagado` y `saldo` (pagado − garantia_total) a cada ventana. `pagado` es
    None si no hay dato para ese (anio, mes) → `saldo` None. Muta y devuelve el resultado."""
    for v in resultado.get("ventanas", []):
        pagado = pagado_por_periodo.get((v["anio"], v["mes"]))
        v["pagado"] = pagado
        v["saldo"] = None if pagado is None else pagado - (v.get("garantia_total") or 0.0)
    return resultado
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones.py
git commit -m "feat(garantias): aplicar_pagado + saldo por ventana (puro)"
```

---

### Task 3: Cableado del pagado + set/lectura

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.services.garantias_proyecciones import pagado_por_periodo, set_pagado


def test_set_y_pagado_por_periodo(db):
    set_pagado(db, 2026, 8, 80_000_000.0)
    set_pagado(db, 2026, 8, 75_000_000.0)  # upsert: reemplaza
    d = pagado_por_periodo(db)
    assert d[(2026, 8)] == 75_000_000.0


def test_construir_live_incluye_saldo(db, monkeypatch):
    bal = {"balance": {"ungg": {
        "venta_bolsa": {"real": 0.0, "proyectado": 30.0, "total": 50.0, "n_plantas": 1},
        "compra_bolsa_directa": {"real": 0.0, "proyectado": 4.0, "total": 6.0, "n_plantas": 1},
    }}, "periodo": {}}
    monkeypatch.setattr(svc, "_balance_fn", lambda db_, a, m: bal)
    monkeypatch.setattr(svc, "_precio_fn", lambda: 900.0)
    monkeypatch.setattr(svc, "_regulatorio_fn",
                        lambda a, m: {"valor": 0.0, "anio": a, "mes": m, "fallback": False})
    # garantia resto mes actual = 26*1000*900 = 23_400_000; pagamos 24_000_000 -> saldo +600_000
    set_pagado(db, 2026, 8, 24_000_000.0)
    res = svc.construir_proyecciones_live(db, hoy=date(2026, 8, 14))
    v1 = res["ventanas"][0]
    assert v1["pagado"] == 24_000_000.0
    assert v1["saldo"] == 24_000_000.0 - 23_400_000.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_set_y_pagado_por_periodo -q`
Expected: FAIL — `ImportError: cannot import name 'pagado_por_periodo'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/services/garantias_proyecciones.py
def pagado_por_periodo(db) -> dict:
    """{(anio, mes): valor} de lo pagado registrado."""
    from app.models.garantias_proyecciones import GarantiaPagado
    return {(p.anio, p.mes): float(p.valor) for p in db.query(GarantiaPagado).all()}


def set_pagado(db, anio: int, mes: int, valor: float):
    """Upsert del pagado de un período."""
    from app.models.garantias_proyecciones import GarantiaPagado
    fila = db.query(GarantiaPagado).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        fila = GarantiaPagado(anio=anio, mes=mes, valor=valor)
        db.add(fila)
    else:
        fila.valor = valor
    db.commit()
    return fila
```

Y en `construir_proyecciones_live`, tras obtener el resultado de `proyecciones(...)`, anexar el pagado (añadir estas dos líneas antes del `return`, y cambiar el `return` para devolver el resultado ya con pagado):

```python
    resultado = proyecciones(
        hoy,
        calcular_balance_fn=lambda a, m: _balance_fn(db, a, m),
        precio_fn=_precio_fn,
        regulatorio_fn=_regulatorio_fn,
        plantas_nuevas=plantas_nuevas, kwh_planta_nueva=kwh_planta_nueva,
    )
    return aplicar_pagado(resultado, pagado_por_periodo(db))
```

(Reemplaza el `return proyecciones(...)` anterior por lo de arriba.)

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py tests/test_garantias_proyecciones.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): pagado por periodo cableado en el calculo en vivo"
```

---

### Task 4: Endpoints GET/PUT `/pagado`

**Files:**
- Modify: `app/api/v1/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
def test_endpoint_put_y_get_pagado(db):
    api.put_pagado(anio=2026, mes=8, valor=80_000_000.0, db=db, _=USER)
    out = api.get_pagado(db=db, _=USER)
    assert out["pagado"] == [{"anio": 2026, "mes": 8, "valor": 80_000_000.0}]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_endpoint_put_y_get_pagado -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'put_pagado'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/api/v1/garantias_proyecciones.py
from app.services.garantias_proyecciones import pagado_por_periodo, set_pagado


@router.get("/pagado")
def get_pagado(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Montos de garantía pagados por período."""
    d = pagado_por_periodo(db)
    return {"pagado": [{"anio": a, "mes": m, "valor": v}
                       for (a, m), v in sorted(d.items())]}


@router.put("/pagado")
def put_pagado(
    anio: int = Query(..., ge=2020, le=2050),
    mes: int = Query(..., ge=1, le=12),
    valor: float = Query(..., ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Fija (upsert) el monto pagado de un período."""
    set_pagado(db, anio, mes, valor)
    return {"anio": anio, "mes": mes, "valor": valor}
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Verificar import**

Run: `python -c "import app.main"`
Expected: sin errores relacionados al router.

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): endpoints GET/PUT del pagado por periodo"
```

---

### Task 5 (FRONTEND): input Pagado + Saldo en las tarjetas

**Files:**
- Modify: `src/api/garantiasProyecciones.js`
- Modify: `src/views/Garantias/Proyecciones/ProyeccionesView.vue`

- [ ] **Step 1: Añadir `setPagado` al módulo API**

```javascript
// añadir en src/api/garantiasProyecciones.js
export function setPagado({ anio, mes, valor }) {
  return api
    .put(`${BASE}/pagado`, null, { params: { anio, mes, valor } })
    .then((r) => r.data)
}
```

- [ ] **Step 2: En `ProyeccionesView.vue`, añadir el bloque Pagado/Saldo dentro de cada tarjeta**

En el `<script setup>`, importar `setPagado` (junto a los otros imports de la API) y añadir el handler:

```javascript
import { getProyecciones, guardarSnapshot, getHistorial, setPagado } from '@/api/garantiasProyecciones.js'

async function guardarPagado(v) {
  try {
    await setPagado({ anio: v.anio, mes: v.mes, valor: v.pagado || 0 })
    await cargar()  // recalcula el saldo
  } catch (e) {
    toast.add({ severity: 'error', summary: 'No se pudo guardar el pagado',
      detail: e.response?.data?.detail || e.message, life: 5000 })
  }
}
```

En el template, dentro del `<div v-for="v in data.ventanas">`, después del `<dl>` de desglose, añadir:

```html
        <div class="mt-3 pt-3 border-t" style="border-color:rgba(44,32,57,0.10)">
          <div class="flex items-center gap-2 mb-2">
            <label class="text-xs font-medium" style="color:#6b5a8a">Pagado</label>
            <InputNumber v-model="v.pagado" :min="0" mode="currency" currency="COP" locale="es-CO"
              :maxFractionDigits="0" size="small" style="width:11rem"
              @blur="guardarPagado(v)" />
          </div>
          <div v-if="v.saldo != null" class="text-sm font-semibold"
            :style="v.saldo >= 0 ? 'color:#059669' : 'color:#DC2626'">
            Saldo: {{ fmtCOP(v.saldo) }} {{ v.saldo >= 0 ? '· a favor' : '· falta' }}
          </div>
        </div>
```

- [ ] **Step 3: Verificar build**

Run: `npm run build`
Expected: `✓ built in ...` sin errores.

- [ ] **Step 4: Commit**

```bash
git add src/api/garantiasProyecciones.js src/views/Garantias/Proyecciones/ProyeccionesView.vue
git commit -m "feat(garantias): input Pagado + Saldo (a favor/falta) por ventana"
```

---

## Self-Review

- **Cobertura:** registrar pagado por período ✓, saldo = pagado − garantía por ventana ✓, None si no hay pagado ✓, endpoints GET/PUT ✓, UI con color a favor/falta ✓, modelo auto-creado por create_all ✓.
- **Placeholders:** ninguno.
- **Consistencia:** `aplicar_pagado(dict, dict)->dict`, `pagado_por_periodo(db)->dict{(a,m):float}`, `set_pagado(db,a,m,val)`, endpoints `get_pagado/put_pagado`. Frontend `setPagado({anio,mes,valor})`.

## Nota
- Semántica del saldo (pagado full-mes vs garantía de la ventana) a calibrar con un caso real de XM, igual que el signo del neto. La resta directa es el MVP acordado.
