# Vínculo Starlink ↔ Minigranja — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir el vínculo sitio Starlink → proyecto (minigranja) por período y que el Excel consolidado lo lea por relación de BD, en vez de re-resolver un string en memoria.

**Architecture:** Se añaden dos tablas (`starlink_mapeo_sitio`, `starlink_factura_linea`) y un resolver puro. Al guardar una factura (PUT) el backend resuelve cada sitio del `agrupado` a `proyecto_id` usando el catálogo de mapeos y (re)genera las líneas. El GET devuelve las líneas ya resueltas con `nombre_comercial`; el frontend las consume para `public_services`. DDL vía `_PENDING_DDLS` y backfill vía función de startup (Alembic NO es el camino de deploy en este repo).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column), PostgreSQL, pytest (tests de funciones puras, sin BD), Vue 3 + PrimeVue, XLSX (SheetJS).

**Spec:** `docs/superpowers/specs/2026-07-09-starlink-minigranja-vinculo-design.md`

---

## File Structure

**Backend (`unergy-operaciones-backend`):**
- Create `app/services/starlink_resolver.py` — resolución pura sitio → proyecto (única unidad con TDD).
- Create `tests/test_starlink_resolver.py` — tests puros del resolver.
- Modify `app/models/starlink.py` — añadir `StarlinkMapeoSitio` y `StarlinkFacturaLinea`.
- Modify `app/models/__init__.py` — registrar los dos modelos nuevos.
- Modify `app/main.py` — DDL en `_PENDING_DDLS` + función de startup `_run_starlink_mapeo_seed()`.
- Modify `app/api/v1/starlink.py` — helper `_regenerar_lineas`, extender PUT/GET, endpoints de mapeo.

**Frontend (`unergy-operaciones-frontend-master`):**
- Modify `src/views/Finanzas/costosExcelExport.js` — consumir `lineas` resueltas para `public_services`.
- Modify `src/views/Finanzas/StarlinkPDF.vue` — columna "Minigranja" + asignación de sitios sin mapear.

**Nota de rutas:** todos los comandos `pytest`/`git` del backend se corren desde `unergy-operaciones-backend/`. Los del frontend desde `unergy-operaciones-frontend-master/`.

---

## Task 1: Resolver puro sitio → proyecto (TDD)

**Files:**
- Create: `app/services/starlink_resolver.py`
- Test: `tests/test_starlink_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_starlink_resolver.py`:

```python
"""Tests del resolver puro sitio Starlink → proyecto (sin DB)."""
from app.services.starlink_resolver import normalizar_sitio, resolver_lineas


def test_normalizar_quita_acentos_y_colapsa():
    assert normalizar_sitio("Cañahuate") == "CANAHUATE"
    assert normalizar_sitio("  el   molino ") == "EL MOLINO"
    assert normalizar_sitio(None) == ""


def test_resuelve_por_nombre_normalizado():
    agrupado = [{"descripcion": "Gandalf", "sin_iva": 100.0, "iva": 19.0, "monto_total": 119.0}]
    mapeos = [{"patron": "GANDALF", "proyecto_id": 7}]
    lineas = resolver_lineas(agrupado, mapeos)
    assert len(lineas) == 1
    assert lineas[0]["proyecto_id"] == 7
    assert lineas[0]["sin_iva"] == 100.0
    assert lineas[0]["descripcion"] == "Gandalf"


def test_sin_match_proyecto_none():
    agrupado = [{"descripcion": "NESTLE", "sin_iva": 50.0, "iva": 9.5, "monto_total": 59.5}]
    lineas = resolver_lineas(agrupado, [])
    assert lineas[0]["proyecto_id"] is None


def test_match_ignora_acentos_del_patron():
    agrupado = [{"descripcion": "CAÑAHUATE", "sin_iva": 10.0, "iva": 1.9, "monto_total": 11.9}]
    mapeos = [{"patron": "Cañahuate", "proyecto_id": 3}]
    assert resolver_lineas(agrupado, mapeos)[0]["proyecto_id"] == 3


def test_una_linea_por_entrada_del_agrupado():
    agrupado = [
        {"descripcion": "Gandalf", "sin_iva": 1, "iva": 0, "monto_total": 1},
        {"descripcion": "Cañahuate", "sin_iva": 2, "iva": 0, "monto_total": 2},
    ]
    lineas = resolver_lineas(agrupado, [{"patron": "GANDALF", "proyecto_id": 7}])
    assert len(lineas) == 2
    assert [l["proyecto_id"] for l in lineas] == [7, None]


def test_campos_none_se_normalizan_a_cero():
    agrupado = [{"descripcion": "Baraya", "sin_iva": None, "iva": None, "monto_total": None}]
    linea = resolver_lineas(agrupado, [])[0]
    assert linea["sin_iva"] == 0.0 and linea["iva"] == 0.0 and linea["monto_total"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_starlink_resolver.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.starlink_resolver'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/services/starlink_resolver.py`:

