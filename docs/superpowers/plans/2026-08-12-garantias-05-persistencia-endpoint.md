# Garantías · Plan 5 — Persistencia (snapshot) + endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exponer las proyecciones de garantía por API y persistir el snapshot semanal.

**Architecture:** Modelo `GarantiaSnapshot` (SQLAlchemy, auto-creado por el `create_all` de arranque). Servicio que cablea las dependencias reales (`calcular_balance`, `precio_bolsa_prom_7d`, `costo_regulatorio_del_mes`) sobre el motor puro del Plan 4, y persiste. Router nuevo con GET (cálculo en vivo), POST (guardar snapshot) y GET historial. Tests con el harness sqlite del repo (invocando funciones del router directo, deps externas mockeadas).

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest (+ sqlite en memoria).

**Contexto verificado:** El esquema de prod lo provisiona `create_all` al arrancar (más `_PENDING_DDLS`), así que un modelo nuevo registrado en `app/models/__init__.py` se crea solo. El harness de tests usa `Base.metadata.create_all` sobre sqlite con `@compiles` para `BigInteger`→INTEGER y `JSONB`→TEXT, y llama las funciones del router directamente (auth está stubeada en `conftest.py`). Ver `tests/test_comercial_ofertas_api.py`. El motor puro `proyecciones(hoy, *, calcular_balance_fn, precio_fn, regulatorio_fn, ...)` del Plan 4 ya existe y está testeado.

---

## File Structure

- **Create** `app/models/garantias_proyecciones.py` — modelo `GarantiaSnapshot`.
- **Modify** `app/models/__init__.py` — registrar el modelo (una línea de import).
- **Modify** `app/services/garantias_proyecciones.py` — `filas_snapshot`, `construir_proyecciones_live`, `guardar_snapshot`, `historial_snapshots`.
- **Create** `app/api/v1/garantias_proyecciones.py` — router GET/POST/historial.
- **Modify** `app/api/v1/router.py` — incluir el router.
- **Test** `tests/test_garantias_proyecciones_api.py`.

---

### Task 1: Modelo `GarantiaSnapshot`

**Files:**
- Create: `app/models/garantias_proyecciones.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_garantias_proyecciones_api.py
"""Persistencia + endpoint de proyecciones de garantía. Harness sqlite; se invocan las
funciones del router directamente (auth stubeada en conftest). Deps externas mockeadas."""
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos)
from app.models.garantias_proyecciones import GarantiaSnapshot


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_guardar_y_leer_snapshot(db):
    fila = GarantiaSnapshot(
        fecha_corte=date(2026, 8, 14), clave="resto_mes_actual", anio=2026, mes=8,
        neto_mwh=26.0, precio_bolsa=900.0, valor_energia=23_400_000.0,
        valor_plantas_nuevas=0.0, costo_regulatorio=1_000_000.0,
        garantia_total=24_400_000.0, plantas_nuevas=0, kwh_planta_nueva=180.0,
        regulatorio_anio=2026, regulatorio_mes=7, regulatorio_fallback=False,
    )
    db.add(fila)
    db.commit()
    leido = db.query(GarantiaSnapshot).one()
    assert leido.clave == "resto_mes_actual"
    assert float(leido.garantia_total) == 24_400_000.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_guardar_y_leer_snapshot -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.garantias_proyecciones'`

- [ ] **Step 3: Implementación mínima**

