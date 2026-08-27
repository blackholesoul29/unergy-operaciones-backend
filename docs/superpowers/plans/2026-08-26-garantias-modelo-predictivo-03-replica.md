# Modelo Predictivo de Garantías — Plan 3: Carga del corpus y réplica del día 7

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cargar el corpus en las tablas del plan 2 y calcular la réplica determinística del día 7, de modo que la tab que ya está en producción muestre el número firme de XM en vez del estado vacío.

**Architecture:** Cargadores idempotentes que usan los parsers puros del plan 2; un servicio de réplica que lee `xm_medida` con el filtro anti-leakage y escribe `gar_componente_pred`; dos endpoints que sirven el contrato que el plan 1 congeló.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, PostgreSQL, pytest, openpyxl.

---

## Contexto: plan 3 de 4

| Plan | Alcance | Estado |
|---|---|---|
| 1 — Frontend | Vista de planeación | **hecho**, en producción |
| 2 — Ingesta | Esquema, parsers, validación | **hecho**, en master |
| **3 — Carga y réplica** (este) | Cargadores, réplica día 7, endpoints | listo para ejecutar |
| 4 — Estimador día 14 | Reconstrucción propia, residual, intervalo | pendiente |

El estimador del día 14 **no entra acá**. Este plan entrega el número **firme**: el que XM
ya publicó, reproducido desde los insumos. Con eso la tab muestra datos reales y el rango
llega después.

## Lo que ya está medido y este plan da por sentado

Todo verificado sobre el corpus real el 2026-08-26. No son supuestos.

| Hecho | Consecuencia |
|---|---|
| **La réplica del día 7 da error mediano de 0,0057%** sobre 70 períodos (39/70 dentro de 0,01%) | La aritmética está resuelta. Si el backtest de este plan da mucho peor, el bug está en la carga, no en la fórmula |
| **XM define Exposición como `compras − ventas`** | Invertido produce ceros donde hay deuda, sin fallar |
| Hay **536 días con los cuatro insumos en `.tx2`**, 2025-01-01 → 2026-07-29 | Ese es el rango calculable |
| `dspcttos` reproduce `CONTRATO DE VENTA` **exacto, 538/538 días** | El despacho no es aproximación |
| Los otros 17 componentes son **casi constantes**: el error de usar el período anterior es 0,9% (TX2), 4,3% (PROY) y 0,0% (M+1) de σ(Exposición) | El agregado por persistencia es casi exacto |
| El producto energía × precio va **hora a hora**, no agregando a día primero | En solar la exposición horaria correlaciona fuerte con el precio horario |

## La regla de `disponible_desde`, que el plan 2 dejó abierta

`preparar_archivo` se niega a inventar la fecha de disponibilidad: si no se la dan,
marca el archivo `esquema_ok = False`. **Este plan tiene que suministrarla**, y la regla
sale del timeline declarado por XM, no de una suposición:

> Para el vencimiento del 28-AGO, la ventana base cierra el **14-AGO** y XM calcula el
> **21-AGO** usando datos en versión TX2 de esos días. Luego un `.tx2` del día D está
> disponible a más tardar **D + 7**.

```
disponible_desde = fecha_documento + 7 días     (para .tx2)
origen_disponibilidad = "derivado"
```

**Por qué errar por exceso es seguro.** La asimetría manda: un lag más grande de la
cuenta solo **excluye** datos que sí estaban disponibles — hace el backtest pesimista.
Un lag más chico **filtra** datos que no existían — invalida el backtest sin que nada
falle. Ante la duda, agrandar.

**Solo se carga `.tx2` en este plan.** El `.tx1` (516 días de `trsd`) habilita estimar
antes del día 14 y entra en el plan 4, con su propio lag. El `.txf` no se carga: es
posterior al cálculo y solo serviría para medir revisiones.

## Convenciones del repo

**Antes de tocar nada:**

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```

Si el segundo número no es `0`, `git pull --rebase origin master`. Este repo se atrasa
muy rápido — durante el plan 2 hubo que rebasar seis veces.

**Tests:** `python -m pytest -q`. Línea base verificada el 2026-08-27 sobre `origin/master`: **2107 passed, 1 skipped** en 56 s.
(El plan 2 cerró en 2092; los 62 commits que entraron después sumaron 15 pruebas.)

**Esquema:** las cinco tablas ya existen vía modelo + `create_all`. Este plan **no crea
tablas ni toca `_PENDING_DDLS`**. Si hiciera falta una columna nueva — no debería —, va
por revisión de Alembic con los helpers de `alembic_idempotencia.py`.

**Producción no se escribe desde local.** El `.env` local no apunta ahí. La carga masiva
del corpus corre como comando manual contra la base local, o como tarea `*_seed` en
`_deferred_init` dentro del contenedor.

**Tests en SQLite:** 104 de 130 archivos usan `sqlite:///:memory:`, con `JSONB → TEXT`.
Los tests de los cargadores deben verificar el **comportamiento** (qué filas se
insertan, que reingerir no duplique), no el tipo de la columna.