```python
"""Resolución pura sitio Starlink → proyecto (minigranja).

Sin dependencias de DB ni FastAPI. Recibe el `agrupado` de una factura (ya con los
splits aplicados por el parser en _construir_agrupado) y el catálogo de mapeos, y
devuelve una línea por sitio con su proyecto_id resuelto (o None si no está mapeado).
El match es por nombre normalizado — espejo de normName() de costosExcelExport.js.
"""
from __future__ import annotations
import unicodedata


def normalizar_sitio(nombre: str) -> str:
    """Mayúsculas, sin acentos, espacios colapsados."""
    s = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def resolver_lineas(agrupado: list[dict], mapeos: list[dict]) -> list[dict]:
    """
    agrupado: entradas con 'descripcion', 'sin_iva', 'iva', 'monto_total'.
    mapeos:   entradas con 'patron' (texto) y 'proyecto_id' (int | None).
    Devuelve una línea por entrada del agrupado:
      {'descripcion', 'proyecto_id', 'sin_iva', 'iva', 'monto_total'}.
    Sin match → proyecto_id = None.
    """
    indice = {normalizar_sitio(m["patron"]): m.get("proyecto_id") for m in mapeos}
    lineas: list[dict] = []
    for it in agrupado:
        desc = it.get("descripcion", "")
        lineas.append({
            "descripcion": desc,
            "proyecto_id": indice.get(normalizar_sitio(desc)),
            "sin_iva":     float(it.get("sin_iva") or 0),
            "iva":         float(it.get("iva") or 0),
            "monto_total": float(it.get("monto_total") or 0),
        })
    return lineas
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_starlink_resolver.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/starlink_resolver.py tests/test_starlink_resolver.py
git commit -m "feat(starlink): resolver puro sitio -> proyecto con tests"
```

---

## Task 2: Modelos `StarlinkMapeoSitio` y `StarlinkFacturaLinea`

**Files:**
- Modify: `app/models/starlink.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_starlink_modelos.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_starlink_modelos.py` (smoke test de metadatos del modelo, sin BD):

```python
"""Smoke test: los modelos nuevos existen, tienen tabla y columnas esperadas."""
from app.models.starlink import StarlinkMapeoSitio, StarlinkFacturaLinea


def test_mapeo_sitio_tabla_y_columnas():
    assert StarlinkMapeoSitio.__tablename__ == "starlink_mapeo_sitio"
    cols = set(StarlinkMapeoSitio.__table__.columns.keys())
    assert {"id", "patron", "proyecto_id", "activo"} <= cols


def test_factura_linea_tabla_y_columnas():
    assert StarlinkFacturaLinea.__tablename__ == "starlink_factura_linea"
    cols = set(StarlinkFacturaLinea.__table__.columns.keys())
    assert {"id", "factura_id", "proyecto_id", "descripcion",
            "sin_iva", "iva", "monto_total"} <= cols


def test_factura_linea_fk_a_facturas_con_cascade():
    fk = list(StarlinkFacturaLinea.__table__.c.factura_id.foreign_keys)[0]
    assert fk.column.table.name == "starlink_facturas"
    assert fk.ondelete == "CASCADE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_starlink_modelos.py -v`