```python
# app/models/garantias_proyecciones.py
"""Snapshot semanal de una estimación de garantía (una fila por ventana y corte)."""
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GarantiaSnapshot(Base):
    __tablename__ = "garantia_snapshot"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    fecha_corte: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    clave: Mapped[str] = mapped_column(String(30), nullable=False)  # resto_mes_actual | mes_siguiente
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    neto_mwh: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    precio_bolsa: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    valor_energia: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    valor_plantas_nuevas: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    costo_regulatorio: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    garantia_total: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    plantas_nuevas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    kwh_planta_nueva: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    regulatorio_anio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regulatorio_mes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regulatorio_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

En `app/models/__init__.py`, añadir (junto a los demás imports de modelos, respetando el estilo del archivo):

```python
from app.models.garantias_proyecciones import GarantiaSnapshot  # noqa: F401
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add app/models/garantias_proyecciones.py app/models/__init__.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): modelo GarantiaSnapshot (snapshot semanal)"
```

---

### Task 2: `filas_snapshot` (mapear resultado → filas)

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.services.garantias_proyecciones import filas_snapshot


def _resultado_demo():
    return {
        "fecha_corte": "2026-08-14", "precio_bolsa_cop_kwh": 900.0,
        "plantas_nuevas": 0, "kwh_planta_nueva": 180.0,
        "ventanas": [
            {"clave": "resto_mes_actual", "anio": 2026, "mes": 8, "neto_mwh": 26.0,
             "energia_neta_kwh": 26000.0, "valor_energia": 23_400_000.0,
             "valor_plantas_nuevas": 0.0, "costo_regulatorio": 1_000_000.0,
             "garantia_total": 24_400_000.0,
             "regulatorio_periodo": {"anio": 2026, "mes": 7, "fallback": False}},
            {"clave": "mes_siguiente", "anio": 2026, "mes": 9, "neto_mwh": 44.0,
             "energia_neta_kwh": 44000.0, "valor_energia": 39_600_000.0,
             "valor_plantas_nuevas": 0.0, "costo_regulatorio": 2_000_000.0,
             "garantia_total": 41_600_000.0,
             "regulatorio_periodo": {"anio": 2026, "mes": 8, "fallback": True}},
        ],
    }


def test_filas_snapshot_una_por_ventana(db):
    filas = filas_snapshot(_resultado_demo())
    assert len(filas) == 2
    f0 = filas[0]
    assert f0.clave == "resto_mes_actual"
    assert f0.fecha_corte == date(2026, 8, 14)
    assert float(f0.garantia_total) == 24_400_000.0
    assert f0.regulatorio_mes == 7 and f0.regulatorio_fallback is False
    assert filas[1].regulatorio_fallback is True
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_filas_snapshot_una_por_ventana -q`
Expected: FAIL — `ImportError: cannot import name 'filas_snapshot'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/garantias_proyecciones.py
# (import arriba, junto a los existentes)
from datetime import date, datetime  # 'date' ya está importado; añadir si falta


def filas_snapshot(resultado: dict) -> list:
    """Convierte la salida de `proyecciones` en filas GarantiaSnapshot (sin commitear)."""
    from app.models.garantias_proyecciones import GarantiaSnapshot
    corte = date.fromisoformat(resultado["fecha_corte"])
    precio = resultado.get("precio_bolsa_cop_kwh")
    filas = []
    for v in resultado["ventanas"]:
        reg = v.get("regulatorio_periodo") or {}
        filas.append(GarantiaSnapshot(
            fecha_corte=corte, clave=v["clave"], anio=v["anio"], mes=v["mes"],
            neto_mwh=v.get("neto_mwh"), precio_bolsa=precio,
            valor_energia=v.get("valor_energia"),
            valor_plantas_nuevas=v.get("valor_plantas_nuevas"),
            costo_regulatorio=v.get("costo_regulatorio"),
            garantia_total=v.get("garantia_total"),
            plantas_nuevas=resultado.get("plantas_nuevas", 0),
            kwh_planta_nueva=resultado.get("kwh_planta_nueva"),
            regulatorio_anio=reg.get("anio"), regulatorio_mes=reg.get("mes"),
            regulatorio_fallback=bool(reg.get("fallback")),
        ))
    return filas
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): filas_snapshot (resultado -> filas GarantiaSnapshot)"
```

---

### Task 3: Cableado en vivo + guardar/historial

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.services import garantias_proyecciones as svc


def test_construir_live_usa_deps_reales_mockeadas(db, monkeypatch):
    bal = {"balance": {"ungg": {
        "venta_bolsa": {"real": 0.0, "proyectado": 30.0, "total": 50.0, "n_plantas": 1},
        "compra_bolsa_directa": {"real": 0.0, "proyectado": 4.0, "total": 6.0, "n_plantas": 1},
    }}, "periodo": {}}
    monkeypatch.setattr(svc, "_balance_fn", lambda db_, a, m: bal)
    monkeypatch.setattr(svc, "_precio_fn", lambda: 900.0)
    monkeypatch.setattr(svc, "_regulatorio_fn",
                        lambda a, m: {"valor": 1_000_000.0, "anio": a, "mes": m, "fallback": False})

    res = svc.construir_proyecciones_live(db, hoy=date(2026, 8, 14))
    assert res["precio_bolsa_cop_kwh"] == 900.0
    assert res["ventanas"][0]["garantia_total"] == 26.0 * 1000 * 900.0 + 1_000_000.0