**Zona horaria:** el contenedor corre en UTC y Colombia es UTC−5. Usar `_hoy_col()`.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/services/garantias_modelo/cargador.py` | **Crear.** Insumos FTP → `XMArchivo` + `XMMedida`, idempotente. |
| `app/services/garantias_modelo/cargador_targets.py` | **Crear.** Excel de garantía → `GarCalculo` + `GarComponenteReal`. |
| `app/services/garantias_modelo/replica.py` | **Crear.** Puro: exposición desde series horarias. |
| `app/services/garantias_modelo/motor.py` | **Crear.** Orquesta: lee la base con el filtro anti-leakage, escribe `GarComponentePred`. |
| `app/services/garantias_modelo/backtest.py` | **Crear.** Compara pred vs real y reporta error por componente. |
| `app/api/v1/garantias_modelo.py` | **Crear.** Los dos endpoints del contrato. Solo transporte. |
| `app/api/v1/router.py` | **Modificar.** Registrar el router. |
| `scripts/cargar_corpus_garantias.py` | **Crear.** Comando de carga masiva. |
| `tests/test_gar_modelo_replica.py` | **Crear.** |
| `tests/test_gar_modelo_cargador.py` | **Crear.** |
| `tests/test_gar_modelo_backtest.py` | **Crear.** |
| `tests/test_gar_modelo_endpoints.py` | **Crear.** |

`replica.py` y `backtest.py` son **puros**: reciben series y devuelven números. Eso los
hace testeables sin base, que es como está el resto del repo.

---

## Task 1: La réplica, como función pura

**Files:**
- Create: `app/services/garantias_modelo/replica.py`
- Test: `tests/test_gar_modelo_replica.py`

Es el corazón del sistema y no necesita base de datos: recibe series horarias y devuelve
pesos.

- [x] **Step 1: Escribir el test que falla**

```python
"""La réplica de Exposición Energía en Bolsa, como aritmética pura.

Validada contra XM con error mediano de 0,0057% sobre 70 períodos. El signo y la
granularidad horaria no son detalles: invertir el signo produce ceros donde hay deuda,
y agregar a día antes de multiplicar da otro número.
"""
import datetime

import pytest

from app.services.garantias_modelo.replica import (
    exposicion_dia,
    exposicion_periodo,
    precio_implicito,
)

D1 = datetime.date(2026, 8, 1)
D2 = datetime.date(2026, 8, 2)


def test_exposicion_dia_es_compras_menos_ventas():
    # Convención de XM: positivo = comprador neto = se debe dinero = sube la garantía.
    r = exposicion_dia(compras=[10.0] * 24, ventas=[4.0] * 24, precio=[100.0] * 24)
    assert r == pytest.approx(6.0 * 100.0 * 24)


def test_exposicion_dia_vendedor_neto_da_negativo():
    r = exposicion_dia(compras=[1.0] * 24, ventas=[5.0] * 24, precio=[100.0] * 24)
    assert r < 0


def test_exposicion_es_horaria_no_diaria():
    """El producto va hora a hora. Agregar a día primero da otro número cuando la
    energía correlaciona con el precio, que es el caso solar."""
    compras = [0.0] * 12 + [10.0] * 12
    ventas = [0.0] * 24
    precio = [50.0] * 12 + [200.0] * 12          # caro justo cuando hay energía
    horaria = exposicion_dia(compras=compras, ventas=ventas, precio=precio)
    neto_dia = sum(compras) - sum(ventas)
    precio_medio = sum(precio) / 24
    diaria = neto_dia * precio_medio
    assert horaria == pytest.approx(10.0 * 200.0 * 12)
    assert horaria != pytest.approx(diaria)


def test_exposicion_periodo_suma_los_dias():
    dias = {
        D1: {"compras": [10.0] * 24, "ventas": [4.0] * 24, "precio": [100.0] * 24},
        D2: {"compras": [10.0] * 24, "ventas": [4.0] * 24, "precio": [100.0] * 24},
    }
    assert exposicion_periodo(dias) == pytest.approx(2 * 6.0 * 100.0 * 24)


def test_exposicion_periodo_vacio_es_cero():
    assert exposicion_periodo({}) == 0.0


def test_exposicion_dia_longitudes_distintas_falla_ruidosamente():
    with pytest.raises(ValueError):
        exposicion_dia(compras=[1.0] * 24, ventas=[1.0] * 23, precio=[1.0] * 24)


def test_precio_implicito_reconcilia():
    """El precio implícito debe coincidir con el Precio de Bolsa Ponderado de XM.
    Si no coincide de forma sistemática, la ventana o los datos están mal."""
    r = precio_implicito(energia=[10.0] * 12 + [30.0] * 12,
                         precio=[100.0] * 12 + [200.0] * 12)
    assert r == pytest.approx((10 * 100 * 12 + 30 * 200 * 12) / (10 * 12 + 30 * 12))


def test_precio_implicito_sin_energia_es_none():
    assert precio_implicito(energia=[0.0] * 24, precio=[100.0] * 24) is None
```

- [x] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_replica.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `replica`

- [x] **Step 3: Implementar**

```python
"""Réplica determinística de Exposición Energía en Bolsa.

Puro: recibe series horarias y devuelve pesos. No toca la base.

Validada contra los valores publicados por XM sobre 70 períodos: error mediano de
0,0057% (536 COP sobre cifras de decenas de millones), 39/70 dentro de 0,01%.

Dos cosas que no son detalles de estilo:

1. **El signo es `compras − ventas`.** Positivo = comprador neto = se debe dinero = sube
   la garantía. Invertirlo produce ceros donde hay deuda, y el piso en cero lo esconde.
2. **El producto va hora a hora.** Agregar a día y multiplicar por un precio diario da
   otro número siempre que la energía correlacione con el precio — y en solar
   correlaciona fuerte, porque generamos al mediodía.
"""
from __future__ import annotations

import datetime

HORAS = 24


def exposicion_dia(*, compras: list[float], ventas: list[float],
                   precio: list[float]) -> float:
    """Exposición de un día en COP, sumando hora a hora.

    Falla ruidosamente si las series no tienen la misma longitud: una serie corta
    silenciosamente truncada daría un número plausible y equivocado.
    """
    if not (len(compras) == len(ventas) == len(precio)):
        raise ValueError(
            f"series de distinta longitud: compras={len(compras)} "
            f"ventas={len(ventas)} precio={len(precio)}")
    return sum((compras[h] - ventas[h]) * precio[h] for h in range(len(compras)))


def exposicion_periodo(dias: dict[datetime.date, dict[str, list[float]]]) -> float:
    """Suma la exposición de cada día de la ventana. `{}` -> 0.0."""
    return sum(
        exposicion_dia(compras=d["compras"], ventas=d["ventas"], precio=d["precio"])
        for d in dias.values()
    )