Expected: FAIL con `ImportError: cannot import name 'StarlinkMapeoSitio'`.

- [ ] **Step 3: Write minimal implementation**

En `app/models/starlink.py`, reemplazar la línea de imports de SQLAlchemy y añadir los dos modelos al final.

Cambiar la línea de import (actual línea 4):

```python
from sqlalchemy import BigInteger, String, Text, Numeric, DateTime, Boolean, ForeignKey
```

Añadir al final del archivo:

```python
class StarlinkMapeoSitio(Base):
    """Mapeo persistido y editable: nombre de sitio del PDF → proyecto (minigranja).
    Reemplaza el hardcode STARLINK_TO_PANEL del frontend. Match 1:1 por nombre
    normalizado (los splits ya los aplica el parser antes de agrupar)."""
    __tablename__ = "starlink_mapeo_sitio"

    id:          Mapped[int] = mapped_column(BigInteger, primary_key=True)
    patron:      Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    activo:      Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              default=True, server_default="true")
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(), onupdate=func.now())


class StarlinkFacturaLinea(Base):
    """Línea de una factura Starlink resuelta a un proyecto (minigranja).
    Proyección normalizada de agrupado_json: una fila por sitio, con proyecto_id
    (NULL = sin asignar) y el valor sin IVA que consume el consolidado."""
    __tablename__ = "starlink_factura_linea"

    id:          Mapped[int] = mapped_column(BigInteger, primary_key=True)
    factura_id:  Mapped[int] = mapped_column(
        BigInteger, ForeignKey("starlink_facturas.id", ondelete="CASCADE"),
        nullable=False, index=True)
    proyecto_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("proyectos.id"), nullable=True, index=True)
    descripcion: Mapped[str]   = mapped_column(String(255), nullable=False)
    sin_iva:     Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    iva:         Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    monto_total: Mapped[float] = mapped_column(Numeric(15, 2), nullable=False)
    created_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at:  Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                  server_default=func.now(), onupdate=func.now())
```

En `app/models/__init__.py`, cambiar la línea de import de starlink (actual línea 33):

```python
from app.models.starlink import StarlinkFactura, StarlinkMapeoSitio, StarlinkFacturaLinea
```

Y en la lista `__all__`, reemplazar `"StarlinkFactura",` por:

```python
    "StarlinkFactura", "StarlinkMapeoSitio", "StarlinkFacturaLinea",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_starlink_modelos.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/models/starlink.py app/models/__init__.py tests/test_starlink_modelos.py
git commit -m "feat(starlink): modelos starlink_mapeo_sitio y starlink_factura_linea"
```

---

## Task 3: DDL en `_PENDING_DDLS`

**Files:**
- Modify: `app/main.py` (lista `_PENDING_DDLS`, termina en la línea ~1007 con `]`)

- [ ] **Step 1: Añadir la DDL idempotente**

En `app/main.py`, dentro de la lista `_PENDING_DDLS`, justo ANTES del `]` de cierre (después de la última entrada `"ALTER TABLE ppa_contratos ADD COLUMN IF NOT EXISTS renovacion_automatica BOOLEAN",`), añadir:

```python
    # Vínculo Starlink ↔ minigranja (2026-07): mapeo editable sitio→proyecto y
    # líneas de factura resueltas por proyecto. Tablas nuevas (Alembic no es el
    # camino de deploy en este repo — ver nota de migration 031 arriba).
    """CREATE TABLE IF NOT EXISTS starlink_mapeo_sitio (
        id BIGSERIAL PRIMARY KEY,
        patron VARCHAR(255) NOT NULL UNIQUE,
        proyecto_id BIGINT REFERENCES proyectos(id),
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_starlink_mapeo_sitio_proyecto ON starlink_mapeo_sitio (proyecto_id)",
    """CREATE TABLE IF NOT EXISTS starlink_factura_linea (
        id BIGSERIAL PRIMARY KEY,
        factura_id BIGINT NOT NULL REFERENCES starlink_facturas(id) ON DELETE CASCADE,
        proyecto_id BIGINT REFERENCES proyectos(id),
        descripcion VARCHAR(255) NOT NULL,
        sin_iva NUMERIC(15,2) NOT NULL,
        iva NUMERIC(15,2) NOT NULL,
        monto_total NUMERIC(15,2) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_starlink_factura_linea_factura ON starlink_factura_linea (factura_id)",
    "CREATE INDEX IF NOT EXISTS ix_starlink_factura_linea_proyecto ON starlink_factura_linea (proyecto_id)",
```