def test_guardar_y_historial(db):
    res = svc.construir_proyecciones_live.__wrapped__ if hasattr(svc.construir_proyecciones_live, "__wrapped__") else None
    # guardar dos snapshots de cortes distintos
    from app.services.garantias_proyecciones import filas_snapshot, guardar_snapshot, historial_snapshots
    r1 = _resultado_demo()
    guardar_snapshot(db, r1)
    hist = historial_snapshots(db)
    assert len(hist) == 2  # dos ventanas
    assert {h.clave for h in hist} == {"resto_mes_actual", "mes_siguiente"}
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_construir_live_usa_deps_reales_mockeadas -q`
Expected: FAIL — `AttributeError: ... has no attribute '_balance_fn'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/garantias_proyecciones.py
from datetime import timedelta


def _balance_fn(db, anio: int, mes: int) -> dict:
    from app.services.balance_energia import calcular_balance
    return calcular_balance(db, anio, mes)


def _precio_fn() -> float | None:
    from datetime import date as _d
    from app.services.simem_bolsa import precio_bolsa_prom_7d
    hoy = _d.today()
    inicio = hoy - timedelta(days=25)
    return precio_bolsa_prom_7d(inicio.isoformat(), hoy.isoformat())


def _regulatorio_fn(anio: int, mes: int) -> dict:
    from app.services.costo_regulatorio_drive import costo_regulatorio_del_mes
    return costo_regulatorio_del_mes(anio, mes)


def construir_proyecciones_live(db, hoy: date | None = None, *, plantas_nuevas: int = 0,
                                kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Calcula las dos ventanas cableando las dependencias reales (balance, precio SIMEM,
    costo regulatorio de Drive). Los `_*_fn` de módulo son mockeables en tests."""
    if hoy is None:
        hoy = date.today()
    return proyecciones(
        hoy,
        calcular_balance_fn=lambda a, m: _balance_fn(db, a, m),
        precio_fn=_precio_fn,
        regulatorio_fn=_regulatorio_fn,
        plantas_nuevas=plantas_nuevas, kwh_planta_nueva=kwh_planta_nueva,
    )


def guardar_snapshot(db, resultado: dict) -> list:
    """Persiste las filas del resultado y las devuelve."""
    filas = filas_snapshot(resultado)
    for f in filas:
        db.add(f)
    db.commit()
    return filas


def historial_snapshots(db, limite: int = 200) -> list:
    """Últimos snapshots, más recientes primero."""
    from app.models.garantias_proyecciones import GarantiaSnapshot
    return (db.query(GarantiaSnapshot)
            .order_by(GarantiaSnapshot.fecha_corte.desc(), GarantiaSnapshot.id.desc())
            .limit(limite).all())
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): cableado en vivo + guardar/historial de snapshots"
```

---

### Task 4: Router y registro

**Files:**
- Create: `app/api/v1/garantias_proyecciones.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
import types
from app.api.v1 import garantias_proyecciones as api

USER = types.SimpleNamespace(id=1)


def test_endpoint_get_calcula_en_vivo(db, monkeypatch):
    monkeypatch.setattr(api, "construir_proyecciones_live",
                        lambda db_, plantas_nuevas=0, kwh_planta_nueva=180.0: {"ok": True,
                            "ventanas": [], "fecha_corte": "2026-08-14"})
    out = api.get_proyecciones(plantas_nuevas=0, kwh_planta_nueva=180.0, db=db, _=USER)
    assert out["ok"] is True


def test_endpoint_post_guarda_snapshot(db, monkeypatch):
    monkeypatch.setattr(api, "construir_proyecciones_live",
                        lambda db_, plantas_nuevas=0, kwh_planta_nueva=180.0: _resultado_demo())
    out = api.post_snapshot(plantas_nuevas=0, kwh_planta_nueva=180.0, db=db, _=USER)
    assert out["guardadas"] == 2
    # y quedan en el historial
    assert len(api.get_historial(db=db, _=USER)["snapshots"]) == 2
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_endpoint_get_calcula_en_vivo -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.v1.garantias_proyecciones'`

- [ ] **Step 3: Implementación mínima**

```python
# app/api/v1/garantias_proyecciones.py
"""Proyecciones de garantía (precobro XM): cálculo en vivo + snapshot semanal."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services.garantias_proyecciones import (
    construir_proyecciones_live,
    guardar_snapshot,
    historial_snapshots,
)