def precio_implicito(*, energia: list[float], precio: list[float]) -> float | None:
    """Precio ponderado por energía: `Σ(e·p) / Σe`.

    Sirve de check de reconciliación contra el *Precio de Bolsa Ponderado* que publica
    XM. Si no coincide de forma sistemática, la ventana o los datos están mal — no el
    precio. `None` cuando no hubo energía, que no es lo mismo que un precio de cero.
    """
    total = sum(energia)
    if not total:
        return None
    return sum(energia[i] * precio[i] for i in range(len(energia))) / total
```

- [x] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_replica.py -q`
Expected: `8 passed`

- [x] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/replica.py tests/test_gar_modelo_replica.py
git commit -m "feat(garantias): la replica de exposicion como funcion pura"
```

---

## Task 2: Cargador de insumos FTP

**Files:**
- Create: `app/services/garantias_modelo/cargador.py`
- Test: `tests/test_gar_modelo_cargador.py`

Toma los archivos ya parseados y los persiste. **Acá se suministra `disponible_desde`**,
que el plan 2 se niega a inventar.

- [x] **Step 1: Escribir el test que falla**

```python
"""Carga de insumos FTP: idempotencia y la regla de disponible_desde."""
import datetime

import pytest

from app.services.garantias_modelo.cargador import (
    LAG_POR_VERSION,
    disponible_desde_derivado,
    filas_a_medidas,
)

FECHA = datetime.date(2026, 8, 14)


def test_lag_de_tx2_es_siete_dias():
    """Sale del timeline de XM: la ventana cierra 14 días antes del vencimiento y XM
    calcula 7 días antes, usando TX2 de esos días."""
    assert LAG_POR_VERSION["tx2"] == 7


def test_disponible_desde_derivado_suma_el_lag():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.date() == datetime.date(2026, 8, 21)


def test_disponible_desde_derivado_es_utc():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.tzinfo is not None


def test_version_sin_lag_conocido_falla_ruidosamente():
    """Errar por exceso es seguro, inventar no. Una versión desconocida se rechaza."""
    with pytest.raises(ValueError):
        disponible_desde_derivado(FECHA, "txz")


def test_filas_a_medidas_asigna_el_archivo():
    filas = [{"tipo": "trsd", "fecha_documento": FECHA, "hora": 1, "entidad": "NACIONAL",
              "concepto": "pbna", "concepto_raw": "PBNA", "valor": 250.5, "version": "tx2"}]
    r = filas_a_medidas(filas, archivo_id=42)
    assert len(r) == 1
    assert r[0]["archivo_id"] == 42
    assert r[0]["concepto"] == "pbna"


def test_filas_a_medidas_vacio():
    assert filas_a_medidas([], archivo_id=1) == []
```

- [x] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_cargador.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `cargador`

- [x] **Step 3: Implementar**

```python
"""Carga de insumos de XM a `xm_archivo` + `xm_medida`.

La idempotencia es por `sha256` del contenido en `xm_archivo` y por la clave natural en
`xm_medida`. Reingerir el mismo corpus no duplica filas.
"""
from __future__ import annotations

import datetime

# Días entre la fecha del documento y el momento en que esa versión está disponible.
#
# El de `tx2` no es una suposición: sale del timeline que XM declara. Para el
# vencimiento del 28-AGO la ventana base cierra el 14-AGO y XM calcula el 21-AGO usando
# datos en versión TX2 de esos días — luego un `.tx2` del día D está disponible a más
# tardar D+7.
#
# Errar por exceso es seguro: un lag más grande solo EXCLUYE datos que sí estaban
# disponibles y hace el backtest pesimista. Uno más chico FILTRA datos que no existían e
# invalida el backtest sin que nada falle. Ante la duda, agrandar.
LAG_POR_VERSION = {
    "tx2": 7,
}


def disponible_desde_derivado(fecha_documento: datetime.date,
                              version: str) -> datetime.datetime:
    """`fecha_documento + lag`, en UTC. Falla si la versión no tiene lag conocido.

    No hay valor por defecto a propósito: inventar un lag para una versión que no
    medimos es exactamente el error que este diseño evita.
    """
    lag = LAG_POR_VERSION.get((version or "").lower())
    if lag is None:
        raise ValueError(
            f"sin lag conocido para la versión {version!r}: no se puede derivar "
            f"disponible_desde. Agregarlo a LAG_POR_VERSION solo con evidencia.")
    return datetime.datetime.combine(
        fecha_documento + datetime.timedelta(days=lag),
        datetime.time.min,
        tzinfo=datetime.timezone.utc,
    )


def filas_a_medidas(filas: list[dict], *, archivo_id: int) -> list[dict]:
    """Anexa `archivo_id` a las filas que devolvió un parser, listas para `xm_medida`."""
    return [dict(f, archivo_id=archivo_id) for f in filas]
```

- [x] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_cargador.py -q`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/cargador.py tests/test_gar_modelo_cargador.py
git commit -m "feat(garantias): cargador de insumos con la regla de disponible_desde"
```

---

## Task 3: Backtest, como función pura

**Files:**
- Create: `app/services/garantias_modelo/backtest.py`
- Test: `tests/test_gar_modelo_backtest.py`

- [x] **Step 1: Escribir el test que falla**

```python
"""Backtest: error por componente, no solo del total."""
import pytest

from app.services.garantias_modelo.backtest import (
    error_relativo,
    resumen_error,
)


def test_error_relativo_normal():
    assert error_relativo(predicho=110.0, real=100.0) == pytest.approx(10.0)


def test_error_relativo_usa_valor_absoluto_del_real():
    """El real puede ser negativo; el error no debe cambiar de signo por eso."""
    assert error_relativo(predicho=-110.0, real=-100.0) == pytest.approx(10.0)


def test_error_relativo_real_cero_es_none():
    """Dividir por un real de cero da infinito y contamina la mediana. La exposición
    neta es un residuo pequeño de números grandes: cerca de cero, el porcentaje engaña."""
    assert error_relativo(predicho=5.0, real=0.0) is None


