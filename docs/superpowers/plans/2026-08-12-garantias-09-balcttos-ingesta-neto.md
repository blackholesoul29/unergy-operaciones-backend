# Garantías · Plan 9 — Ingesta del BalCttos + neto real (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Guardar el neto real de compras en bolsa del BalCttos por período (vía un endpoint que recibe el archivo) y usarlo como ancla del cálculo de garantía: real para lo transcurrido + proyección a esa tasa.

**Architecture:** Tabla `balcttos_neto` (neto real por período). Endpoint POST que recibe el `.xlsx` del BalCttos (lo empuja el agente local), lo parsea con `app/services/balcttos.py` (ya existe) y hace upsert. El motor `construir_proyecciones_live` usa ese neto: si hay BalCttos del mes, el neto de la ventana sale de `proyectar_neto_mwh` (tasa diaria real); si no, cae al comportamiento actual (balance). **Backend puro, NO toca frontend.**

**Tech Stack:** Python, SQLAlchemy, FastAPI, pytest (sqlite).

**Contexto (ya construido y verificado):** `app/services/balcttos.py` tiene `neto_compras_bolsa_de_bytes(bytes) -> {'total_mwh', 'por_dia': {fecha: mwh}}` y `proyectar_neto_mwh(neto_mwh, dias_con_dato, dias_objetivo) -> float`. Validado: el archivo real da 245.2 MWh en 19 días. El neto de compras es POSITIVO = compra neta (exposición positiva), que es justo lo que `calcular_garantia(neto_mwh, precio, reg)` espera (valor_energia = neto_mwh×1000×precio). Motor: `construir_proyecciones_live(db, hoy=None, *, plantas_nuevas, kwh_planta_nueva)` en `app/services/garantias_proyecciones.py`; router en `app/api/v1/garantias_proyecciones.py` (prefix `/garantias/proyecciones`, `api_router`). Harness de tests sqlite con `@compiles` (ver `tests/test_garantias_proyecciones_api.py`). El esquema de prod lo crea `create_all` al arrancar.

---

## File Structure

- **Modify** `app/models/garantias_proyecciones.py` — modelo `BalCttosNeto`.
- **Modify** `app/models/__init__.py` — registrar `BalCttosNeto`.
- **Modify** `app/services/garantias_proyecciones.py` — `guardar_balcttos_neto`, `balcttos_neto_de_periodo`, `neto_ventana_balcttos`, y usarlo en `construir_proyecciones_live`.
- **Modify** `app/api/v1/garantias_proyecciones.py` — endpoint `POST /balcttos` (multipart).
- **Test** `tests/test_garantias_proyecciones_api.py`.

---

### Task 1: Modelo `BalCttosNeto`

**Files:**
- Modify: `app/models/garantias_proyecciones.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.models.garantias_proyecciones import BalCttosNeto


def test_guardar_y_leer_balcttos_neto(db):
    db.add(BalCttosNeto(anio=2026, mes=8, dia_corte=19, neto_mwh=245.2))
    db.commit()
    r = db.query(BalCttosNeto).one()
    assert r.anio == 2026 and r.dia_corte == 19 and float(r.neto_mwh) == 245.2
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_guardar_y_leer_balcttos_neto -q`
Expected: FAIL — `ImportError: cannot import name 'BalCttosNeto'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/models/garantias_proyecciones.py (UniqueConstraint ya se importa)
class BalCttosNeto(Base):
    """Neto real de compras en bolsa del BalCttos de XM, por período (MWh). `dia_corte` =
    último día con dato real del archivo (para proyectar el resto a esa tasa diaria)."""
    __tablename__ = "balcttos_neto"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    dia_corte: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    neto_mwh: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("anio", "mes", name="uq_balcttos_neto_periodo"),)
```

En `app/models/__init__.py`, agregar `BalCttosNeto` al import existente de `garantias_proyecciones`:

```python
from app.models.garantias_proyecciones import GarantiaSnapshot, GarantiaPagado, BalCttosNeto  # noqa: F401
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/garantias_proyecciones.py app/models/__init__.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): modelo BalCttosNeto (neto real por periodo)"
```

---

### Task 2: Servicio — guardar/leer + neto de ventana desde BalCttos

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
from app.services.garantias_proyecciones import (
    guardar_balcttos_neto, balcttos_neto_de_periodo, neto_ventana_balcttos)


def test_guardar_balcttos_upsert(db):
    guardar_balcttos_neto(db, 2026, 8, dia_corte=19, neto_mwh=245.2)
    guardar_balcttos_neto(db, 2026, 8, dia_corte=20, neto_mwh=260.0)  # reemplaza
    r = balcttos_neto_de_periodo(db, 2026, 8)
    assert r["dia_corte"] == 20 and r["neto_mwh"] == 260.0


def test_neto_ventana_proyecta_a_tasa_diaria(db):
    guardar_balcttos_neto(db, 2026, 8, dia_corte=19, neto_mwh=245.2)
    # resto del mes actual: agosto tiene 31 días, quedan 31-19=12 -> tasa*12
    neto = neto_ventana_balcttos(db, 2026, 8, dias_objetivo=12)
    assert neto == 245.2 / 19 * 12
    # sin dato -> None
    assert neto_ventana_balcttos(db, 2026, 9, dias_objetivo=30) is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_guardar_balcttos_upsert -q`
Expected: FAIL — `ImportError: cannot import name 'guardar_balcttos_neto'`

- [ ] **Step 3: Implementación**

```python
# añadir en app/services/garantias_proyecciones.py
def guardar_balcttos_neto(db, anio: int, mes: int, *, dia_corte: int, neto_mwh: float):
    """Upsert del neto real del BalCttos para un período."""
    from app.models.garantias_proyecciones import BalCttosNeto
    fila = db.query(BalCttosNeto).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        fila = BalCttosNeto(anio=anio, mes=mes, dia_corte=dia_corte, neto_mwh=neto_mwh)
        db.add(fila)
    else:
        fila.dia_corte = dia_corte
        fila.neto_mwh = neto_mwh
    db.commit()
    return fila


def balcttos_neto_de_periodo(db, anio: int, mes: int) -> dict | None:
    """{'dia_corte', 'neto_mwh'} del BalCttos guardado, o None si no hay."""
    from app.models.garantias_proyecciones import BalCttosNeto
    fila = db.query(BalCttosNeto).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        return None
    return {"dia_corte": fila.dia_corte, "neto_mwh": float(fila.neto_mwh)}


def neto_ventana_balcttos(db, anio: int, mes: int, dias_objetivo: int) -> float | None:
    """Neto (MWh) de una ventana proyectando la tasa diaria real del BalCttos del período.
    None si no hay BalCttos guardado para ese (anio, mes)."""
    from app.services.balcttos import proyectar_neto_mwh
    dato = balcttos_neto_de_periodo(db, anio, mes)
    if dato is None or not dato["dia_corte"]:
        return None
    return proyectar_neto_mwh(dato["neto_mwh"], dato["dia_corte"], dias_objetivo)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): guardar/leer BalCttos neto + neto de ventana proyectado"
```

---

### Task 3: Usar el BalCttos en `construir_proyecciones_live` (con fallback)

**Files:**
- Modify: `app/services/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
import calendar
from datetime import date