- [ ] **Step 2: Verificar que el módulo importa sin errores de sintaxis**

Run: `python -c "import app.main"`
Expected: sin excepción (puede imprimir logs de startup DDL, pero no traceback de `SyntaxError`).

- [ ] **Step 3: Commit**

```bash
git add app/main.py
git commit -m "feat(starlink): DDL de tablas de mapeo y lineas en _PENDING_DDLS"
```

---

## Task 4: Helper `_regenerar_lineas` + extender PUT/GET

**Files:**
- Modify: `app/api/v1/starlink.py` (imports arriba; PUT en línea ~90; GET en línea ~68)

- [ ] **Step 1: Añadir imports y helper**

En `app/api/v1/starlink.py`, tras la línea `from app.models.starlink import StarlinkFactura` (línea 22), cambiarla por:

```python
from app.models.starlink import StarlinkFactura, StarlinkMapeoSitio, StarlinkFacturaLinea
from app.models.proyectos import Proyecto
from app.services.starlink_resolver import resolver_lineas
```

Añadir el helper justo después de `router = APIRouter(...)` (línea 25):

```python
def _regenerar_lineas(db: Session, fac: StarlinkFactura) -> None:
    """(Re)genera starlink_factura_linea para una factura desde su agrupado_json,
    resolviendo cada sitio contra el catálogo starlink_mapeo_sitio (match por nombre)."""
    agrupado = json.loads(fac.agrupado_json)
    mapeos = [
        {"patron": m.patron, "proyecto_id": m.proyecto_id}
        for m in db.query(StarlinkMapeoSitio).filter(StarlinkMapeoSitio.activo.is_(True)).all()
    ]
    db.query(StarlinkFacturaLinea).filter(StarlinkFacturaLinea.factura_id == fac.id).delete()
    for ln in resolver_lineas(agrupado, mapeos):
        db.add(StarlinkFacturaLinea(
            factura_id=fac.id,
            proyecto_id=ln["proyecto_id"],
            descripcion=ln["descripcion"],
            sin_iva=ln["sin_iva"],
            iva=ln["iva"],
            monto_total=ln["monto_total"],
        ))
```

- [ ] **Step 2: Regenerar líneas en el PUT**

En `guardar_factura` (PUT), la función hoy termina con:

```python
    db.commit()
    db.refresh(fac)
    return {"ok": True, "periodo": fac.periodo}
```

Reemplazar ese bloque final por:

```python
    db.flush()          # asegura fac.id antes de generar las líneas
    _regenerar_lineas(db, fac)
    db.commit()
    db.refresh(fac)
    return {"ok": True, "periodo": fac.periodo}
```

- [ ] **Step 3: Devolver líneas resueltas en el GET**

En `obtener_factura` (GET), el `return {...}` actual añade sus campos. Antes del `return`, insertar:

```python
    lineas_rows = (
        db.query(StarlinkFacturaLinea)
        .filter(StarlinkFacturaLinea.factura_id == fac.id)
        .all()
    )
    pids = {l.proyecto_id for l in lineas_rows if l.proyecto_id is not None}
    nombres = {}
    if pids:
        nombres = {
            pid: nombre
            for pid, nombre in db.query(Proyecto.id, Proyecto.nombre_comercial)
                                 .filter(Proyecto.id.in_(pids)).all()
        }
    lineas = [
        {
            "descripcion":      l.descripcion,
            "proyecto_id":      l.proyecto_id,
            "nombre_comercial": nombres.get(l.proyecto_id),
            "sin_iva":          float(l.sin_iva),
            "iva":              float(l.iva),
            "monto_total":      float(l.monto_total),
        }
        for l in lineas_rows
    ]
```