def test_resumen_error_reporta_mediana_y_percentiles():
    r = resumen_error([1.0, 2.0, 3.0, 4.0, 100.0])
    assert r["n"] == 5
    assert r["mediana"] == pytest.approx(3.0)
    assert r["max"] == pytest.approx(100.0)


def test_resumen_error_ignora_none():
    r = resumen_error([1.0, None, 3.0])
    assert r["n"] == 2


def test_resumen_error_vacio():
    r = resumen_error([])
    assert r["n"] == 0
    assert r["mediana"] is None


def test_resumen_error_cuenta_dentro_de_umbrales():
    r = resumen_error([0.001, 0.5, 3.0, 20.0])
    assert r["dentro_0_01"] == 1
    assert r["dentro_1"] == 2
    assert r["dentro_5"] == 3
```

- [x] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_backtest.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `backtest`

- [x] **Step 3: Implementar**

```python
"""Métricas del backtest, puras.

Se reporta el error **por componente**, no solo del total: así se sabe qué pieza falla
en vez de saber únicamente que el total no cuadra.
"""
from __future__ import annotations

import statistics as st

UMBRALES = (0.01, 1.0, 5.0)


def error_relativo(*, predicho: float, real: float) -> float | None:
    """Error porcentual absoluto. `None` cuando el real es cero.

    No se devuelve infinito ni un número enorme: la exposición neta es un residuo
    pequeño de números grandes, así que cerca de cero cualquier diferencia mínima da un
    porcentaje absurdo que contamina la mediana. Un real de cero no es comparable en
    porcentaje y se reporta aparte.
    """
    if not real:
        return None
    return abs(predicho - real) / abs(real) * 100.0


def resumen_error(errores: list[float | None]) -> dict:
    """Mediana, percentiles y conteos por umbral. Los `None` se descartan y no cuentan."""
    v = sorted(e for e in errores if e is not None)
    if not v:
        return {"n": 0, "mediana": None, "p90": None, "max": None,
                **{f"dentro_{str(u).replace('.', '_')}": 0 for u in UMBRALES}}
    return {
        "n": len(v),
        "mediana": st.median(v),
        "p90": v[min(len(v) - 1, int(len(v) * 0.9))],
        "max": max(v),
        **{f"dentro_{str(u).replace('.', '_')}": sum(1 for x in v if x < u)
           for u in UMBRALES},
    }
```

- [x] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_backtest.py -q`
Expected: `7 passed`

- [x] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/backtest.py tests/test_gar_modelo_backtest.py
git commit -m "feat(garantias): metricas de backtest por componente"
```

---

## Task 4: El motor — lectura con filtro anti-leakage

**Files:**
- Create: `app/services/garantias_modelo/motor.py`

Es el único módulo de este plan que toca la base. Su responsabilidad: para un
`GarCalculo`, leer de `xm_medida` **solo lo disponible en su `fecha_calculo`**, armar las
series horarias y llamar a `replica.exposicion_periodo`.

- [x] **Step 1: Implementar**

```python
"""Motor de la réplica: lee la base con el filtro anti-leakage y calcula.

**El filtro anti-leakage es una sola condición y vive acá:**

    XMArchivo.disponible_desde <= calculo.fecha_calculo

Todo lo demás del diseño existe para que esa línea sea correcta. Si se relaja, el
backtest da resultados que se ven bien y son falsos — el único bug del proyecto que no
avisa.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.garantias_modelo import GarCalculo, XMArchivo, XMMedida
from app.services.garantias_modelo.replica import exposicion_periodo

HORAS = 24

# Conceptos y entidades, verificados contra archivos reales el 2026-08-27 sobre
# `BalCttos0101.tx2` y `trsd0101.tx2` — no son suposiciones. Si alguno no coincide, el
# motor devuelve 0.0 sin fallar, que es el peor resultado posible.
#
#   BalCttos.tx2 -> entidad "UNGG", horas 1..24, 24 filas por concepto. Conceptos
#   normalizados presentes: compras en bolsa / contrato de venta / generacion ideal /
#   neto de compras en bolsa / neto de ventas en bolsa /
#   perdidas asignadas a un generador / ventas en bolsa
#
#   trsd.tx2 -> entidad "NACIONAL", horas 1..24. `pbna` está entre los 33 códigos.
_NETO_COMPRAS = "neto de compras en bolsa"
_NETO_VENTAS = "neto de ventas en bolsa"
_PBNA = "pbna"


def _series(db: Session, *, tipo: str, concepto: str, entidad: str | None,
            desde: datetime.date, hasta: datetime.date,
            corte: datetime.date, version: str = "tx2"
            ) -> dict[datetime.date, list[float]]:
    """Serie horaria por día, filtrada por disponibilidad a `corte`."""
    q = (
        select(XMMedida.fecha_documento, XMMedida.hora, XMMedida.valor)
        .join(XMArchivo, XMMedida.archivo_id == XMArchivo.id)
        .where(
            XMMedida.tipo == tipo,
            XMMedida.concepto == concepto,
            XMMedida.version == version,
            XMMedida.fecha_documento >= desde,
            XMMedida.fecha_documento <= hasta,
            XMArchivo.esquema_ok.is_(True),
            XMArchivo.disponible_desde <= datetime.datetime.combine(
                corte, datetime.time.max, tzinfo=datetime.timezone.utc),
        )
    )
    if entidad is not None:
        q = q.where(XMMedida.entidad == entidad)

    salida: dict[datetime.date, list[float]] = {}
    for fecha, hora, valor in db.execute(q):
        salida.setdefault(fecha, [0.0] * HORAS)
        if 1 <= hora <= HORAS:
            salida[fecha][hora - 1] = float(valor)
    return salida


def exposicion_de_calculo(db: Session, calculo: GarCalculo) -> dict:
    """Exposición en COP del período de `calculo`, con el filtro anti-leakage aplicado.

    Devuelve también los días efectivamente usados: un período al que le faltan días
    produce un número menor, y eso hay que verlo, no descubrirlo después.
    """
    corte = calculo.fecha_calculo or calculo.fecha_vencimiento
    comun = dict(desde=calculo.periodo_ini, hasta=calculo.periodo_fin, corte=corte)

    compras = _series(db, tipo="balcttos", concepto=_NETO_COMPRAS,
                      entidad=calculo.agente, **comun)
    ventas = _series(db, tipo="balcttos", concepto=_NETO_VENTAS,
                     entidad=calculo.agente, **comun)
    precio = _series(db, tipo="trsd", concepto=_PBNA, entidad="NACIONAL", **comun)

    dias_completos = sorted(set(compras) & set(precio))
    esperados = (calculo.periodo_fin - calculo.periodo_ini).days + 1

    armado = {
        d: {"compras": compras[d],
            "ventas": ventas.get(d, [0.0] * HORAS),
            "precio": precio[d]}
        for d in dias_completos
    }
    return {
        "valor": exposicion_periodo(armado),
        "dias_usados": len(dias_completos),
        "dias_esperados": esperados,
        "completo": len(dias_completos) == esperados,
    }
```

- [x] **Step 2: Verificar que importa y que la app sigue arrancando**

Run:
```bash
python -c "from app.services.garantias_modelo.motor import exposicion_de_calculo; print('ok')"
python -c "import app.main; print('ok')"
```
Expected: `ok` dos veces.

- [x] **Step 3: Correr la suite**

Run: `python -m pytest -q`
Expected: sin regresión.

- [x] **Step 4: Commit**

```bash
git add app/services/garantias_modelo/motor.py
git commit -m "feat(garantias): motor de la replica con el filtro anti-leakage"
```

---

## Task 5: Los dos endpoints

**Files:**
- Create: `app/api/v1/garantias_modelo.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/test_gar_modelo_endpoints.py`

El contrato lo congeló el plan 1 y está en
`unergy-operaciones-frontend-master/docs/superpowers/plans/2026-08-26-garantias-modelo-predictivo-01-frontend.md`.
**No cambiarlo:** el frontend ya está en producción consumiéndolo.

Dos notas del contrato que hay que respetar:

- El frontend envía `horizonte` en **todas** las llamadas, también con `esquema=mensual`
  donde no aplica. Hay que **ignorarlo** ahí, no fallar.
- Mientras solo exista la réplica, cada fila va con `estado = "firme"`, `central = null`
  y `p90` = el número firme. El contrato ya lo contempla.

- [x] **Step 1: Escribir el test que falla**

```python
"""Los endpoints del Modelo Predictivo respetan el contrato que el frontend consume."""
from app.api.v1.garantias_modelo import router


def test_el_router_expone_las_dos_rutas():
    rutas = {r.path for r in router.routes}
    assert "/garantias/modelo/plan" in rutas
    assert "/garantias/modelo/detalle/{id}" in rutas


def test_el_prefijo_es_el_del_contrato():
    assert router.prefix == "/garantias/modelo"


def test_las_rutas_son_get():
    for r in router.routes:
        assert "GET" in r.methods
```

- [x] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_endpoints.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `garantias_modelo`

- [x] **Step 3: Implementar el router**

```python
"""Modelo Predictivo de Garantías: el plan de la semana y el detalle de un vencimiento.