def test_construir_live_usa_balcttos_si_hay(db, monkeypatch):
    # balance mockeado (para que NO se use si hay BalCttos)
    bal = {"balance": {"ungg": {
        "venta_bolsa": {"real": 0.0, "proyectado": 999.0, "total": 999.0, "n_plantas": 1},
        "compra_bolsa_directa": {"real": 0.0, "proyectado": 0.0, "total": 0.0, "n_plantas": 1},
    }}, "periodo": {}}
    monkeypatch.setattr(svc, "_balance_fn", lambda db_, a, m: bal)
    monkeypatch.setattr(svc, "_precio_fn", lambda: 900.0)
    monkeypatch.setattr(svc, "_regulatorio_fn", lambda a, m: {"valor": 0.0, "anio": a, "mes": m, "fallback": False})
    # BalCttos de agosto: 245.2 MWh en 19 días
    guardar_balcttos_neto(db, 2026, 8, dia_corte=19, neto_mwh=245.2)

    res = svc.construir_proyecciones_live(db, hoy=date(2026, 8, 21))
    v1 = res["ventanas"][0]  # resto mes actual
    # agosto: 31 días, corte 21 -> quedan 10 -> neto = 245.2/19*10 (NO el 999 del balance)
    quedan = calendar.monthrange(2026, 8)[1] - 21
    assert v1["neto_mwh"] == 245.2 / 19 * quedan
    assert v1["fuente_neto"] == "balcttos"
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_construir_live_usa_balcttos_si_hay -q`
Expected: FAIL (hoy usa el balance, neto 999)

- [ ] **Step 3: Implementación**

En `app/services/garantias_proyecciones.py`, `construir_proyecciones_live`: después de calcular `resultado = aplicar_pagado(proyecciones(...), ...)` (o donde arma el resultado), sobrescribir el neto de cada ventana con el del BalCttos si existe. Concretamente, reemplazar el cuerpo de `construir_proyecciones_live` por:

```python
def construir_proyecciones_live(db, hoy: date | None = None, *, plantas_nuevas: int = 0,
                                kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    import calendar
    if hoy is None:
        hoy = date.today()
    resultado = proyecciones(
        hoy,
        calcular_balance_fn=lambda a, m: _balance_fn(db, a, m),
        precio_fn=_precio_fn,
        regulatorio_fn=_regulatorio_fn,
        plantas_nuevas=plantas_nuevas, kwh_planta_nueva=kwh_planta_nueva,
    )
    precio = resultado.get("precio_bolsa_cop_kwh")
    for v in resultado["ventanas"]:
        # días de la ventana: resto del mes actual = días que faltan; mes siguiente = mes completo
        if v["clave"] == "resto_mes_actual":
            dias_obj = calendar.monthrange(v["anio"], v["mes"])[1] - hoy.day
        else:
            dias_obj = calendar.monthrange(v["anio"], v["mes"])[1]
        neto_bc = neto_ventana_balcttos(db, v["anio"], v["mes"], dias_obj)
        if neto_bc is None:
            v["fuente_neto"] = "proyeccion"
            continue
        # recomputar la garantía con el neto real del BalCttos (mantiene plantas nuevas y regulatorio)
        recal = calcular_garantia(neto_bc, precio or 0.0, v.get("costo_regulatorio") or 0.0,
                                  plantas_nuevas, kwh_planta_nueva)
        v.update(recal)
        v["neto_mwh"] = neto_bc
        v["fuente_neto"] = "balcttos"
    return aplicar_pagado(resultado, pagado_por_periodo(db))
```

(Ojo: si el `construir_proyecciones_live` actual ya termina en `return aplicar_pagado(...)`, ese `return` se mueve al final como arriba; el `aplicar_pagado` sigue siendo lo último.)

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py tests/test_garantias_proyecciones.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): usar el neto real del BalCttos en el calculo (con fallback a proyeccion)"
```

---

### Task 4: Endpoint POST `/balcttos` (recibe el archivo del agente)

**Files:**
- Modify: `app/api/v1/garantias_proyecciones.py`
- Test: `tests/test_garantias_proyecciones_api.py`

- [ ] **Step 1: Test que falla**

```python
# añadir en tests/test_garantias_proyecciones_api.py
def test_endpoint_ingesta_balcttos(db):
    # xlsx mínimo del BalCttos: 1 fila NETO DE COMPRAS EN BOLSA, 24 horas de 1000 kWh = 24 MWh
    import io, openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["FechaDocumento","CONCEPTO","MERCADO","CC","COMP","VEND","TD","TA"] + [f"HORA {h:02d}" for h in range(1,25)])
    ws.append(["2026-08-05","NETO DE COMPRAS EN BOLSA","NAL","C","X","UNGG","d","a"] + [1000.0]*24)
    buf = io.BytesIO(); wb.save(buf)
    out = api.ingerir_balcttos(anio=2026, mes=8, archivo_bytes=buf.getvalue(), db=db, _=USER)
    assert out["neto_mwh"] == 24.0 and out["dia_corte"] == 5
    # quedó guardado
    from app.services.garantias_proyecciones import balcttos_neto_de_periodo
    assert balcttos_neto_de_periodo(db, 2026, 8)["neto_mwh"] == 24.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py::test_endpoint_ingesta_balcttos -q`
Expected: FAIL — `AttributeError: ... 'ingerir_balcttos'`

- [ ] **Step 3: Implementación**

El test llama una función pura `ingerir_balcttos(anio, mes, archivo_bytes, db, _)` (sin `UploadFile`, para poder testear sin multipart). El endpoint HTTP la envuelve. Añadir en `app/api/v1/garantias_proyecciones.py`:

```python
from fastapi import File, UploadFile
from app.services.balcttos import neto_compras_bolsa_de_bytes
from app.services.garantias_proyecciones import guardar_balcttos_neto


def ingerir_balcttos(*, anio: int, mes: int, archivo_bytes: bytes, db: Session, _=None) -> dict:
    """Parsea el BalCttos y guarda su neto real. Lógica pura (testeable sin multipart)."""
    parsed = neto_compras_bolsa_de_bytes(archivo_bytes)
    dias = sorted(parsed["por_dia"])
    dia_corte = int(dias[-1][8:10]) if dias else 0
    guardar_balcttos_neto(db, anio, mes, dia_corte=dia_corte, neto_mwh=parsed["total_mwh"])
    return {"anio": anio, "mes": mes, "dia_corte": dia_corte, "neto_mwh": parsed["total_mwh"]}


@router.post("/balcttos")
async def post_balcttos(
    anio: int = Query(..., ge=2020, le=2050),
    mes: int = Query(..., ge=1, le=12),
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Recibe el BalCttos (lo empuja el agente local), parsea el NETO DE COMPRAS EN BOLSA
    y guarda el neto real del período."""
    contenido = await archivo.read()
    return ingerir_balcttos(anio=anio, mes=mes, archivo_bytes=contenido, db=db, _=_)
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_garantias_proyecciones_api.py -q`
Expected: PASS

- [ ] **Step 5: Import + suite completa**

Run: `python -c "import app.main"` (sin errores del router) y `python -m pytest -q` (todos).

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/garantias_proyecciones.py tests/test_garantias_proyecciones_api.py
git commit -m "feat(garantias): endpoint POST /balcttos (ingesta del neto real)"
```

---

## Self-Review

- **Cobertura:** tabla `balcttos_neto` ✓, upsert ✓, neto de ventana proyectado a la tasa real ✓, motor usa BalCttos con fallback a la proyección actual ✓, endpoint de ingesta ✓, `fuente_neto` marca de dónde salió cada ventana ✓. No toca frontend.
- **Placeholders:** ninguno.
- **Consistencia:** `guardar_balcttos_neto(db,a,m,*,dia_corte,neto_mwh)`, `balcttos_neto_de_periodo(db,a,m)->dict|None`, `neto_ventana_balcttos(db,a,m,dias_objetivo)->float|None`, `ingerir_balcttos(*,anio,mes,archivo_bytes,db,_)->dict`.

## Fuera de alcance (no ahora)
- **Agente local:** descargar el BalCttos del FTP y hacer POST a `/garantias/proyecciones/balcttos`. Va en `local_agent/servidor.py` (corre en la máquina de la usuaria, con las creds del FTP). Se prepara aparte.
- **Frontend:** mostrar `fuente_neto` / botón de carga — CONGELADO, no tocar.