router = APIRouter(prefix="/garantias/proyecciones", tags=["Garantías · Proyecciones"])


@router.get("")
def get_proyecciones(
    plantas_nuevas: int = Query(0, ge=0),
    kwh_planta_nueva: float = Query(180.0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Las dos estimaciones de garantía al corte de hoy (en vivo, sin guardar)."""
    return construir_proyecciones_live(db, plantas_nuevas=plantas_nuevas,
                                       kwh_planta_nueva=kwh_planta_nueva)


@router.post("/snapshot")
def post_snapshot(
    plantas_nuevas: int = Query(0, ge=0),
    kwh_planta_nueva: float = Query(180.0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Calcula y guarda el snapshot semanal (una fila por ventana)."""
    resultado = construir_proyecciones_live(db, plantas_nuevas=plantas_nuevas,
                                            kwh_planta_nueva=kwh_planta_nueva)
    filas = guardar_snapshot(db, resultado)
    return {"guardadas": len(filas), "fecha_corte": resultado.get("fecha_corte")}


@router.get("/historial")
def get_historial(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Snapshots guardados, más recientes primero."""
    filas = historial_snapshots(db)
    return {"snapshots": [
        {"id": f.id, "fecha_corte": f.fecha_corte.isoformat(), "clave": f.clave,
         "anio": f.anio, "mes": f.mes,
         "neto_mwh": float(f.neto_mwh) if f.neto_mwh is not None else None,
         "precio_bolsa": float(f.precio_bolsa) if f.precio_bolsa is not None else None,
         "garantia_total": float(f.garantia_total) if f.garantia_total is not None else None,
         "regulatorio_fallback": f.regulatorio_fallback}
        for f in filas
    ]}
```

En `app/api/v1/router.py`, registrar el router siguiendo el patrón de los demás (import + `include_router`):

```python
from app.api.v1 import garantias_proyecciones as garantias_proyecciones_api
# ... donde se incluyen los routers:
api_router.include_router(garantias_proyecciones_api.router)
```

(Usar el mismo nombre del objeto agregador que ya use `router.py` — `api_router` o el que sea.)

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Verificar que la app arranca (import del router OK)**

Run: `python -c "import app.main"`
Expected: sin errores de import (si falla por falta de variables de entorno de arranque ajenas al router, reportarlo; el objetivo es que el import del router no rompa).

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/garantias_proyecciones.py app/api/v1/router.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): endpoint GET/POST/historial de proyecciones"
```

---

## Self-Review

- **Cobertura del spec:** snapshot semanal persistido ✓, GET en vivo (dos ventanas) ✓, POST guarda ✓, historial ✓, cableado real de balance/SIMEM/regulatorio ✓, modelo auto-creado por create_all ✓, registro del router ✓.
- **Placeholders:** ninguno (el registro en router.py usa el nombre del agregador existente — el implementador debe verificarlo al abrir el archivo).
- **Consistencia de tipos:** `filas_snapshot(dict)->list[GarantiaSnapshot]`, `construir_proyecciones_live(db, hoy=None, *, plantas_nuevas, kwh_planta_nueva)->dict`, `guardar_snapshot(db, dict)->list`, `historial_snapshots(db, limite)->list`. Router: `get_proyecciones/post_snapshot/get_historial`.

## Notas de integración
- El GET real depende de la API de generación de Unergy (vía `calcular_balance`), de SIMEM y del Drive; en prod puede tardar/fallar por esas dependencias — el motor puro y la persistencia ya están cubiertos por tests. Verificar en vivo tras el deploy.
- Falta la sub-pestaña **Proyecciones** (frontend) — Plan 6.
