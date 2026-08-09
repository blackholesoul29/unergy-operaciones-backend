# Ficha operativa de la oferta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la API del CRM devuelva, por cada oferta, los 6 parámetros que el equipo consume — nombre del proyecto, lugar, operador de red, energía real, energía promedio, fecha de inicio de operación y tiempo del contrato de compra — aunque la planta todavía no exista como `Proyecto` y aunque hoy no haya información.

**Architecture:** Cuatro columnas nullable en `oportunidad_ofertas` guardan lo *declarado* cuando no hay `Proyecto`. Una función pura `ficha_operativa()` resuelve cada campo por cascada **Proyecto → declarado en la oferta → null** y devuelve valores planos más un mapa `fuentes` que dice de dónde salió cada uno. Un cargador por lotes `contexto_ficha()` precarga proyectos, PPAs, operadores y generación en un número **fijo** de consultas, para que la lista plana de `/comercial` no caiga en N+1.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 (estilo `Mapped`/`mapped_column`), PostgreSQL 17 en producción, pytest con SQLite en memoria para tests.

## Global Constraints

- **No hay Alembic.** Toda migración es un statement idempotente al final de `_PENDING_DDLS` en `app/main.py`, que corre **en cada arranque**. Prohibido `RENAME VALUE` reversible: dejar un rename y su inverso hace que cada deploy revierta la migración (trampa de julio, documentada en el propio `_PENDING_DDLS`).
- **Antes de un `ADD COLUMN` en el CRM, grep del concepto en `app/models/`.** Ya se hizo para este trabajo: `municipio`, `departamento`, `operador_red_id` y `energia_promedio_kwh_mes` no existen en `oportunidad_ofertas`, y no duplican al contrato — `ppa_contratos.cantidad_minima_kwh_mes` es un **compromiso contractual**, `energia_promedio_kwh_mes` es una **estimación técnica de generación**. Cosas distintas.
- **No se agrega columna de fecha:** `oportunidad_ofertas.fecha_tentativa_inicio` ya existe y es exactamente el fallback de "cuándo arranca el suministro".
- Comentarios y docstrings **en español**, explicando el *por qué*, como el resto de `app/services/comercial.py` y `app/models/comercial.py`.
- **Sin dependencias nuevas.** Sin cambios en el frontend (fuera de alcance por decisión de Juan, 2026-08-03).
- Los tests corren con `pytest tests/ -q` desde `Backend Operaciones`. Línea base: **694 tests pasan** antes de este trabajo. No pueden bajar.
- Los tests nuevos usan SQLite en memoria y llaman las funciones del router **directamente** (`api.list_ofertas_todas(db=db, current=ADMIN)`), como `tests/test_comercial_pipeline_oferta.py`. No hay `TestClient` en esta suite.
- **Sobre los commits:** el repo tiene el trabajo del pipeline-por-oferta (2026-08-02) sin commitear en estos mismos archivos. Los commits de este plan lo van a arrastrar; está bien, es la misma línea de trabajo. Lo que **no** se debe agregar nunca es lo ajeno: `backend_structure.html`, `docs/API_FALLAS.md`, `scripts/*`, `Guía de inicio — Plataforma Operaciones.md`. Por eso cada commit usa rutas explícitas en `git add`, nunca `git add -A`.

---

## Contexto del dominio (leer antes de empezar)

Quien implemente esto probablemente no conozca el modelo. Lo mínimo:

- Una **Oportunidad** es un cliente en el pipeline comercial. Cuelga de `Cliente`.
- Una **OportunidadOferta** (`oportunidad_ofertas`) es *una planta × un tipo de servicio*. **El negocio es la oferta, no el cliente**: la etapa del pipeline vive en la oferta. Un cliente puede tener una oferta firmada y otra todavía en envío.
- Un **Proyecto** (`proyectos`) es la planta física, con su ubicación, operador de red y generación. **Muchas ofertas no tienen proyecto**: la planta todavía no existe. Ese es el hueco que resuelve este plan.
- Al firmar (`POST /comercial/ofertas/{id}/firmar`) nace un **PPAContrato** (`ppa_contratos`) con `fecha_inicio`/`fecha_fin`, y la oferta se queda con `ppa_contrato_id`. Las condiciones comerciales viven en el contrato, **nunca** copiadas en la oferta.
- `generacion_diaria` tiene una fila por proyecto y día con `kwh_real`.
- `Proyecto.operador_red_legal` es una `@property` que ya resuelve la cascada operador propio → primera frontera que lo tenga. Requiere precargar `operador` y `fronteras.operador`.

**Decisiones ya cerradas con Juan (2026-08-03), no reabrir:**
1. Los datos se **declaran en la oferta** cuando no hay Proyecto (no se fuerza a crear el Proyecto: el endpoint del CRM exige `operador_red_id` obligatorio y eso está pendiente de hablar con Sara).
2. "Energía promedio" = **generación mensual estimada** (kWh/mes que se espera que genere la planta).
3. "Fecha de inicio de operación" = **inicio de suministro del PPA**; si la oferta no está firmada, la fecha tentativa declarada.

---

## File Structure

| Archivo | Responsabilidad | Tarea |
|---|---|---|
| `app/models/comercial.py` | 4 columnas nuevas en `OportunidadOferta` | 1 |
| `app/main.py` | 5 statements DDL idempotentes al final de `_PENDING_DDLS` | 1 |
| `app/services/comercial.py` | `meses_de_contrato()` + `ficha_operativa()` (puras) y `contexto_ficha()` + `_ultimo_mes_generacion()` (acceso a datos, por lotes) | 2, 3 |
| `app/schemas/comercial.py` | los 4 campos en `OfertaCreate` y `OfertaUpdate` | 4 |
| `app/api/v1/comercial.py` | `_oferta_out(o, ficha=None)`, validación del operador, cableado en los 4 puntos que serializan ofertas | 4 |
| `tests/test_comercial_ficha_operativa.py` | **NUEVO** — todos los tests de este plan | 1–4 |
| `data/comercial_cierres_2026-08.json` | bloque `ficha` por cierre, con las 4 llaves en null | 5 |
| `../comercial_jake/comercial_cierres_2026-08.json` | copia de lectura, se sincroniza | 5 |

`ficha_operativa()` y `contexto_ficha()` van juntas en `app/services/comercial.py` aunque una sea pura y la otra toque la BD: es el mismo concepto y el archivo ya mezcla ambas cosas (`cerrar_contratos_vencidos()` recibe `db`). Partirlo en dos módulos por purismo dejaría dos archivos de 60 líneas que siempre se editan juntos.

---

### Task 1: Las 4 columnas declaradas y su migración

**Files:**
- Modify: `app/models/comercial.py` (imports en la línea 3-4; clase `OportunidadOferta`, insertar antes de `notas` en la línea 213)
- Modify: `app/main.py` (al final de `_PENDING_DDLS`, después de la línea 1194)
- Test: `tests/test_comercial_ficha_operativa.py` (crear)