Y añadir `"lineas": lineas,` como una clave más del dict que retorna el endpoint.

- [ ] **Step 4: Verificar import**

Run: `python -c "import app.api.v1.starlink"`
Expected: sin traceback.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/starlink.py
git commit -m "feat(starlink): PUT regenera lineas resueltas; GET las devuelve con nombre_comercial"
```

---

## Task 5: Endpoints de mapeo (listar + upsert con reproceso)

**Files:**
- Modify: `app/api/v1/starlink.py`

- [ ] **Step 1: Añadir endpoints de mapeo**

Al final de `app/api/v1/starlink.py`, antes de la sección `# ── POST /starlink/excel ──`, añadir:

```python
# ── GET /starlink/mapeo ───────────────────────────────────────────────────────

@router.get("/mapeo")
def listar_mapeo(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Catálogo de mapeos sitio→proyecto, con el nombre comercial resuelto."""
    filas = db.query(StarlinkMapeoSitio).order_by(StarlinkMapeoSitio.patron).all()
    pids = {m.proyecto_id for m in filas if m.proyecto_id is not None}
    nombres = {}
    if pids:
        nombres = {
            pid: nombre
            for pid, nombre in db.query(Proyecto.id, Proyecto.nombre_comercial)
                                 .filter(Proyecto.id.in_(pids)).all()
        }
    return [
        {
            "id": m.id, "patron": m.patron, "proyecto_id": m.proyecto_id,
            "nombre_comercial": nombres.get(m.proyecto_id), "activo": m.activo,
        }
        for m in filas
    ]


# ── PUT /starlink/mapeo ───────────────────────────────────────────────────────

@router.put("/mapeo")
def upsert_mapeo(payload: dict, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Crea o actualiza un mapeo sitio→proyecto (clave: patron) y reprocesa TODAS
    las facturas guardadas para reflejar el cambio en las líneas."""
    patron = (payload.get("patron") or "").strip()
    if not patron:
        raise HTTPException(400, "patron es obligatorio.")
    proyecto_id = payload.get("proyecto_id")

    m = db.query(StarlinkMapeoSitio).filter(StarlinkMapeoSitio.patron == patron).first()
    if m:
        m.proyecto_id = proyecto_id
        m.activo = payload.get("activo", True)
    else:
        m = StarlinkMapeoSitio(patron=patron, proyecto_id=proyecto_id,
                               activo=payload.get("activo", True))
        db.add(m)
    db.flush()

    for fac in db.query(StarlinkFactura).all():
        _regenerar_lineas(db, fac)
    db.commit()
    db.refresh(m)
    return {"ok": True, "id": m.id, "patron": m.patron}
```

- [ ] **Step 2: Verificar import**

Run: `python -c "import app.api.v1.starlink"`
Expected: sin traceback.

- [ ] **Step 3: Commit**

```bash
git add app/api/v1/starlink.py
git commit -m "feat(starlink): endpoints GET/PUT de mapeo sitio->proyecto con reproceso"
```

---

## Task 6: Seed + backfill en el startup

**Files:**
- Modify: `app/main.py` (añadir función `_run_starlink_mapeo_seed` y llamarla donde se corren los seeds de startup)

- [ ] **Step 1: Localizar dónde se invocan los seeds de startup**

Run: `grep -n "_run_catalog_seed\|_run_column_migrations" app/main.py`
Expected: aparece la llamada a `_run_column_migrations()` y `_run_catalog_seed()` dentro del handler de startup (evento `startup` o `lifespan`). Anotar el nombre de esa función/handler para añadir ahí la nueva llamada.

- [ ] **Step 2: Añadir la función de seed + backfill**

En `app/main.py`, después de `_run_catalog_seed()` (termina cerca de la línea ~1110), añadir:

```python
# Semilla del mapeo sitio Starlink → minigranja. patron (normalizado como queda en
# agrupado.descripcion) → nombre_comercial del proyecto. Migrado del hardcode
# STARLINK_TO_PANEL del frontend. NESTLE / OFICINA UNERGY no son minigranjas → NULL.
_STARLINK_SEED = {
    "BARAYA": "Minigranja Solar Baraya",
    "CUMBIA": "Minigranja Solar Cumbia",
    "EL COPEY OCCIDENTE": "Minigranja Solar Copey",
    "EL MOLINO": "Minigranja Solar El Molino",
    "EL OLIMPO": "Minigranja Solar El Olimpo",
    "EL SON": "Minigranja Solar El Son",
    "GANDALF": "Minigranja Solar Gandalf",
    "CANAHUATE": "Minigranja Solar Cañahuate",
    "IBIRICO": "Minigranja Solar Ibirico",
    "MAPALE": "Minigranja Solar Mapalé",
    "LA ESMERALDA": "Minigranja Solar Esmeralda",
    "LA MESA": "Minigranja Solar La Mesa",
    "VALLENATA": "Minigranja Solar La Paz Vallenata",
    "LEYENDA": "Minigranja Solar La Paz Leyenda",
    "LA RESERVA": "MGS 0012 La Reserva",
    "PUYA": "Minigranja Solar La Puya",
    "MGS LA PAZ VERSO": "Minigranja Solar La Paz Verso",
    "PERUA": "Minigranja Solar Perijá",
    "SAN DIEGO SUR": "Minigranja Solar San Diego Sur",
    "URUACO": "Minigranja Solar Uruaco",
    "VILLANUEVA": "Minigranja Solar Villanueva",
    "CACICA": "Minigranja Solar La Cacica",
    "PILONERAS": "Minigranja Solar Las Piloneras",
    "VALENCIA 1": "Minigranja Solar Valencia Oriente 1",
    "VALENCIA 2": "Minigranja Solar Valencia Oriente 2",
    "CHIRIGUANA N2": "Minigranja Solar Chiriguana 2",
    "CHIRIGUANA N4": "Minigranja Solar Chiriguana 4",
    # Nombres individuales que produce el parser al dividir splits y que no están en
    # el mapa del front (JOROPO MAPALE → Joropo/Mapale; PUYA Y MERENGUE → Puya/Merengue):
    "JOROPO": "Minigranja Solar Joropo",
    "MERENGUE": "MGS 0019 El Merengue",
    # Sitios conocidos que NO son minigranjas → proyecto_id NULL (quedan "sin asignar"):
    "NESTLE": None,
    "OFICINA UNERGY": None,
}


def _run_starlink_mapeo_seed() -> None:
    """Siembra starlink_mapeo_sitio (idempotente: no pisa proyecto_id editado) y
    hace backfill de starlink_factura_linea para las facturas ya guardadas."""
    from sqlalchemy.orm import sessionmaker
    from app.models.proyectos import Proyecto
    from app.models.starlink import StarlinkFactura, StarlinkMapeoSitio
    from app.api.v1.starlink import _regenerar_lineas

    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # nombre_comercial → id (para resolver el seed)
        proyectos = {p.nombre_comercial: p.id for p in db.query(Proyecto.id, Proyecto.nombre_comercial).all()}
        for patron, nombre in _STARLINK_SEED.items():
            patron = patron.strip()
            if not patron:
                continue
            existente = db.query(StarlinkMapeoSitio).filter(StarlinkMapeoSitio.patron == patron).first()
            if existente:
                continue  # idempotente: no tocar lo que ya existe (posible edición manual)
            db.add(StarlinkMapeoSitio(
                patron=patron,
                proyecto_id=proyectos.get(nombre) if nombre else None,
                activo=True,
            ))
        db.flush()

        # Backfill: facturas sin líneas → generarlas
        from app.models.starlink import StarlinkFacturaLinea
        for fac in db.query(StarlinkFactura).all():
            tiene = db.query(StarlinkFacturaLinea).filter(StarlinkFacturaLinea.factura_id == fac.id).first()
            if not tiene:
                _regenerar_lineas(db, fac)
        db.commit()
        print("[starlink seed] OK — mapeo sembrado y backfill de líneas")
    except Exception as e:
        db.rollback()
        print(f"[starlink seed] ERROR: {e}")
    finally:
        db.close()
```