Solo transporte. El contrato lo congeló el plan 1 y el frontend ya está en producción
consumiéndolo: no cambiar nombres de campo sin cambiar la vista.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.services.garantias_modelo.servicio import construir_detalle, construir_plan

router = APIRouter(prefix="/garantias/modelo", tags=["Garantías · Modelo Predictivo"])


@router.get("/plan")
def get_plan(
    agente: str = Query("UNGG"),
    esquema: str = Query("semanal"),
    cuantil: float = Query(0.9, ge=0.5, le=0.99),
    horizonte: int = Query(4, ge=1, le=12),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lo que hay que reservar para los próximos vencimientos.

    `horizonte` se ignora cuando `esquema` es mensual — el frontend lo envía siempre.
    """
    return construir_plan(db, agente=agente, esquema=esquema,
                          cuantil=cuantil, horizonte=horizonte)


@router.get("/detalle/{id}")
def get_detalle(
    id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Cadena de cálculo, descomposición del ancho e insumos de un vencimiento."""
    return construir_detalle(db, id=id)
```

- [x] **Step 4: Registrar el router**

En `app/api/v1/router.py`, agregar `garantias_modelo` a la lista de imports de la línea 2
(al final, después de `retos`), y al final del archivo:

```python
api_router.include_router(garantias_modelo.router)
```

- [x] **Step 5: Correr el test y la suite**

Run: `python -m pytest tests/test_gar_modelo_endpoints.py -q` → `3 passed`
Run: `python -m pytest -q` → sin regresión
Run: `python -c "import app.main; print('ok')"` → `ok`

- [x] **Step 6: Commit**

```bash
git add app/api/v1/garantias_modelo.py app/api/v1/router.py tests/test_gar_modelo_endpoints.py
git commit -m "feat(garantias): endpoints del modelo predictivo"
```

---

## Task 6: El servicio que arma la respuesta

**Files:**
- Create: `app/services/garantias_modelo/servicio.py`

Construye exactamente la forma que el frontend espera, leyendo `GarCalculo`,
`GarComponenteReal` y `GarComponentePred`.

- [x] **Step 1: Implementar**

```python
"""Arma las respuestas de los endpoints, con la forma exacta del contrato del plan 1.

Mientras solo exista la réplica del día 7, cada fila sale con `estado = "firme"`,
`central = None` y `p90` = el número firme. Es honesto: sin estimador no hay rango, y
poner un rango falso sería peor que no tenerlo.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.garantias_modelo import (
    GarCalculo, GarComponentePred, GarComponenteReal,
)

_EXPOSICION = "exposicion energia en bolsa ($)"


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _id_calculo(c: GarCalculo) -> str:
    return f"{c.fecha_vencimiento.isoformat()}|{c.periodo_ini.isoformat()}"


def construir_plan(db: Session, *, agente: str, esquema: str,
                   cuantil: float, horizonte: int) -> dict:
    """`horizonte` se ignora si `esquema` es mensual: el frontend lo manda siempre."""
    q = (
        select(GarCalculo)
        .where(GarCalculo.agente == agente, GarCalculo.esquema == esquema)
        .order_by(GarCalculo.fecha_vencimiento.desc())
        .limit(horizonte * 3 if esquema == "semanal" else 6)
    )
    calculos = list(db.execute(q).scalars())

    semanales: list[dict] = []
    mensuales: list[dict] = []
    for c in calculos:
        real = db.execute(
            select(GarComponenteReal.valor).where(
                GarComponenteReal.calculo_id == c.id,
                GarComponenteReal.componente == _EXPOSICION)
        ).scalar()
        pred = db.execute(
            select(GarComponentePred.valor).where(
                GarComponentePred.calculo_id == c.id,
                GarComponentePred.componente == _EXPOSICION,
                GarComponentePred.horizonte_dias == 7)
        ).scalar()
        fila = {
            "id": _id_calculo(c),
            "vencimiento": _iso(c.fecha_vencimiento),
            "periodo_ini": _iso(c.periodo_ini),
            "periodo_fin": _iso(c.periodo_fin),
            "etiqueta_periodo": c.etiqueta_periodo,
            "estado": "firme",
            "central": None,
            "p90": float(pred) if pred is not None else None,
            "real": float(real) if real is not None else None,
            "fecha_calculo_xm": _iso(c.fecha_calculo),
            "procedencia_ventana": (c.procedencia or {}).get("ventana", "observada"),
        }
        (semanales if c.esquema == "semanal" else mensuales).append(fila)

    p90s = [f["p90"] for f in semanales if f["p90"] is not None]
    return {
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "frescura": None,
        "totales": {
            "central": None,
            "suma_p90": sum(p90s) if p90s else 0.0,
            "p90_total": None,
            "brecha": None,
        },
        "semanales": semanales,
        "mensuales": mensuales,
        "backtest": None,
    }


def construir_detalle(db: Session, *, id: str) -> dict:
    """Cadena de cálculo de un vencimiento. `id` es `vencimiento|periodo_ini`."""
    try:
        vto, ini = id.split("|", 1)
        c = db.execute(
            select(GarCalculo).where(
                GarCalculo.fecha_vencimiento == datetime.date.fromisoformat(vto),
                GarCalculo.periodo_ini == datetime.date.fromisoformat(ini))
        ).scalars().first()
    except ValueError:
        c = None
    if c is None:
        return {"id": id, "cadena": [], "descomposicion_ancho": [], "insumos": []}

    reales = {r.componente: float(r.valor) for r in db.execute(
        select(GarComponenteReal).where(GarComponenteReal.calculo_id == c.id)
    ).scalars()}
    pred = db.execute(
        select(GarComponentePred.valor).where(
            GarComponentePred.calculo_id == c.id,
            GarComponentePred.componente == _EXPOSICION,
            GarComponentePred.horizonte_dias == 7)
    ).scalar()

    return {
        "id": id,
        "cadena": [
            {"concepto": "Exposición en bolsa", "origen": "replicada",
             "central": None, "p90": float(pred) if pred is not None else None},
            {"concepto": "Exposición publicada por XM", "origen": "real",
             "central": None, "p90": reales.get(_EXPOSICION)},
        ],
        "descomposicion_ancho": [],
        "insumos": [],
    }
```

- [x] **Step 2: Verificar que importa**

Run: `python -c "import app.main; print('ok')"`
Expected: `ok`

- [x] **Step 3: Correr la suite**

Run: `python -m pytest -q`
Expected: sin regresión.

- [x] **Step 4: Commit**

```bash
git add app/services/garantias_modelo/servicio.py
git commit -m "feat(garantias): servicio que arma el contrato del frontend"
```

---

## Task 7: Comando de carga masiva y cierre

**Files:**
- Create: `scripts/cargar_corpus_garantias.py`

- [x] **Step 1: Escribir el comando**

Es un script, no un endpoint: la carga del histórico se corre a mano una vez.

```python
"""Carga el corpus de XM a las tablas del Modelo Predictivo.

Uso:
    python scripts/cargar_corpus_garantias.py --zip "<ruta al zip>" [--dry-run]

Idempotente: reingerir el mismo zip no duplica filas — `xm_archivo.sha256` es único y
`xm_medida` tiene su clave natural.

**Ojo con `esquema_ok`:** `preparar_archivo` devuelve `disponible_desde = None` cuando no
se la suministran, y las columnas del modelo son `NOT NULL`. Este cargador siempre la
suministra vía `disponible_desde_derivado`, pero si un archivo llega con
`esquema_ok = False` **se registra y no se insertan sus medidas**.
"""
import argparse
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal  # noqa: E402
from app.models.garantias_modelo import XMArchivo, XMMedida  # noqa: E402
from app.services.garantias_modelo.cargador import (  # noqa: E402
    disponible_desde_derivado, filas_a_medidas,
)
from app.services.garantias_modelo.ingesta import preparar_archivo  # noqa: E402
from app.services.garantias_modelo.normalizar import version_de_nombre  # noqa: E402
from app.services.garantias_modelo.parsers_ftp import (  # noqa: E402
    parsear_arrpas, parsear_balcttos, parsear_dspcttos, parsear_trsd,
)

AGENTES = ("UNGG", "UNGC")


def _parsear(tipo, contenido, fecha, version, agente):
    if tipo == "balcttos":
        return parsear_balcttos(contenido, fecha, version, agente)
    if tipo == "trsd":
        return parsear_trsd(contenido, fecha, version)
    if tipo == "dspcttos":
        return parsear_dspcttos(contenido, fecha, version, agente)
    if tipo == "arrpas":
        return parsear_arrpas(contenido, fecha, version)
    return [], 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--agente", default="UNGG", choices=AGENTES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    nuevos = saltados = rechazados = medidas = 0
    try:
        with zipfile.ZipFile(args.zip) as zf:
            for n in sorted(zf.namelist()):
                if n.endswith("/"):
                    continue
                base = os.path.basename(n)
                version = version_de_nombre(base)
                if version != "tx2":          # este plan solo carga tx2
                    continue

                anio = None
                partes = os.path.dirname(n).split("/")[-1].split("-")
                if len(partes) == 2 and partes[0].isdigit():
                    anio = int(partes[0])

                contenido = zf.read(n)

                # Dos pasadas, y no es redundancia. Con `disponible_desde=None`
                # `preparar_archivo` corta ANTES de llamar a `validar_estructura`:
                # devuelve `esquema_ok=False` sin haber mirado una sola columna. Si
                # reponemos el flag a mano después, marcamos como válido un archivo
                # que nunca se validó — y el fallo de abril-2026 (columnas
                # intercambiadas) volvería a pasar inadvertido.
                #
                # La primera pasada sirve solo para derivar la fecha del documento;
                # la segunda, ya con `disponible_desde`, es la que valida de verdad.
                previo = preparar_archivo(base, contenido,
                                          disponible_desde=None, anio=anio)
                if not previo["periodo_ini"]:
                    rechazados += 1
                    print(f"  SIN FECHA {base}: no se pudo derivar el día del nombre")
                    continue

                meta = preparar_archivo(
                    base, contenido, anio=anio,
                    disponible_desde=disponible_desde_derivado(
                        previo["periodo_ini"], version))
                meta["origen_disponibilidad"] = "derivado"

                existe = db.query(XMArchivo).filter_by(sha256=meta["sha256"]).first()
                if existe:
                    saltados += 1
                    continue
                if not meta["esquema_ok"]:
                    rechazados += 1
                    print(f"  RECHAZADO {base}: {meta['esquema_detalle']}")
                    if args.dry_run:
                        continue

                filas, descartadas = _parsear(
                    meta["tipo"], contenido, meta["periodo_ini"], version, args.agente)
                if descartadas:
                    print(f"  {base}: {descartadas} fila(s) truncada(s) descartada(s)")

                if args.dry_run:
                    nuevos += 1
                    medidas += len(filas)
                    continue

                arch = XMArchivo(**{k: v for k, v in meta.items()})
                arch.filas_ingeridas = len(filas)
                db.add(arch)
                db.flush()
                db.bulk_insert_mappings(
                    XMMedida, filas_a_medidas(filas, archivo_id=arch.id))
                db.commit()
                nuevos += 1
                medidas += len(filas)
    finally:
        db.close()

    print(f"\nnuevos: {nuevos}   ya estaban: {saltados}   rechazados: {rechazados}")
    print(f"medidas insertadas: {medidas:,}")
    if rechazados:
        print("Hubo archivos rechazados. Revisar antes de dar la carga por buena.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [x] **Step 2: Probar en seco contra los zips reales**

**Cuál zip tiene los `.tx2` de cada tipo** (verificado el 2026-08-27; no es obvio y los
nombres engañan — hay pares donde el zip "limpio" solo trae `.txf`):

| Tipo | Zip con los `.tx2` | Contenido |
|---|---|---|
| BalCttos | `XM_BalCttos Intento1.zip` | 538 `.tx2` + 577 `.txf` |
| trsd | `XM_trsd intento4.zip` | 539 `.tx2` + 577 `.txf` + 516 `.tx1` |
| dspcttos | `XM_dspcttos_2025 Intento2.zip`, `XM_dspcttos_2026 Intento 3.zip` | por año |
| arrpas | `XM_arrpas intento 5.zip` | incluye el layout nuevo de 2026-03 |

`XM_BalCttos.zip` (sin *Intento1*) **solo tiene `.txf`**: correrlo da 0 archivos nuevos
y parece un bug del cargador cuando no lo es.

Run, uno por uno, empezando por trsd:
```bash
python scripts/cargar_corpus_garantias.py --zip "C:\Users\adhar\OneDrive\Documents\Plataforma Operaciones\XM_trsd intento4.zip" --dry-run
```
Expected: ~539 archivos nuevos, ~427.000 medidas (33 códigos x 24 horas x 539 días),
cero rechazados.

```bash
python scripts/cargar_corpus_garantias.py --zip "C:\Users\adhar\OneDrive\Documents\Plataforma Operaciones\XM_BalCttos Intento1.zip" --dry-run
```
Expected: ~538 archivos nuevos, ~180.000 medidas, cero rechazados.

Si hay rechazados, **parar y reportar** con el motivo: significa que un archivo real no
pasa `validar_estructura`, y eso hay que entenderlo antes de cargar nada.

- [x] **Step 2b: Verificar que el motor no devuelve cero**

El riesgo real del motor no es que falle, es que devuelva `0.0` en silencio porque un
concepto o una entidad no coinciden. Después de la carga en vivo de trsd y BalCttos,
comprobar un día conocido:

```bash
python -c "
import datetime
from app.core.database import SessionLocal
from app.services.garantias_modelo.motor import _series
db = SessionLocal()
d = datetime.date(2025, 1, 1)
c = _series(db, tipo='balcttos', concepto='neto de compras en bolsa', entidad='UNGG',
            desde=d, hasta=d, corte=datetime.date(2026, 1, 1))
p = _series(db, tipo='trsd', concepto='pbna', entidad='NACIONAL',
            desde=d, hasta=d, corte=datetime.date(2026, 1, 1))
print('dias compras', len(c), 'dias pbna', len(p))
"
```
Expected: `dias compras 1 dias pbna 1`. Si sale `0`, el filtro anti-leakage o los
nombres de concepto están mal — **no seguir**.

Referencia medida directamente de los archivos el 2026-08-27, sin pasar por la base:
la exposición del **2025-01-01 es -497.440,05 COP** (vendedor neto ese día). El motor
tiene que reproducir ese número.

- [x] **Step 3: Correr la suite completa**

Run: `python -m pytest -q`
Expected: sin regresión desde 2107 passed / 1 skipped.

- [x] **Step 4: Verificar sincronía y commitear**

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```
Si el segundo número no es `0`, `git pull --rebase origin master` y volver a correr la
suite.

```bash
git add scripts/cargar_corpus_garantias.py
git commit -m "feat(garantias): comando de carga masiva del corpus"
```

---

## Estado esperado al terminar

- La réplica y el backtest existen como funciones puras y testeadas.
- El motor lee la base con el filtro anti-leakage en un solo lugar.
- Los dos endpoints del contrato responden y están registrados.
- El comando de carga masiva corre en seco contra un zip real sin rechazos.
- La suite completa en verde.

## Lo que este plan no hace

- **No estima el día 14.** Solo la réplica del número firme. El rango es el plan 4.
- **No carga `.tx1` ni `.txf`.** Solo `.tx2`, que es lo que usa la réplica.
- **No implementa la frescura ni la descomposición del ancho.** El contrato las declara
  y el servicio devuelve `null`; el frontend ya las maneja como opcionales.
- **No activa el cron de FTP.** La carga es manual en este plan.


---

# Resultado de la ejecucion — 2026-08-27

Las 7 tareas quedaron completas, en la rama `feat/garantias-modelo-replica`, seis
commits. Suite: **2158 passed, 1 skipped** (linea base 2107). Lo que sigue es lo que el
plan no habia previsto.

## Lo que se desvio del plan

**Se invirtio el orden de las tareas 5 y 6.** El router de la tarea 5 importa el
servicio de la tarea 6, asi que en el orden escrito no compilaba. Se implemento primero
el servicio.

**El generador de claves del backtest tenia un bug.** El plan usaba
`UMBRALES = (0.01, 1.0, 5.0)` y armaba la clave con `str(u)`: `1.0` produce
`dentro_1_0`, no `dentro_1`. Se cambio a `(0.01, 1, 5)`.

**Se le agregaron tests al motor, que el plan no le habia puesto.** Es la pieza que
puede devolver `0.0` en silencio si un concepto o una entidad no coinciden. Siete tests
sobre SQLite: el par disponible/no-disponible con los mismos datos prueba que el corte
es lo que decide, mas `esquema_ok=False`, otro agente, concepto mal escrito y periodo
incompleto.

**`--dry-run` ya no abre sesion.** Como estaba escrito exigia que las tablas existieran,
justo lo que uno no tiene antes de la primera carga. Validar el corpus no necesita base.

## El defecto de diseno que solo aparecio al insertar

Los tests unitarios del plan 2 parsean pero **nunca insertan**, asi que no podian verlo:

> **BalCttos trae una linea por contrato** y `_parsear_ancho` identifica la serie solo
> por `CONCEPTO`, descartando `CODIGO CONTRATO`. En enero-2025 `CONTRATO DE VENTA`
> aparece 8 veces; en julio-2026, 50. Todas comparten `uq_xm_medida_natural`.

Se resolvio en el cargador con `agregar_por_clave_natural()`, que suma y reporta cuantas
filas colapso. No pierde nada: los tres conceptos de la replica aparecen una sola vez
por dia, el unico que se repite es `contrato de venta` —cuyo total es lo que se concilia
contra `dspcttos`— y el detalle por contrato vive en `dspcttos`, donde `concepto` ES el
codigo de contrato.

## Seis archivos corruptos de XM, confirmados

El validador rechazo, en **2026-04-26, 27 y 28**, tanto `BalCttos` como `dspcttos`:
cabecera con **cada nombre de columna duplicado** (62 en vez de 31; 108 en vez de 54)
mientras las filas de datos traen el ancho correcto. Sin el validador, el bloque horario
se habria leido con 7 posiciones de desfase: numeros plausibles y falsos.

**No hay version corregida.** Se reviso el `.txf` final de los seis y trae la misma
cabecera doblada: XM nunca lo arreglo.

**El contenido es recuperable** —solo la linea de cabecera esta doblada— pero reparar
datos malformados del proveedor es una decision de politica, no un fix mecanico, y se
dejo fuera a proposito. Hoy el hueco es visible: `exposicion_de_calculo` devuelve
`dias_usados`, `dias_esperados` y `completo`, y la semana del 22 al 28 de abril de 2026
sale **4/7 con `completo=False`**.

**Cuidado con esa semana:** da +18.479.576,62 COP (comprador neto, o sea deuda) sobre
solo 4 de 7 dias, asi que **subestima** un pasivo real. No usarla como esta.

## Verificacion end-to-end contra la base local

`localhost:5432/operaciones`, no produccion.

| Que | Resultado |
|---|---|
| trsd | 539 archivos, 423.648 medidas, 0 rechazados |
| balcttos | 535 archivos, 99.960 medidas, 3 rechazados (los corruptos) |
| arrpas (en seco) | 537 archivos, 2.077.504 medidas, 0 rechazados |
| dspcttos 2025 / 2026 (en seco) | 340 y 195 archivos, 3 rechazados en 2026 |
| Replica desde la base | **-497.440,05 COP** el 2025-01-01, exacto |
| Anti-leakage en el borde | 0 dias en D+6, 1 dia en D+7 — sin off-by-one |
| Semanas completas | 7/7 en ene-2025 y jul-2026 |

## Lo que sigue (plan 4)

- El estimador del dia 14 y el intervalo. Hoy toda fila sale `estado=firme`,
  `central=null`.
- Cargar los targets: los Excel de garantia publicados, que son los que llenan
  `gar_calculo` y `gar_componente_real`. **Sin eso la tab sigue vacia en produccion**:
  este plan dejo el motor y los endpoints, pero nadie escribe todavia `gar_calculo`.
- Cargar `.tx1` con su propio lag medido, para estimar antes del dia 14.
- Decidir si se reparan los seis archivos de abril-2026.