**Interfaces:**
- Consumes: nada.
- Produces: `OportunidadOferta.municipio: str | None`, `.departamento: str | None`, `.operador_red_id: int | None`, `.energia_promedio_kwh_mes: Decimal | None`. Las tareas 2–4 dependen de estos nombres exactos.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_comercial_ficha_operativa.py` con este contenido completo (las tareas siguientes le agregan tests al final):

```python
"""Ficha operativa de la oferta (2026-08-03).

Los 6 parámetros que el equipo consume por API — nombre del proyecto, lugar,
operador de red, energía real, energía promedio, fecha de inicio de operación y
tiempo del contrato — solo existían colgados de `Proyecto`, y la mayoría de las
ofertas del pipeline no tienen proyecto (GD Rio Pamplonita y GD Las Margaritas 1
ni siquiera existen como planta). Lo que se protege aquí es la cascada
Proyecto → declarado en la oferta → null, y que consultarla no cueste una
consulta por oferta.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.models.generacion import GeneracionDiaria
from app.models.contratos import PPAContrato, PPATarifa, ContratoServicio
from app.models.comercial import (
    Oportunidad, OportunidadOferta, OportunidadEstadoHistorial, OportunidadGestion,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Cliente.__table__, ClienteDocumentoComercial.__table__, Contacto.__table__,
        Proyecto.__table__, Frontera.__table__, OperadorRed.__table__,
        GeneracionDiaria.__table__,
        Oportunidad.__table__, OportunidadOferta.__table__,
        OportunidadEstadoHistorial.__table__, OportunidadGestion.__table__,
        PPAContrato.__table__, PPATarifa.__table__, ContratoServicio.__table__,
        Base.metadata.tables["ppa_contrato_proyectos"],
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# ── Task 1: las columnas declaradas ──────────────────────────────────────────

def test_la_oferta_puede_declarar_lugar_operador_y_energia(db):
    """Sin Proyecto no hay dónde poner el lugar ni el operador. Estas cuatro
    columnas son ese lugar: la oferta declara lo que sabe y la API lo resuelve."""
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()

    of = OportunidadOferta(
        oportunidad_id=op.id, tipo="compra_energia",
        planta_nombre="GD Las Margaritas 1",
        municipio="Sincelejo", departamento="Sucre",
        operador_red_id=orr.id, energia_promedio_kwh_mes=185000)
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio == "Sincelejo"
    assert of.departamento == "Sucre"
    assert of.operador_red_id == orr.id
    assert float(of.energia_promedio_kwh_mes) == 185000.0


def test_los_cuatro_campos_son_opcionales(db):
    """Una oferta recién creada no sabe nada de la planta todavía."""
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia")
    db.add(of); db.commit(); db.refresh(of)

    assert of.municipio is None and of.departamento is None
    assert of.operador_red_id is None and of.energia_promedio_kwh_mes is None
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: FAIL — `TypeError: 'municipio' is an invalid keyword argument for OportunidadOferta`.

- [ ] **Step 3: Agregar las columnas al modelo**

En `app/models/comercial.py`, agregar `Numeric` al import de SQLAlchemy (línea 3-4), que hoy no lo trae:

```python
from sqlalchemy import (BigInteger, Integer, String, Boolean, Date, DateTime,
                        ForeignKey, Enum as SAEnum, Numeric, Text)
```

Y en la clase `OportunidadOferta`, **justo antes** de `notas: Mapped[str | None] = mapped_column(Text, nullable=True)` (línea 213):

```python
    # ── Ficha operativa declarada (2026-08-03) ───────────────────────────────
    # Lo que el equipo consulta por API vive en `proyectos`, pero la mayoría de
    # las ofertas del pipeline no tienen proyecto todavía (la planta no existe).
    # Estas columnas son el fallback declarado; la API resuelve por cascada
    # Proyecto → oferta → null y dice de dónde salió cada dato (ficha_operativa).
    municipio: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departamento: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Solo el FK al catálogo, sin texto libre: `proyectos.operador_red` (texto)
    # ya está declarado legacy en su propio modelo y no se repite el error. Si
    # falta un operador, se arregla el catálogo.
    operador_red_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("operadores_red.id"), nullable=True, index=True)
    # Generación mensual ESTIMADA, en kWh para hablar el idioma del CRM
    # (cantidad_minima_kwh_mes). No confundir con esa: aquella es un compromiso
    # contractual del PPA, esta es una estimación técnica de la planta.
    energia_promedio_kwh_mes: Mapped[float | None] = mapped_column(
        Numeric(14, 3), nullable=True)
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Agregar los DDL de migración**

En `app/main.py`, al **final** de la lista `_PENDING_DDLS`, después de `"ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS documento_url VARCHAR(1000)",` (línea 1194) y antes del `]`:

```python
    # migration — Comercial: ficha operativa declarada en la oferta (2026-08-03)
    # Los 6 parámetros que el equipo consume por API solo existían colgados de
    # `proyectos`, y las ofertas del pipeline no tienen proyecto. Estas columnas
    # son el fallback declarado; la API resuelve Proyecto → oferta → null.
    # energia_promedio_kwh_mes NO duplica a ppa_contratos.cantidad_minima_kwh_mes:
    # aquella es el compromiso contractual, esta la estimación de generación.
    "ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS municipio VARCHAR(100)",
    "ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS departamento VARCHAR(100)",
    "ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS operador_red_id BIGINT REFERENCES operadores_red(id)",
    "ALTER TABLE oportunidad_ofertas ADD COLUMN IF NOT EXISTS energia_promedio_kwh_mes NUMERIC(14,3)",
    "CREATE INDEX IF NOT EXISTS ix_oferta_operador_red ON oportunidad_ofertas (operador_red_id)",
```

Los cinco son `IF NOT EXISTS`: correr el arranque dos veces no hace nada la segunda. Ningún `RENAME VALUE`, ningún `DROP`.

- [ ] **Step 6: Verificar que la suite completa sigue verde**

Run: `pytest tests/ -q`
Expected: PASS — 696 passed (694 de línea base + los 2 nuevos).

- [ ] **Step 7: Commit**

```bash
git add app/models/comercial.py app/main.py tests/test_comercial_ficha_operativa.py
git commit -m "feat(comercial): la oferta declara lugar, operador de red y energia promedio"
```

---

### Task 2: `ficha_operativa()` — la cascada, sin tocar la BD

**Files:**
- Modify: `app/services/comercial.py` (agregar al final del archivo, después de `calcular_alerta`)
- Test: `tests/test_comercial_ficha_operativa.py` (agregar al final)

**Interfaces:**
- Consumes: las 4 columnas de la Task 1.
- Produces:
  - `meses_de_contrato(inicio: date | None, fin: date | None) -> int | None`
  - `ficha_operativa(oferta, proyecto=None, ppa=None, generacion=None, operador_oferta=None) -> dict`
    - `generacion`: `tuple[str, float] | None` — `("2026-07", 182350.0)`
    - `operador_oferta`: `str | None` — nombre legal del catálogo para `oferta.operador_red_id`
    - Devuelve exactamente estas llaves: `proyecto_nombre`, `municipio`, `departamento`, `operador_red`, `operador_red_id`, `energia_promedio_kwh_mes`, `energia_real_kwh_mes`, `energia_real_periodo`, `fecha_inicio_operacion`, `contrato_compra_meses`, `contrato_compra_anios`, `contrato_fecha_inicio`, `contrato_fecha_fin`, `fuentes`.
  - La Task 3 llama a `ficha_operativa(oferta, **contexto[oferta.id])`, así que los nombres de los parámetros son contrato.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_comercial_ficha_operativa.py`:

```python
# ── Task 2: la cascada Proyecto → oferta → null ──────────────────────────────

from app.services.comercial import ficha_operativa, meses_de_contrato  # noqa: E402


def _oferta(**kw):
    """Oferta mínima para la lógica pura: sin BD, solo los atributos que lee."""
    base = dict(planta_nombre=None, municipio=None, departamento=None,
                operador_red_id=None, energia_promedio_kwh_mes=None,
                fecha_tentativa_inicio=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _proyecto(**kw):
    base = dict(nombre_comercial=None, municipio=None, departamento=None,
                operador_red_id=None, operador_red_legal=None,
                mwh_mes_estimado=None, p50_mensual_kwh=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_sin_proyecto_la_ficha_sale_de_lo_declarado_en_la_oferta():
    """El caso GD Rio Pamplonita: la planta no existe como Proyecto y aun así el
    equipo tiene que poder consultar su lugar por API."""
    f = ficha_operativa(
        _oferta(planta_nombre="GD Rio Pamplonita", municipio="Cúcuta",
                departamento="Norte de Santander", operador_red_id=7),
        operador_oferta="CENS S.A. E.S.P.")

    assert f["proyecto_nombre"] == "GD Rio Pamplonita"
    assert f["municipio"] == "Cúcuta" and f["departamento"] == "Norte de Santander"
    assert f["operador_red"] == "CENS S.A. E.S.P." and f["operador_red_id"] == 7
    assert f["fuentes"]["municipio"] == "oferta"
    assert f["fuentes"]["operador_red"] == "oferta"


def test_el_proyecto_manda_sobre_lo_declarado():
    """Cuando la planta ya existe, el Proyecto es la verdad: lo declarado en la
    oferta fue una foto del momento de la venta y puede haber envejecido."""
    f = ficha_operativa(
        _oferta(planta_nombre="Catedral (borrador)", municipio="Sincelejo"),
        proyecto=_proyecto(nombre_comercial="GD Catedral", municipio="Corozal",
                           operador_red_legal="AFINIA S.A.S. E.S.P.", operador_red_id=3))

    assert f["proyecto_nombre"] == "GD Catedral"
    assert f["municipio"] == "Corozal"
    assert f["operador_red"] == "AFINIA S.A.S. E.S.P." and f["operador_red_id"] == 3
    assert f["fuentes"]["municipio"] == "proyecto"


def test_la_cascada_es_por_campo_no_por_entidad():
    """Un Proyecto a medio diligenciar no debe borrar lo que la oferta sí sabe."""
    f = ficha_operativa(
        _oferta(municipio="Sincelejo", departamento="Sucre"),
        proyecto=_proyecto(nombre_comercial="GD Catedral", municipio="Corozal"))

    assert f["municipio"] == "Corozal" and f["fuentes"]["municipio"] == "proyecto"
    assert f["departamento"] == "Sucre" and f["fuentes"]["departamento"] == "oferta"


def test_energia_promedio_del_proyecto_se_convierte_de_mwh_a_kwh():
    """`proyectos.mwh_mes_estimado` está en MWh; el CRM habla en kWh."""
    f = ficha_operativa(_oferta(), proyecto=_proyecto(mwh_mes_estimado=185.5))
    assert f["energia_promedio_kwh_mes"] == 185500.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "proyecto"


def test_sin_estimado_la_energia_promedio_cae_al_p50():
    """p50_mensual_kwh son 12 valores mensuales en kWh: el promedio es su media."""
    f = ficha_operativa(_oferta(), proyecto=_proyecto(p50_mensual_kwh=[100.0] * 11 + [220.0]))
    assert f["energia_promedio_kwh_mes"] == 110.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "proyecto"


def test_sin_proyecto_la_energia_promedio_es_la_declarada():
    f = ficha_operativa(_oferta(energia_promedio_kwh_mes=170000))
    assert f["energia_promedio_kwh_mes"] == 170000.0
    assert f["fuentes"]["energia_promedio_kwh_mes"] == "oferta"


def test_la_fecha_de_inicio_de_operacion_es_la_del_contrato():
    """Decisión de Juan: es el inicio de suministro del PPA, no la entrada en
    operación de la planta ni el inicio de comercialización."""
    ppa = types.SimpleNamespace(fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    f = ficha_operativa(_oferta(fecha_tentativa_inicio=dt.date(2026, 1, 1)), ppa=ppa)

    assert f["fecha_inicio_operacion"] == dt.date(2026, 2, 12)
    assert f["fuentes"]["fecha_inicio_operacion"] == "contrato"


def test_sin_contrato_la_fecha_es_la_tentativa_y_se_marca_estimada():
    """Una oferta no firmada no tiene PPA. La tentativa sirve, pero el consumidor
    de la API tiene que poder saber que es una estimación."""
    f = ficha_operativa(_oferta(fecha_tentativa_inicio=dt.date(2026, 10, 1)))
    assert f["fecha_inicio_operacion"] == dt.date(2026, 10, 1)
    assert f["fuentes"]["fecha_inicio_operacion"] == "estimada"
    assert f["contrato_compra_meses"] is None and f["contrato_compra_anios"] is None


def test_duracion_del_contrato_en_meses_calendario():
    """Se cuenta por mes calendario y no por días porque el PPA se factura por
    mes: es el mismo conteo que produce /firmar al expandir ppa_tarifas."""
    assert meses_de_contrato(dt.date(2026, 1, 1), dt.date(2026, 3, 31)) == 3      # Agustín 1
    assert meses_de_contrato(dt.date(2025, 11, 20), dt.date(2026, 12, 31)) == 14  # Bayunca
    assert meses_de_contrato(dt.date(2026, 2, 12), dt.date(2032, 12, 31)) == 83   # Catedral
    assert meses_de_contrato(dt.date(2026, 10, 1), dt.date(2036, 12, 31)) == 123
    assert meses_de_contrato(None, dt.date(2026, 3, 31)) is None
    assert meses_de_contrato(dt.date(2026, 3, 31), dt.date(2026, 1, 1)) is None


def test_la_duracion_tambien_viaja_en_anios():
    ppa = types.SimpleNamespace(fecha_inicio=dt.date(2026, 10, 1), fecha_fin=dt.date(2036, 12, 31))
    f = ficha_operativa(_oferta(), ppa=ppa)
    assert f["contrato_compra_meses"] == 123
    assert f["contrato_compra_anios"] == 10.3   # 10.25 redondeado hacia arriba
    assert f["contrato_fecha_inicio"] == dt.date(2026, 10, 1)
    assert f["contrato_fecha_fin"] == dt.date(2036, 12, 31)


def test_la_energia_real_viaja_con_su_periodo():
    """Sin el periodo, nadie sabe contra qué mes está comparando."""
    f = ficha_operativa(_oferta(), generacion=("2026-07", 182350.5))
    assert f["energia_real_kwh_mes"] == 182350.5
    assert f["energia_real_periodo"] == "2026-07"
    assert f["fuentes"]["energia_real_kwh_mes"] == "generacion"


def test_una_oferta_vacia_devuelve_nulls_y_fuentes_en_null():
    """"Todavía no lo sabemos" y "no aplica" tienen que verse distinto: el valor
    es null en ambos casos, pero `fuentes` dice que nadie lo aportó."""
    f = ficha_operativa(_oferta())
    for campo in ("proyecto_nombre", "municipio", "departamento", "operador_red",
                  "energia_promedio_kwh_mes", "energia_real_kwh_mes",
                  "fecha_inicio_operacion", "contrato_compra_meses"):
        assert f[campo] is None, campo
        assert f["fuentes"][campo] is None, campo
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: FAIL en el import — `ImportError: cannot import name 'ficha_operativa' from 'app.services.comercial'`.

- [ ] **Step 3: Implementar las dos funciones puras**

En `app/services/comercial.py`, agregar `from decimal import Decimal, ROUND_HALF_UP` debajo del import de `datetime` (línea 2), y al **final del archivo**:

```python
def meses_de_contrato(inicio, fin) -> int | None:
    """Meses calendario que cubre el suministro, contando el primero y el último.

    Se cuenta por mes y no por días porque el PPA se factura por mes: es
    exactamente el número de filas de `ppa_tarifas` que genera /firmar al
    expandir el periodo. 12-feb-2026 → 31-dic-2032 son 83 meses de suministro,
    no "6 años y pico".
    """
    if inicio is None or fin is None or fin < inicio:
        return None
    return (fin.year - inicio.year) * 12 + (fin.month - inicio.month) + 1


def ficha_operativa(oferta, proyecto=None, ppa=None, generacion=None,
                    operador_oferta=None) -> dict:
    """Los 6 parámetros que el equipo consume por API, resueltos por cascada.

    La cascada es POR CAMPO: lo que diga el Proyecto manda, si no hay Proyecto o
    el dato está vacío vale lo declarado en la oferta, si no null. Por campo y no
    por entidad porque un Proyecto a medio diligenciar no debe borrar lo que la
    oferta sí sabe.

    Devuelve valores PLANOS más un mapa `fuentes` aparte, en vez de envolver cada
    campo en {valor, fuente}: quien consume la API lee `ficha.municipio` directo,
    y quien necesita auditar de dónde salió el dato mira `fuentes`. Sin ese mapa,
    un null y un "todavía no lo sabemos" se ven igual.

    No toca la BD. `generacion` —("2026-07", kwh) del último mes cerrado— y
    `operador_oferta` —nombre legal del catálogo para oferta.operador_red_id—
    los precarga contexto_ficha() por lotes.
    """
    fuentes: dict[str, str | None] = {}

    def _elegir(campo, del_proyecto, de_la_oferta):
        if del_proyecto not in (None, ""):
            fuentes[campo] = "proyecto"
            return del_proyecto
        if de_la_oferta not in (None, ""):
            fuentes[campo] = "oferta"
            return de_la_oferta
        fuentes[campo] = None
        return None

    proyecto_nombre = _elegir(
        "proyecto_nombre",
        proyecto.nombre_comercial if proyecto else None,
        oferta.planta_nombre)
    municipio = _elegir("municipio",
                        proyecto.municipio if proyecto else None,
                        oferta.municipio)
    departamento = _elegir("departamento",
                           proyecto.departamento if proyecto else None,
                           oferta.departamento)

    # Operador de red: la cascada operador propio → primera frontera que lo tenga
    # ya vive en Proyecto.operador_red_legal; aquí solo se le agrega el escalón
    # de lo declarado en la oferta.
    operador_red = _elegir("operador_red",
                           proyecto.operador_red_legal if proyecto else None,
                           operador_oferta)
    if fuentes["operador_red"] == "proyecto":
        # Puede quedar None si el nombre salió de una frontera y no del proyecto:
        # el nombre es el dato, el id es la conveniencia.
        operador_red_id = proyecto.operador_red_id
    elif fuentes["operador_red"] == "oferta":
        operador_red_id = oferta.operador_red_id
    else:
        operador_red_id = None

    # Energía promedio = generación mensual ESTIMADA (decisión de Juan). El
    # proyecto habla en MWh/mes; el CRM en kWh/mes, como cantidad_minima_kwh_mes.
    promedio_proyecto = None
    if proyecto is not None:
        if proyecto.mwh_mes_estimado is not None:
            promedio_proyecto = float(proyecto.mwh_mes_estimado) * 1000
        elif proyecto.p50_mensual_kwh:
            vals = [float(v) for v in proyecto.p50_mensual_kwh if v is not None]
            if vals:
                promedio_proyecto = sum(vals) / len(vals)
    energia_promedio = _elegir(
        "energia_promedio_kwh_mes", promedio_proyecto,
        float(oferta.energia_promedio_kwh_mes)
        if oferta.energia_promedio_kwh_mes is not None else None)

    # Energía real: la del último mes CERRADO, con su periodo al lado para que
    # nadie compare contra un mes a medias.
    energia_real, energia_real_periodo = None, None
    if generacion:
        energia_real_periodo, kwh = generacion
        energia_real = float(kwh) if kwh is not None else None
    fuentes["energia_real_kwh_mes"] = "generacion" if energia_real is not None else None

    # Fecha de inicio de operación = inicio de suministro del PPA (decisión de
    # Juan). Sin contrato firmado sirve la tentativa, pero marcada como estimada.
    contrato_inicio = ppa.fecha_inicio if ppa else None
    contrato_fin = ppa.fecha_fin if ppa else None
    if contrato_inicio is not None:
        fecha_inicio_operacion = contrato_inicio
        fuentes["fecha_inicio_operacion"] = "contrato"
    elif oferta.fecha_tentativa_inicio is not None:
        fecha_inicio_operacion = oferta.fecha_tentativa_inicio
        fuentes["fecha_inicio_operacion"] = "estimada"
    else:
        fecha_inicio_operacion = None
        fuentes["fecha_inicio_operacion"] = None

    meses = meses_de_contrato(contrato_inicio, contrato_fin)
    anios = None
    if meses is not None:
        anios = float((Decimal(meses) / Decimal(12)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP))
    fuentes["contrato_compra_meses"] = "contrato" if meses is not None else None

    return {
        "proyecto_nombre": proyecto_nombre,
        "municipio": municipio,
        "departamento": departamento,
        "operador_red": operador_red,
        "operador_red_id": operador_red_id,
        "energia_promedio_kwh_mes": energia_promedio,
        "energia_real_kwh_mes": energia_real,
        "energia_real_periodo": energia_real_periodo,
        "fecha_inicio_operacion": fecha_inicio_operacion,
        "contrato_compra_meses": meses,
        "contrato_compra_anios": anios,
        "contrato_fecha_inicio": contrato_inicio,
        "contrato_fecha_fin": contrato_fin,
        "fuentes": fuentes,
    }
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/comercial.py tests/test_comercial_ficha_operativa.py
git commit -m "feat(comercial): ficha_operativa() resuelve los 6 parametros por cascada"
```

---

### Task 3: `contexto_ficha()` — precarga por lotes, sin N+1

**Files:**
- Modify: `app/services/comercial.py` (agregar al final, después de `ficha_operativa`)
- Test: `tests/test_comercial_ficha_operativa.py` (agregar al final)

**Interfaces:**
- Consumes: `ficha_operativa(...)` de la Task 2 (los nombres de sus parámetros son las llaves que produce esta tarea).
- Produces: `contexto_ficha(db, ofertas, hoy=None) -> dict[int, dict]`, donde cada valor es `{"proyecto": Proyecto|None, "ppa": PPAContrato|None, "generacion": tuple[str, float]|None, "operador_oferta": str|None}` — exactamente los kwargs de `ficha_operativa`, para que la Task 4 pueda hacer `ficha_operativa(o, **ctx[o.id])`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_comercial_ficha_operativa.py`:

```python
# ── Task 3: precarga por lotes ───────────────────────────────────────────────

from app.services.comercial import contexto_ficha  # noqa: E402


def _cliente_con_oferta(db, nombre="PELLETCO S.A.S.", **kw_oferta):
    cli = Cliente(razon_social_nombre=nombre)
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.flush()
    of = OportunidadOferta(oportunidad_id=op.id, tipo="compra_energia", **kw_oferta)
    db.add(of); db.flush()
    return op, of


def _generacion(db, proyecto_id, anio, mes, dias, kwh_dia=1000):
    for d in range(1, dias + 1):
        db.add(GeneracionDiaria(proyecto_id=proyecto_id, fecha=dt.date(anio, mes, d),
                                kwh_real=kwh_dia))
    db.flush()


def test_el_contexto_trae_proyecto_ppa_y_operador_declarado(db):
    orr = OperadorRed(nombre_legal="CENS S.A. E.S.P.")
    db.add(orr); db.flush()
    proy = Proyecto(nombre_comercial="GD Catedral", municipio="Corozal")
    db.add(proy); db.flush()
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31))
    db.add(ppa); db.flush()
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id,
                                operador_red_id=orr.id)
    db.commit()

    ctx = contexto_ficha(db, [of])
    assert ctx[of.id]["proyecto"].id == proy.id
    assert ctx[of.id]["ppa"].id == ppa.id
    assert ctx[of.id]["operador_oferta"] == "CENS S.A. E.S.P."
    assert ctx[of.id]["generacion"] is None   # la planta no ha generado


def test_la_energia_real_es_la_del_ultimo_mes_cerrado(db):
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 6, 30, kwh_dia=900)
    _generacion(db, proy.id, 2026, 7, 31, kwh_dia=1000)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    ctx = contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))
    assert ctx[of.id]["generacion"] == ("2026-07", 31000.0)


def test_el_mes_en_curso_no_cuenta(db):
    """Tres días de agosto no son "la energía del mes"."""
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 8, 3)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    assert contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))[of.id]["generacion"] is None


def test_un_mes_con_lecturas_a_medias_tampoco_cuenta(db):
    """20 de 31 días reportados darían un número 35% bajo, presentado como real."""
    proy = Proyecto(nombre_comercial="Bayunca")
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 7, 20)
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id)
    db.commit()

    assert contexto_ficha(db, [of], hoy=dt.date(2026, 8, 3))[of.id]["generacion"] is None


def test_lo_borrado_no_alimenta_la_ficha(db):
    """Un contrato o un proyecto con deleted_at ya no son la verdad de nadie."""
    proy = Proyecto(nombre_comercial="Planta borrada",
                    deleted_at=dt.datetime(2026, 7, 1))
    db.add(proy); db.flush()
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2030, 12, 31),
                      deleted_at=dt.datetime(2026, 7, 1))
    db.add(ppa); db.flush()
    _, of = _cliente_con_oferta(db, proyecto_id=proy.id, ppa_contrato_id=ppa.id)
    db.commit()

    ctx = contexto_ficha(db, [of])
    assert ctx[of.id]["proyecto"] is None and ctx[of.id]["ppa"] is None


def test_sin_ofertas_el_contexto_es_vacio(db):
    assert contexto_ficha(db, []) == {}


def test_una_oferta_sin_nada_enlazado_no_rompe(db):
    _, of = _cliente_con_oferta(db, planta_nombre="GD Rio Pamplonita")
    db.commit()
    ctx = contexto_ficha(db, [of])
    assert ctx[of.id] == {"proyecto": None, "ppa": None, "generacion": None,
                          "operador_oferta": None}
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: FAIL en el import — `ImportError: cannot import name 'contexto_ficha'`.

- [ ] **Step 3: Implementar el cargador por lotes**

En `app/services/comercial.py`, al final del archivo:

```python
def contexto_ficha(db, ofertas, hoy=None) -> dict[int, dict]:
    """Precarga lo que ficha_operativa() necesita: {oferta_id: kwargs}.

    Un número FIJO de consultas sin importar cuántas ofertas entren. Resolver
    esto dentro del bucle sería N+1 justo en la vista principal de /comercial,
    que carga todas las ofertas de una.

    Las llaves de cada valor son los nombres de los parámetros de
    ficha_operativa, para poder llamarla como ficha_operativa(o, **ctx[o.id]).
    """
    from sqlalchemy.orm import selectinload
    from app.models.proyectos import Proyecto
    from app.models.fronteras import Frontera
    from app.models.contratos import PPAContrato
    from app.models.operadores_red import OperadorRed

    ofertas = list(ofertas)
    if not ofertas:
        return {}

    proyecto_ids = {o.proyecto_id for o in ofertas if o.proyecto_id}
    ppa_ids = {o.ppa_contrato_id for o in ofertas if o.ppa_contrato_id}
    operador_ids = {o.operador_red_id for o in ofertas if o.operador_red_id}

    proyectos = {}
    if proyecto_ids:
        # operador y fronteras.operador precargados: Proyecto.operador_red_legal
        # los recorre y sin esto haría dos consultas por proyecto.
        proyectos = {
            p.id: p for p in db.query(Proyecto)
            .options(selectinload(Proyecto.operador),
                     selectinload(Proyecto.fronteras).selectinload(Frontera.operador))
            .filter(Proyecto.id.in_(proyecto_ids),
                    Proyecto.deleted_at.is_(None)).all()
        }
    ppas = {}
    if ppa_ids:
        # Un contrato borrado no alimenta la ficha: la oferta conserva el FK pero
        # sus fechas ya no son la verdad de nadie.
        ppas = {c.id: c for c in db.query(PPAContrato)
                .filter(PPAContrato.id.in_(ppa_ids),
                        PPAContrato.deleted_at.is_(None)).all()}
    operadores = {}
    if operador_ids:
        operadores = dict(
            db.query(OperadorRed.id, OperadorRed.nombre_legal)
            .filter(OperadorRed.id.in_(operador_ids)).all())

    generacion = _ultimo_mes_generacion(db, proyecto_ids, hoy=hoy)

    return {
        o.id: {
            "proyecto": proyectos.get(o.proyecto_id),
            "ppa": ppas.get(o.ppa_contrato_id),
            "generacion": generacion.get(o.proyecto_id),
            "operador_oferta": operadores.get(o.operador_red_id),
        }
        for o in ofertas
    }


def _ultimo_mes_generacion(db, proyecto_ids, hoy=None) -> dict[int, tuple[str, float]]:
    """Último mes CERRADO con lecturas por proyecto: {proyecto_id: ('2026-07', kwh)}.

    Dos exclusiones a propósito, las dos por lo mismo — un número parcial
    presentado como "energía real del mes" es peor que no dar número:
      · el mes en curso no cuenta (tres días de agosto no son un mes);
      · un mes con menos de 28 días de lectura tampoco.
    Una sola consulta agregada para todos los proyectos.
    """
    from sqlalchemy import extract, func as sa_func
    from app.models.generacion import GeneracionDiaria

    if not proyecto_ids:
        return {}
    hoy = hoy or col_now().date()
    primero_del_mes = hoy.replace(day=1)
    anio = extract("year", GeneracionDiaria.fecha)
    mes = extract("month", GeneracionDiaria.fecha)
    filas = (
        db.query(GeneracionDiaria.proyecto_id, anio.label("anio"), mes.label("mes"),
                 sa_func.sum(GeneracionDiaria.kwh_real).label("kwh"))
        .filter(GeneracionDiaria.proyecto_id.in_(proyecto_ids),
                GeneracionDiaria.kwh_real.isnot(None),
                GeneracionDiaria.fecha < primero_del_mes)
        .group_by(GeneracionDiaria.proyecto_id, anio, mes)
        .having(sa_func.count(GeneracionDiaria.id) >= 28)
        .all()
    )
    out: dict[int, tuple[str, float]] = {}
    for proyecto_id, a, m, kwh in filas:
        periodo = f"{int(a):04d}-{int(m):02d}"
        if proyecto_id not in out or periodo > out[proyecto_id][0]:
            out[proyecto_id] = (periodo, float(kwh))
    return out
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: PASS (21 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/comercial.py tests/test_comercial_ficha_operativa.py
git commit -m "feat(comercial): contexto_ficha() precarga la ficha por lotes"
```

---

### Task 4: Exponer la ficha en la API y hacer editables los 4 campos

**Files:**
- Modify: `app/schemas/comercial.py` (`OfertaCreate` línea 111-124, `OfertaUpdate` línea 127-139)
- Modify: `app/api/v1/comercial.py` (import línea 36-38; `_oferta_out` línea 118; `list_ofertas_todas` línea 345-353; `get_oportunidad` línea 449-484; `list_ofertas` línea 659-664; `create_oferta` línea 674-687; `update_oferta` línea 696-702)
- Test: `tests/test_comercial_ficha_operativa.py` (agregar al final)

**Interfaces:**
- Consumes: `ficha_operativa()` y `contexto_ficha()` de las tareas 2 y 3.
- Produces: la llave `"ficha"` en cada oferta serializada por `_oferta_out()`, más las 4 columnas declaradas en crudo (`municipio`, `departamento`, `operador_red_id`, `energia_promedio_kwh_mes`) para que el editor sepa distinguir lo declarado de lo resuelto.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_comercial_ficha_operativa.py`:

```python
# ── Task 4: la ficha viaja por la API ────────────────────────────────────────

from fastapi import HTTPException  # noqa: E402

from app.api.v1 import comercial as api  # noqa: E402
from app.schemas.comercial import (  # noqa: E402
    FirmarOfertaIn, OfertaCreate, OfertaUpdate, OportunidadCreate,
)


def test_la_ficha_viaja_en_la_lista_plana_de_ofertas(db):
    """La lista plana es la fuente de la vista principal de /comercial y es la
    que el equipo va a consumir por API."""
    orr = OperadorRed(nombre_legal="AFINIA S.A.S. E.S.P.")
    db.add(orr); db.flush()
    cli = Cliente(razon_social_nombre="INVERSIONES TECNI-PLAST S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Las Margaritas 1",
        municipio="Sincelejo", departamento="Sucre", operador_red_id=orr.id,
        energia_promedio_kwh_mes=185000,
        fecha_tentativa_inicio=dt.date(2026, 10, 1)), db=db, current=ADMIN)

    fila = api.list_ofertas_todas(db=db, current=ADMIN)[0]
    ficha = fila["ficha"]
    assert ficha["proyecto_nombre"] == "GD Las Margaritas 1"
    assert ficha["municipio"] == "Sincelejo"
    assert ficha["operador_red"] == "AFINIA S.A.S. E.S.P."
    assert ficha["energia_promedio_kwh_mes"] == 185000.0
    assert ficha["fecha_inicio_operacion"] == dt.date(2026, 10, 1)
    assert ficha["fuentes"]["fecha_inicio_operacion"] == "estimada"
    # y lo declarado en crudo, para que el editor sepa qué es suyo
    assert fila["municipio"] == "Sincelejo" and fila["operador_red_id"] == orr.id


def test_la_ficha_viaja_en_el_detalle_de_la_oportunidad(db):
    cli = Cliente(razon_social_nombre="FONSAR S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="Agustín 1", municipio="Sabanalarga"),
        db=db, current=ADMIN)

    detalle = api.get_oportunidad(op["id"], db=db, current=ADMIN)
    assert detalle["ofertas"][0]["ficha"]["municipio"] == "Sabanalarga"
    assert detalle["ofertas"][0]["ficha"]["fuentes"]["municipio"] == "oferta"


def test_la_ficha_de_una_oferta_firmada_toma_la_fecha_y_la_duracion_del_ppa(db):
    cli = Cliente(razon_social_nombre="PELLETCO S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    of = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="Catedral"), db=db, current=ADMIN)
    api.firmar_oferta(of["id"], FirmarOfertaIn(
        fecha_inicio=dt.date(2026, 2, 12), fecha_fin=dt.date(2032, 12, 31),
        tarifa_base=308), db=db, current=ADMIN)

    ficha = api.list_ofertas_todas(db=db, current=ADMIN)[0]["ficha"]
    assert ficha["fecha_inicio_operacion"] == dt.date(2026, 2, 12)
    assert ficha["fuentes"]["fecha_inicio_operacion"] == "contrato"
    assert ficha["contrato_compra_meses"] == 83
    assert ficha["contrato_compra_anios"] == 6.9


def test_el_patch_escribe_los_campos_declarados(db):
    """Si no son editables, el equipo no puede llenarlos nunca."""
    orr = OperadorRed(nombre_legal="ESSA S.A. E.S.P.")
    db.add(orr); db.flush()
    cli = Cliente(razon_social_nombre="RECURSOS AGROPECUARIOS S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)
    of = api.create_oferta(op["id"], OfertaCreate(
        tipo="compra_energia", planta_nombre="GD Rio Pamplonita"), db=db, current=ADMIN)

    api.update_oferta(of["id"], OfertaUpdate(
        municipio="Cúcuta", departamento="Norte de Santander",
        operador_red_id=orr.id, energia_promedio_kwh_mes=95000),
        db=db, current=ADMIN)

    ficha = api.list_ofertas_todas(db=db, current=ADMIN)[0]["ficha"]
    assert ficha["municipio"] == "Cúcuta"
    assert ficha["operador_red"] == "ESSA S.A. E.S.P."
    assert ficha["energia_promedio_kwh_mes"] == 95000.0


def test_un_operador_de_red_inexistente_da_422(db):
    """Sin esto sería un IntegrityError 500 en producción."""
    cli = Cliente(razon_social_nombre="SONETEL S.A.S.")
    db.add(cli); db.flush()
    op = api.create_oportunidad(OportunidadCreate(cliente_id=cli.id), db=db, current=ADMIN)

    with pytest.raises(HTTPException) as e:
        api.create_oferta(op["id"], OfertaCreate(
            tipo="compra_energia", operador_red_id=9999), db=db, current=ADMIN)
    assert e.value.status_code == 422


def _oferta_completa(db, op_id, i):
    """Una oferta con proyecto, contrato y generación propios."""
    proy = Proyecto(nombre_comercial=f"Planta {i}", municipio="Corozal",
                    mwh_mes_estimado=100 + i)
    db.add(proy); db.flush()
    _generacion(db, proy.id, 2026, 7, 31)
    ppa = PPAContrato(fecha_inicio=dt.date(2026, 1, 1), fecha_fin=dt.date(2030, 12, 31))
    db.add(ppa); db.flush()
    of = OportunidadOferta(oportunidad_id=op_id, tipo="compra_energia",
                           planta_nombre=f"Planta {i}", proyecto_id=proy.id,
                           ppa_contrato_id=ppa.id)
    db.add(of); db.commit()


def test_la_lista_no_hace_una_consulta_por_oferta(db):
    """La vista principal carga TODAS las ofertas de una: si la ficha costara una
    consulta por fila, esto se caería con el volumen real."""
    cli = Cliente(razon_social_nombre="GRUPO CON MUCHAS PLANTAS S.A.S.")
    db.add(cli); db.flush()
    op = Oportunidad(cliente_id=cli.id, estado="oportunidad")
    db.add(op); db.commit()
    for i in range(2):
        _oferta_completa(db, op.id, i)

    consultas = {"n": 0}

    @event.listens_for(db.get_bind(), "after_cursor_execute")
    def _contar(*args, **kwargs):
        consultas["n"] += 1

    api.list_ofertas_todas(db=db, current=ADMIN)
    con_dos = consultas["n"]

    for i in range(2, 8):
        _oferta_completa(db, op.id, i)
    consultas["n"] = 0
    filas = api.list_ofertas_todas(db=db, current=ADMIN)
    con_ocho = consultas["n"]   # leerlo ANTES de cualquier otra llamada

    assert len(filas) == 8
    assert con_ocho == con_dos, (
        f"{con_dos} consultas con 2 ofertas y {con_ocho} con 8: hay N+1")
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: FAIL — `pydantic_core.ValidationError: Unexpected keyword argument 'municipio'` en `OfertaCreate`.

- [ ] **Step 3: Agregar los 4 campos a los schemas**

En `app/schemas/comercial.py`, dentro de `OfertaCreate`, **antes** de `notas` (línea 124):

```python
    # ── Ficha operativa declarada (2026-08-03) ───────────────────────────────
    # Solo aplican cuando la planta no existe como Proyecto: si lo tiene, manda
    # el Proyecto (ver ficha_operativa). Editables porque si no, el equipo no
    # puede llenarlos nunca.
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    operador_red_id: Optional[int] = None
    energia_promedio_kwh_mes: Optional[float] = Field(None, ge=0)
```

Y las mismas 4 líneas (sin repetir el comentario largo; basta `# Ficha operativa declarada — ver OfertaCreate`) dentro de `OfertaUpdate`, antes de `notas` (línea 139):

```python
    # Ficha operativa declarada — ver OfertaCreate.
    municipio: Optional[str] = None
    departamento: Optional[str] = None
    operador_red_id: Optional[int] = None
    energia_promedio_kwh_mes: Optional[float] = Field(None, ge=0)
```

- [ ] **Step 4: Cablear la ficha en el router**

En `app/api/v1/comercial.py`:

**4.1** — Ampliar el import de servicios (línea 36-38):

```python
from app.services.comercial import (
    calcular_alerta, col_now, contexto_ficha, estado_a_resultado, ficha_operativa,
    resumen_etapas,
)
```

**4.2** — `_oferta_out` (línea 118) recibe la ficha ya resuelta y suma los campos declarados:

```python
def _oferta_out(o: OportunidadOferta, ficha: dict | None = None) -> dict:
    return {
        "id": o.id, "oportunidad_id": o.oportunidad_id,
        "tipo": _valor(o.tipo),
        "planta_nombre": o.planta_nombre, "proyecto_id": o.proyecto_id,
        "numero_oferta": o.numero_oferta,
        "codigo_seguimiento": _norm_codigo(o.numero_oferta),
        "precio_detalle": o.precio_detalle,
        # Etapa propia de la oferta. `resultado` se deriva de ella y viaja solo
        # para que no se rompa lo que ya lo leía.
        "estado": _valor(o.estado),
        "estado_desde": o.estado_desde,
        "resultado": _valor(o.resultado),
        "etapa_texto": o.etapa_texto, "fecha_oferta": o.fecha_oferta,
        "fecha_tentativa_inicio": o.fecha_tentativa_inicio,
        "contrato_firmado": o.contrato_firmado, "detalle": o.detalle, "notas": o.notas,
        "seguimientos": o.seguimientos or 0,
        "fecha_ultima_respuesta": o.fecha_ultima_respuesta,
        "documento_url": o.documento_url,
        # En qué contrato desembocó. Las condiciones viven allá, no aquí.
        "ppa_contrato_id": o.ppa_contrato_id,
        "contrato_servicio_id": o.contrato_servicio_id,
        # Lo DECLARADO en la oferta, en crudo: el editor necesita distinguirlo de
        # lo resuelto en `ficha` (que puede venir del Proyecto).
        "municipio": o.municipio,
        "departamento": o.departamento,
        "operador_red_id": o.operador_red_id,
        "energia_promedio_kwh_mes": (float(o.energia_promedio_kwh_mes)
                                     if o.energia_promedio_kwh_mes is not None else None),
        # Los 6 parámetros resueltos por cascada + de dónde salió cada uno.
        "ficha": ficha,
        "created_at": o.created_at, "updated_at": o.updated_at,
    }
```

**4.3** — Un helper para no repetir el par contexto+resolución. Agregarlo justo debajo de `_oferta_out`:

```python
def _fichas(db: Session, ofertas) -> dict[int, dict]:
    """{oferta_id: ficha} con la precarga por lotes hecha una sola vez."""
    ctx = contexto_ficha(db, ofertas)
    return {o.id: ficha_operativa(o, **ctx[o.id]) for o in ofertas}
```

**4.4** — `list_ofertas_todas`: reemplazar las líneas 345-353 (desde `filas = qy.order_by(...)` hasta `row = _oferta_out(of)`) por:

```python
    filas = qy.order_by(OportunidadOferta.updated_at.desc(), OportunidadOferta.id.desc()).all()
    fichas = _fichas(db, [of for of, _, _, _ in filas])
    out = []
    for of, op, cli, ultima in filas:
        # La alerta es de la oferta: cuenta desde que ENTRÓ a su etapa actual, no
        # desde que el cliente cambió de estado. Una oferta firmada ya no alerta
        # aunque su hermana lleve meses sin respuesta.
        dias, alerta = calcular_alerta(_valor(of.estado), of.estado_desde or op.estado_desde,
                                       ultima, settings.COMERCIAL_ALERTA_DIAS, ahora)
        row = _oferta_out(of, fichas[of.id])
```

**4.5** — `get_oportunidad`: reemplazar la línea 484 (`"ofertas": [_oferta_out(o) for o in op.ofertas],`) por:

```python
        "ofertas": [_oferta_out(o, fichas_op[o.id]) for o in op.ofertas],
```

y calcular `fichas_op` justo antes del `base.update({...}`, después de la línea 451:

```python
    fichas_op = _fichas(db, op.ofertas)
```

**4.6** — `list_ofertas` (línea 664): reemplazar `return [_oferta_out(o) for o in ofs]` por:

```python
    fichas = _fichas(db, ofs)
    return [_oferta_out(o, fichas[o.id]) for o in ofs]
```

**4.7** — Validación del operador y ficha en `create_oferta` / `update_oferta`. Agregar el helper debajo de `_get_oportunidad_or_404` (línea 57):

```python
def _validar_operador_red(db: Session, operador_red_id: int | None) -> None:
    """El FK al catálogo se valida aquí y no en la BD: sin esto, un id inventado
    revienta como IntegrityError 500 en vez de un 422 con mensaje."""
    if operador_red_id is None:
        return
    if not db.query(OperadorRed.id).filter(OperadorRed.id == operador_red_id).first():
        raise HTTPException(422, "operador_red_id no existe en el catálogo de operadores")
```

En `create_oferta`, después de `payload = data.model_dump()` (línea 674):

```python
    _validar_operador_red(db, payload.get("operador_red_id"))
```

y cambiar el `return` (línea 687) por:

```python
    return _oferta_out(o, _fichas(db, [o])[o.id])
```

En `update_oferta`, después de obtener `o` y antes del bucle de `setattr` (línea 698-699):

```python
    cambios = data.model_dump(exclude_unset=True)
    if "operador_red_id" in cambios:
        _validar_operador_red(db, cambios["operador_red_id"])
    for k, v in cambios.items():
        setattr(o, k, v)
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `pytest tests/test_comercial_ficha_operativa.py -v`
Expected: PASS (27 passed).

- [ ] **Step 6: Correr la suite completa — los tests viejos también leen `_oferta_out`**

Run: `pytest tests/ -q`
Expected: PASS — 721 passed. Si algún test de `tests/test_comercial_ofertas_api.py` o `tests/test_comercial_pipeline_oferta.py` falla por comparación exacta de diccionarios, **ajustar el test** para que compare las llaves que le importan (la ficha es aditiva, no cambia ningún valor existente).

- [ ] **Step 7: Commit**

```bash
git add app/api/v1/comercial.py app/schemas/comercial.py tests/test_comercial_ficha_operativa.py
git commit -m "feat(comercial): la API devuelve la ficha operativa de cada oferta"
```

---

### Task 5: El bloque `ficha` en el archivo de los 7 cierres

Las 4 llaves quedan en null a propósito: la estructura lista para que el cargador (pendiente, §6a del handoff) las escriba cuando haya información. Es exactamente lo que pidió Juan — "que se pueda consultar vía API a pesar de que ahora no haya info".

**Files:**
- Modify: `data/comercial_cierres_2026-08.json` (los 7 objetos de `cierres` y el bloque `_notas`)
- Modify: `../comercial_jake/comercial_cierres_2026-08.json` (copia de lectura, se sincroniza al final)

**Interfaces:**
- Consumes: los nombres de columna de la Task 1.
- Produces: `cierres[].ficha` con `municipio`, `departamento`, `operador_red_id`, `energia_promedio_kwh_mes`.

- [ ] **Step 1: Agregar la nota que explica el bloque**

En `data/comercial_cierres_2026-08.json`, dentro de `_notas`, después de `"biosolar_sin_energia"`:

```json
    "ficha": "Bloque de la ficha operativa (2026-08-03) con las 4 llaves en null. Los 6 parametros que el equipo consulta por API se resuelven por cascada Proyecto -> declarado en la oferta -> null; ninguna de estas 7 plantas tiene Proyecto todavia, asi que aqui es donde se declaran cuando Juan confirme los datos. energia_promedio_kwh_mes es la generacion mensual ESTIMADA, no el cantidad_minima_kwh_mes del contrato."
```

- [ ] **Step 2: Agregar el bloque a los 7 cierres**

En **cada uno** de los 7 objetos de `cierres`, después de su bloque `"contrato": {...}` y antes de `"nota"`:

```json
      "ficha": {
        "municipio": null,
        "departamento": null,
        "operador_red_id": null,
        "energia_promedio_kwh_mes": null
      },
```

- [ ] **Step 3: Verificar que el JSON sigue siendo válido**

Run: `python -c "import json; d=json.load(open('data/comercial_cierres_2026-08.json', encoding='utf-8')); print(len(d['cierres']), 'cierres'); print(all('ficha' in c for c in d['cierres']))"`
Expected: `7 cierres` y `True`.

- [ ] **Step 4: Sincronizar la copia de lectura**

```bash
cp data/comercial_cierres_2026-08.json ../comercial_jake/comercial_cierres_2026-08.json
```

- [ ] **Step 5: Commit**

```bash
git add data/comercial_cierres_2026-08.json
git commit -m "chore(comercial): bloque ficha en los 7 cierres, listo para el cargador"
```

(La copia en `comercial_jake/` no está en este repo; queda actualizada en disco.)

---

## Verificación final

- [ ] **Suite completa**

Run: `pytest tests/ -q`
Expected: 721 passed (694 de línea base + 27 nuevos).

- [ ] **Migración contra Postgres real, idempotente en dos vueltas**

```bash
PYTHONIOENCODING=utf-8 python ../comercial_jake/verificar_migracion.py
```

El script crea una base desechable, reproduce el estado de producción y corre los DDL reales **dos veces** (la segunda prueba que un redeploy no revierte nada). Lo que hay que ver: que los 5 statements nuevos no lancen en la segunda vuelta.

**Caveat conocido, no es regresión de este trabajo:** el script todavía no incluye `terminado` en el enum esperado (se agregó después de escribirlo), así que ese assert puede fallar. Es la deuda que el handoff dejó anotada en §2. Si falla solo por eso, seguir adelante y anotarlo.

- [ ] **Revisar que no se coló nada ajeno**

Run: `git status --short`
Expected: los `??` de siempre siguen sin commitear — `backend_structure.html`, `docs/API_FALLAS.md`, `scripts/cargar_fronteras_comerciales.py`, `scripts/create_purchase_contracts.py`, `Guía de inicio — Plataforma Operaciones.md`. Ninguno de ellos es de este trabajo.

---

## Lo que este plan NO hace

- **La UI de edición.** Los 4 campos son editables por API (`POST`/`PATCH`), pero `OfertasPanel.vue` no los muestra. Decisión explícita de Juan (2026-08-03): backend primero. Sin ese segundo paso, el equipo solo puede llenarlos por API.
- **El cargador de los 7 cierres** (§6a del handoff). Sigue pendiente y es el siguiente frente natural: este plan le deja el bloque `ficha` listo para escribir.
- **Crear los `Proyecto` faltantes** (GD Rio Pamplonita, GD Las Margaritas 1). Bloqueado a propósito: el endpoint del CRM exige `operador_red_id` obligatorio y eso está pendiente de hablar con Sara sobre el flujo de sincronización con frontera. Este plan es justamente lo que permite no esperarla.
- **Confirmar las unidades de energía** de Bayunca (400.000) y Sonetel (170.000), que se asumieron mensuales. Sigue abierto con Juan.