**Nota:** elimina la entrada `"MAPALE ": None` del dict — se dejó marcada como inválida arriba solo para señalar que NO debe incluirse; el sitio "Mapalé" ya está cubierto por `"MAPALE": "Minigranja Solar Mapalé"`. El dict final NO debe contener claves con espacios finales ni valores placeholder.

> **Nota de mantenimiento:** el dict `_STARLINK_SEED` es solo la semilla inicial. Una
> vez desplegado, el catálogo se edita en runtime vía `PUT /starlink/mapeo` (Task 5) y
> el seed es idempotente (no pisa lo editado). No hay claves con espacios ni valores
> placeholder: cada clave es un `patron` normalizado y cada valor un `nombre_comercial`
> exacto o `None`.

- [ ] **Step 3: Llamar la función en el startup**

En el handler de startup (el que ya llama a `_run_column_migrations()` y `_run_catalog_seed()`, identificado en Step 1), añadir la llamada **después** de `_run_column_migrations()` (las tablas deben existir antes del seed):

```python
    _run_starlink_mapeo_seed()
```

- [ ] **Step 4: Verificar import**

Run: `python -c "import app.main"`
Expected: sin traceback (`SyntaxError`/`ImportError`).

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat(starlink): seed del mapeo + backfill de lineas en startup"
```

---

## Task 7: Frontend — consumir líneas resueltas en el export

**Files:**
- Modify: `unergy-operaciones-frontend-master/src/views/Finanzas/costosExcelExport.js` (bloque `public_services por pk`, líneas ~127-136)

- [ ] **Step 1: Reemplazar la lógica de `public_services`**

En `costosExcelExport.js`, el bloque actual es:

```javascript
  // Internet (backend)
  let agrupado = []
  try { agrupado = (await api.get(`/starlink/factura/${periodo}`)).data.agrupado || [] } catch { agrupado = [] }

  // public_services por pk
  const pubByPk = {}
  agrupado.forEach(it => {
    const pk = resolvePk(starlinkPanel(it.descripcion))
    pubByPk[pk] = (pubByPk[pk] || 0) + (it.sin_iva || 0)
  })
```

Reemplazarlo por (usa las `lineas` resueltas por el backend; si no hay líneas —dato viejo aún sin backfill— cae al agrupado con `sin_iva`):

```javascript
  // Internet (backend) — líneas ya resueltas a proyecto (proyecto_id + nombre_comercial)
  let starlinkData = { lineas: [], agrupado: [] }
  try { starlinkData = (await api.get(`/starlink/factura/${periodo}`)).data } catch { /* sin datos */ }

  // public_services por pk. Fuente primaria: lineas resueltas (nombre_comercial).
  // Fallback (datos aún sin backfill): agrupado + mapeo de nombre en el front.
  const pubByPk = {}
  const lineas = starlinkData.lineas || []
  if (lineas.length) {
    lineas.forEach(l => {
      const pk = resolvePk(l.nombre_comercial || l.descripcion)
      pubByPk[pk] = (pubByPk[pk] || 0) + (l.sin_iva || 0)
    })
  } else {
    (starlinkData.agrupado || []).forEach(it => {
      const pk = resolvePk(starlinkPanel(it.descripcion))
      pubByPk[pk] = (pubByPk[pk] || 0) + (it.sin_iva || 0)
    })
  }
```

- [ ] **Step 2: Build de verificación**

Run (desde `unergy-operaciones-frontend-master/`): `npm run build`
Expected: `✓ built` sin errores (solo warnings de tamaño de chunk son aceptables).

- [ ] **Step 3: Commit**

```bash
git add src/views/Finanzas/costosExcelExport.js
git commit -m "feat(costos): export usa lineas Starlink resueltas por proyecto"
```

---

## Task 8: Frontend — columna Minigranja + asignar sitios sin mapear en StarlinkPDF.vue

**Files:**
- Modify: `unergy-operaciones-frontend-master/src/views/Finanzas/StarlinkPDF.vue`

> Este componente ya carga la factura del período vía `GET /starlink/factura/{periodo}`.
> Tras Task 4 esa respuesta incluye `lineas` con `proyecto_id` + `nombre_comercial`.

- [ ] **Step 1: Mostrar la minigranja resuelta en la tabla Agrupado**

En la tabla "Agrupado" de `StarlinkPDF.vue`, añadir una columna que muestre la minigranja resuelta emparejando por `descripcion` con las `lineas` del período. Guardar `this.lineas` (o el ref equivalente) al cargar la factura, y añadir una `<Column>`:

```vue
<Column header="Minigranja">
  <template #body="{ data }">
    <span v-if="minigranjaDe(data.descripcion)">{{ minigranjaDe(data.descripcion) }}</span>
    <Tag v-else severity="warn" value="Sin asignar" />
  </template>
</Column>
```

Con el helper (en methods o `<script setup>`):

```javascript
function minigranjaDe(descripcion) {
  const l = (lineas.value || []).find(x => x.descripcion === descripcion)
  return l ? l.nombre_comercial : null
}
```

- [ ] **Step 2: Permitir asignar un sitio "Sin asignar" a una minigranja**

Añadir, en la fila "Sin asignar", un botón que abra un `Dropdown` con la lista de proyectos (cargada de `GET /proyectos` o el store existente) y al confirmar llame:

```javascript
await api.put('/starlink/mapeo', { patron: descripcionNormalizada, proyecto_id: proyectoSeleccionadoId })
// luego recargar la factura del período para refrescar lineas
await cargarPeriodo(periodoActual)
```

Donde `descripcionNormalizada` = `descripcion.normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase().trim().replace(/\s+/g,' ')` (mismo criterio que `normalizar_sitio` del backend).

- [ ] **Step 3: Build de verificación**

Run (desde `unergy-operaciones-frontend-master/`): `npm run build`
Expected: `✓ built` sin errores.

- [ ] **Step 4: Commit**

```bash
git add src/views/Finanzas/StarlinkPDF.vue
git commit -m "feat(costos): columna Minigranja y asignacion de sitios sin mapear en Starlink"
```

---

## Task 9: Verificación integral

- [ ] **Step 1: Correr toda la suite de tests del backend**

Run (desde `unergy-operaciones-backend/`): `python -m pytest tests/test_starlink_resolver.py tests/test_starlink_modelos.py -v`
Expected: todos PASS.

- [ ] **Step 2: Correr la suite completa para no romper nada**

Run: `python -m pytest -q`
Expected: sin fallos nuevos respecto al baseline (los tests preexistentes siguen verdes).

- [ ] **Step 3: Build del frontend**

Run (desde `unergy-operaciones-frontend-master/`): `npm run build`
Expected: `✓ built` sin errores.

- [ ] **Step 4: Deploy (según guía de trabajo)**

Solo cuando el usuario lo apruebe: `git push origin master` en cada repo (Railway/Vercel auto-despliegan). Verificar en los dashboards. Tras el deploy del backend, el startup crea las tablas (`_PENDING_DDLS`), siembra el mapeo y hace backfill de las facturas existentes.

---

## Notas de verificación funcional (post-deploy)

- `GET /starlink/factura/2026-06` debe devolver `lineas` con `proyecto_id` y `nombre_comercial` para Baraya, Gandalf, Cañahuate, etc.
- El Excel consolidado de 2026-06 debe seguir mostrando `public_services` sin IVA (Baraya 129412.61; Gandalf/Cañahuate 64706.31) — ahora derivado de `proyecto_id`, no del string.
- Un sitio no mapeado (p. ej. uno nuevo) aparece como "Sin asignar" en StarlinkPDF y puede asignarse; tras asignarlo, su valor entra al consolidado.
