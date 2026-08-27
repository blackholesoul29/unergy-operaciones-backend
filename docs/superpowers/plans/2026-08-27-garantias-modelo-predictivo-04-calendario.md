# Modelo Predictivo de Garantías — Plan 4: Calendario, targets y backtest

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la tab del Modelo Predictivo muestre números reales sin depender de que XM publique, generando los períodos desde el calendario y validando la réplica contra los 175 archivos históricos.

**Architecture:** Un generador de calendario puro que produce ventanas desde una tabla de regímenes; un lector de los Excel de garantía que llena targets; un runner que recorre los períodos llamando al motor del plan 3; y el backtest que compara.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, PostgreSQL, pytest, openpyxl.

---

## Contexto: plan 4 de 4

| Plan | Alcance | Estado |
|---|---|---|
| 1 — Frontend | Vista de planeación | en producción |
| 2 — Ingesta | Esquema, parsers, validación | en master |
| 3 — Carga y réplica | Cargadores, motor, endpoints | en master |
| **4 — Calendario y backtest** (este) | Generar períodos, targets, validar | listo para ejecutar |

**El estimador del día 14 no entra acá.** Este plan cierra el circuito con el número
**firme** y prueba que la réplica funciona a escala. El intervalo se decide después, con
el backtest en la mano — construirlo antes sería adivinar sobre una réplica no validada.

## Por qué este plan existe

El plan 3 dejó el motor funcionando y los endpoints respondiendo, pero
**`gar_calculo` tiene 0 filas**. El motor sabe calcular y nadie le dice qué calcular, así
que la tab responde `"semanales": []`.

La corrección que reorienta este plan vino del usuario: **los períodos no salen de XM,
salen del calendario**. Depender de los Excel publicados para saber *cuándo* vence una
garantía contradice el objetivo del proyecto, que es justamente adelantarse a XM.

## Lo que ya está derivado y este plan da por sentado

Todo en **§2.10 del spec**, medido sobre los 175 archivos el 2026-08-27. No son supuestos.

| Hecho | Consecuencia |
|---|---|
| `fin_ventana = vencimiento − 14` en **69 de 74** del régimen actual; las 5 excepciones son martes del régimen viejo | La ventana semanal se calcula, no se estima |
| La **fecha de cálculo se corre por festivos pero la ventana no** (`venc − calc = 8` compensa con `calc − fin = 6`) | Los festivos no mueven el monto. No hay que modelar el calendario festivo |
| Mensual: **fecha de cálculo entre el día 5 y el 10, 17 de 17**; pero la **ventana NO es derivable** (mejor fórmula: 3 de 17) | La mensual se lee del archivo. No buscar la fórmula: ya se buscó |
| El **vencimiento mensual (17–24) no tiene regla aritmética** | Es dato de entrada, no derivable. No perder tiempo buscándola |
| Dos cambios de régimen en 20 meses (largo 7→30 el 2025-09-26; martes→viernes el 2025-10-31) | El calendario va como **datos con vigencia**, no constantes |
| Cada Excel trae hoja `PERIODO BASE` con la ventana día por día | Los targets históricos son legibles sin heurística |
| El motor del plan 3 reproduce **−497.440,05 COP** del 2025-01-01 leyendo de la base | Si el backtest da mal, el bug está en el calendario o los targets, no en la aritmética |

## Convenciones del repo

**Antes de tocar nada:**

```bash
git fetch origin && git rev-list --left-right --count HEAD...origin/master
```

Si el segundo número no es `0`, `git pull --rebase origin master`. Este repo se atrasa
rápido: durante el plan 2 hubo que rebasar seis veces y el plan 3 arrancó 62 commits
atrás.

**Tests:** `python -m pytest -q`. Línea base al cierre del plan 3: **2158 passed, 1 skipped**.

**Esquema:** las cinco tablas ya existen. Este plan **no crea tablas ni toca
`_PENDING_DDLS`**.

**Producción no se escribe desde local.** Todo lo de este plan corre contra
`localhost:5432/operaciones`.

**Tests en SQLite:** verificar comportamiento, no tipos. Ver el patrón en
`tests/test_gar_modelo_motor.py` (los `@compiles` de `JSONB` y `BigInteger`).

**Zona horaria:** usar `_hoy_col()`, no `date.today()`.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/services/garantias_modelo/calendario.py` | **Crear.** Puro: regímenes → vencimientos y ventanas. |
| `app/services/garantias_modelo/parsers_garantia_xlsx.py` | **Crear.** Lee `PERIODO BASE` y los componentes de un Excel. |
| `app/services/garantias_modelo/targets.py` | **Crear.** Persiste `GarCalculo` + `GarComponenteReal`. |
| `app/services/garantias_modelo/runner.py` | **Crear.** Recorre períodos, llama al motor, escribe `GarComponentePred`. |
| `app/services/garantias_modelo/servicio.py` | **Modificar.** Poblar `backtest` y `frescura`, hoy en `null`. |
| `scripts/cargar_targets_garantias.py` | **Crear.** Comando de carga de los 175 Excel. |
| `scripts/calcular_predicciones.py` | **Crear.** Comando que corre el runner y reporta el backtest. |
| `tests/test_gar_modelo_calendario.py` | **Crear.** |
| `tests/test_gar_modelo_parsers_xlsx.py` | **Crear.** |
| `tests/test_gar_modelo_runner.py` | **Crear.** |

---

## Task 1: El calendario, como función pura

**Files:**
- Create: `app/services/garantias_modelo/calendario.py`
- Test: `tests/test_gar_modelo_calendario.py`

El corazón de este plan y no necesita base de datos.

- [ ] **Step 1: Escribir el test que falla**

```python
"""El calendario de vencimientos, derivado de §2.10 del spec.

Los números vienen de medir los 175 archivos reales, no de la documentación de XM.
"""
import datetime

import pytest

from app.services.garantias_modelo.calendario import (
    REGIMENES,
    regimen_vigente,
    ventana_semanal,
    ventana_mensual,
    vencimientos_semanales,
)

V_2026_08_28 = datetime.date(2026, 8, 28)   # viernes, caso verificado contra XM


def test_ventana_semanal_del_caso_verificado():
    """Contra `GARANTIA SEMANAL MENSUAL 28AGO-2026.XLSX`, hoja PERIODO BASE."""
    ini, fin = ventana_semanal(V_2026_08_28)
    assert fin == datetime.date(2026, 8, 14)      # vencimiento − 14
    assert ini == datetime.date(2026, 7, 16)      # 30 días corridos
    assert (fin - ini).days + 1 == 30


def test_ventana_semanal_del_regimen_martes():
    """Antes del 2025-10-31: martes, ventana de 7 días, venc − fin = 11."""
    ini, fin = ventana_semanal(datetime.date(2025, 3, 4))
    assert fin == datetime.date(2025, 2, 21)
    assert (fin - ini).days + 1 == 7


def test_el_regimen_se_escoge_por_fecha():
    assert regimen_vigente(datetime.date(2025, 3, 4))["dia_semana"] == 1     # martes
    assert regimen_vigente(datetime.date(2026, 8, 28))["dia_semana"] == 4    # viernes


def test_los_regimenes_no_se_solapan_ni_dejan_hueco():
    """Un régimen mal encadenado deja fechas sin regla o con dos."""
    ord_ = sorted(REGIMENES, key=lambda r: r["desde"])
    for a, b in zip(ord_, ord_[1:]):
        assert a["hasta"] is not None
        assert b["desde"] == a["hasta"] + datetime.timedelta(days=1)
    assert ord_[-1]["hasta"] is None       # el vigente queda abierto


def test_vencimientos_semanales_son_todos_viernes():
    v = vencimientos_semanales(datetime.date(2026, 8, 1), datetime.date(2026, 8, 31))
    assert v == [datetime.date(2026, 8, 7), datetime.date(2026, 8, 14),
                 datetime.date(2026, 8, 21), datetime.date(2026, 8, 28)]


def test_vencimientos_semanales_cruzando_el_cambio_de_regimen():
    """El 2025-10-31 cambió de martes a viernes. No puede duplicar ni saltar semanas."""
    v = vencimientos_semanales(datetime.date(2025, 10, 15), datetime.date(2025, 11, 15))
    assert datetime.date(2025, 10, 21) in v      # último martes
    assert datetime.date(2025, 10, 31) in v      # primer viernes
    assert len(v) == len(set(v))


def test_ventana_mensual_no_se_inventa():
    """La ventana mensual NO es derivable: es el corte de mes liquidado de XM.

    Se midió contra los 17 casos reales y la mejor fórmula aritmética acierta 3 de 17
    (ver Step 4). Devolver una ventana calculada seria dar un numero plausible y falso,
    que es exactamente lo que este proyecto evita. Se devuelve None y quien llama la
    lee del archivo.
    """
    assert ventana_mensual(datetime.date(2026, 8, 21)) is None


def test_fecha_fuera_de_todo_regimen_falla_ruidosamente():
    """Antes del primer régimen no hay regla. Inventar una contamina el backtest."""
    with pytest.raises(ValueError):
        ventana_semanal(datetime.date(2020, 1, 1))
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_calendario.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `calendario`

- [ ] **Step 3: Implementar**

Los regímenes van como **datos con vigencia**. Van dos cambios en 20 meses y XM anunció
otro para el 2026-09-04: el próximo debe ser agregar una fila, no editar lógica.

```python
"""El calendario de vencimientos y ventanas base de las garantías de XM.

Puro: no toca la base. Los números salen de medir los 175 archivos históricos
(spec §2.10), no de la documentación de XM.

**Por qué esto es una tabla y no constantes.** En 20 meses XM cambió el régimen dos
veces: el largo de la ventana semanal pasó de 7 a 30 días el 2025-09-26, y el día de
vencimiento pasó de martes a viernes el 2025-10-31. Ya anunció otro cambio para el
2026-09-04. Agregar un régimen tiene que ser agregar una fila.

**Lo que NO se modela: los festivos.** La fecha de *cálculo* sí se corre —los
vencimientos del 2026-04-03, 2026-05-01 y 2026-08-07 salen con `venc − calc = 8`— pero
compensan con `calc − fin = 6`, así que `venc − fin` sigue en 14. La ventana no se
mueve, y la ventana es la que determina el monto.
"""
from __future__ import annotations

import datetime

# `dia_semana` en la convención de `date.weekday()`: 0=lunes … 4=viernes.
# `hasta` inclusive; `None` = régimen vigente.
REGIMENES = [
    {
        "nombre": "martes-7d",
        "desde": datetime.date(2025, 1, 1),
        "hasta": datetime.date(2025, 10, 30),
        "dia_semana": 1,          # martes
        "venc_menos_fin": 11,
        "largo_ventana": 7,
        "venc_menos_calc": 4,
    },
    {
        "nombre": "viernes-30d",
        "desde": datetime.date(2025, 10, 31),
        "hasta": None,
        "dia_semana": 4,          # viernes
        "venc_menos_fin": 14,
        "largo_ventana": 30,
        "venc_menos_calc": 7,
    },
]

DIAS_MES_MIN = 28


def regimen_vigente(fecha: datetime.date) -> dict:
    """El régimen que aplica a `fecha`. Falla si no hay ninguno.

    No hay valor por defecto: aplicar la regla equivocada a un período histórico
    produce una ventana plausible y falsa, que es justo lo que este proyecto evita.
    """
    for r in REGIMENES:
        if r["desde"] <= fecha and (r["hasta"] is None or fecha <= r["hasta"]):
            return r
    raise ValueError(
        f"{fecha} no cae en ningún régimen conocido. Los regímenes arrancan el "
        f"{REGIMENES[0]['desde']}; agregar uno nuevo a REGIMENES si XM cambió otra vez.")


def ventana_semanal(vencimiento: datetime.date) -> tuple[datetime.date, datetime.date]:
    """`(inicio, fin)` de la ventana base, ambos inclusive."""
    r = regimen_vigente(vencimiento)
    fin = vencimiento - datetime.timedelta(days=r["venc_menos_fin"])
    ini = fin - datetime.timedelta(days=r["largo_ventana"] - 1)
    return ini, fin


def fecha_calculo(vencimiento: datetime.date) -> datetime.date:
    """Cuándo XM publica. Se corre por festivos; usar solo para mostrar, nunca para
    derivar la ventana."""
    r = regimen_vigente(vencimiento)
    return vencimiento - datetime.timedelta(days=r["venc_menos_calc"])


def vencimientos_semanales(desde: datetime.date,
                           hasta: datetime.date) -> list[datetime.date]:
    """Todos los vencimientos semanales del rango, respetando el cambio de régimen.

    Se recorre día a día en vez de saltar de siete en siete: al cruzar un cambio de
    día de la semana, saltar produce huecos o duplicados.
    """
    salida = []
    d = desde
    while d <= hasta:
        try:
            r = regimen_vigente(d)
        except ValueError:
            d += datetime.timedelta(days=1)
            continue
        if d.weekday() == r["dia_semana"]:
            salida.append(d)
        d += datetime.timedelta(days=1)
    return salida


def ventana_mensual(vencimiento: datetime.date) -> None:
    """**No es derivable.** Devuelve `None` a propósito.

    La ventana mensual es el corte del *mes liquidado* de XM, que ellos publican y que
    no coincide con el mes calendario. Se midió contra los 17 casos reales
    (2026-08-27): la mejor fórmula aritmética —30/31 días terminando ~el 29 del mes
    anterior— acierta **3 de 17**, y las ventanas consecutivas tampoco encadenan
    (9 de 16). Los cortes reales van del día 26 al 29 sin patrón.

    Devolver una ventana calculada daría un número plausible y falso. Quien necesite la
    mensual la lee de la hoja `PERIODO BASE` del archivo, o del calendario de
    liquidación que publica XM.

    Ver el Step 4 del plan 4 para la hipótesis de derivarla de `xm_medida`.
    """
    return None
```

- [ ] **Step 4: NO buscar la fórmula mensual — ya se buscó**

Está medido y cerrado: la mejor fórmula acierta **3 de 17**, y las ventanas consecutivas
encadenan solo en 9 de 16. Los cortes reales caen entre el día 26 y el 29 sin patrón.
**No gastar tiempo acá.**

| Vencimiento | Ventana real |
|---|---|
| 2025-08-20 | 2025-06-30 → 2025-07-29 |
| 2025-11-21 | 2025-09-30 → 2025-10-29 |
| 2025-12-19 | 2025-10-31 → 2025-11-29 |
| 2026-01-23 | 2025-11-28 → 2025-12-27 |
| 2026-02-20 | 2025-12-29 → 2026-01-27 |
| 2026-03-20 | 2026-01-28 → 2026-02-26 |
| 2026-08-21 | 2026-06-30 → 2026-07-29 |

La mensual histórica se lee del archivo (Task 2). Para meses futuros hay **una hipótesis
que vale la pena probar y que no requiere a XM**: el corte de mes liquidado debería ser
observable en `xm_medida`, mirando hasta qué día hay datos en `.tx2`. Si el último día
liquidado que vemos coincide con el `fin` que declara el archivo en los 17 casos,
la mensual también queda generable. **Probarlo es barato y el dato ya está cargado.**
Si no coincide, dejarla como entrada manual y seguir: la semanal es la que necesita
anticipación, y esa sí está resuelta.

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_calendario.py -q`

- [ ] **Step 6: Commit**

```bash
git add app/services/garantias_modelo/calendario.py tests/test_gar_modelo_calendario.py
git commit -m "feat(garantias): calendario de vencimientos como tabla de regimenes"
```

---

## Task 2: Leer los Excel de garantía

**Files:**
- Create: `app/services/garantias_modelo/parsers_garantia_xlsx.py`
- Test: `tests/test_gar_modelo_parsers_xlsx.py`

Extrae de un Excel lo que XM declara. Es la fuente de los targets y el juez del Task 1.

- [ ] **Step 1: Lo que hay que leer**

De la hoja **`PERIODO BASE`**:
- `FECHA DE VENCIMIENTO: 21 DE AGO DE 2026` (texto, mes en español abreviado)
- `FECHA DE CÁLCULO: 2026-08-06` (ISO)
- Los días de la ventana, uno por fila

De la hoja de detalle (`01-30 SEP`, `AJUSTE TX2 SEMA MENS 08-14 AGO`, …), la fila del
agente con las 19 columnas de componente:

```
CÓDIGO | AGENTE | ACTIVIDAD | Exposición Energía en Bolsa ($) | Restricciones ($) |
Desviación ($) | Responsabilidad Comercial del AGC ($) | Regulación Primaria de
Frecuencia ($) | Servicios AGC ($) | Compras Reconciliación ($) | Ventas Reconciliación
($) | Cargo por Confiabilidad ($) | VMOEFV | Servicios CND-SIC-FAZNI | Cargos Uso STN ($)
| Servicios LAC($) | LC | FCDC | GARANTIA 01-30SEP
```

**Trampas confirmadas:**
- El semanal trae **cuatro hojas de detalle**, una por subperíodo: `DEPÓSITO SEM MENS`,
  `AJUSTE PROY (M)`, `AJUSTE TX2 SEMA MENS`, `AJUSTE (M+1)`. **No colapsarlas**: cada
  una es un `GarCalculo` distinto, con su propia ventana (spec §2.9).
- Hay `_V2` y `_V3` del mismo día: son republicaciones. **Gana el sufijo más alto**;
  registrar cuál se usó.
- 30 de los 175 archivos **no tienen `PERIODO BASE`**. Saltarlos con motivo, no romper.
- Los nombres de mes vienen `ENE…DIC` y también `SEPT` (cuatro letras).
- Reusar `normalizar_concepto` y `coincide_concepto` de `normalizar.py` para casar los
  nombres de componente: ya manejan tildes y mojibake.

- [ ] **Step 2: Escribir tests con un Excel construido en memoria**

No leer del zip en los tests: construir un workbook mínimo con `openpyxl` que
reproduzca la estructura. Los tests tienen que correr sin los zips presentes.

Casos mínimos: vencimiento en texto español, fecha de cálculo ISO, ventana continua,
archivo sin `PERIODO BASE`, mes `SEPT`, y las cuatro hojas del semanal.

- [ ] **Step 3: Implementar, correr, commitear**

---

## Task 3: Persistir los targets

**Files:**
- Create: `app/services/garantias_modelo/targets.py`
- Create: `scripts/cargar_targets_garantias.py`

Escribe `GarCalculo` (uno por subperíodo) y `GarComponenteReal`.

- [ ] **Step 1: Puntos de diseño a respetar**

- **Idempotente** por `uq_gar_calculo_natural` (agente, esquema, vencimiento,
  periodo_ini, periodo_fin). Reingerir no duplica.
- `procedencia` guarda de qué archivo salió y qué versión (`_V2`/`_V3`) ganó. Esa
  columna existe justo para esto.
- **`etiqueta_periodo`** = el nombre de la hoja normalizado (`AJUSTE TX2`,
  `AJUSTE (M+1)`, …). El frontend ya lo muestra.
- **Comparar la ventana del archivo contra `calendario.py`** y guardar la diferencia en
  `discrepancias`. Si el calendario acierta en todos, se puede generar hacia adelante
  con confianza; si falla, ahí está la evidencia. **Este es el entregable más valioso
  del plan.**

- [ ] **Step 2: Correr contra los 175 y reportar**

Expected: los ~145 con `PERIODO BASE` cargan; los 30 sin ella se saltan con motivo.

**Reportar explícitamente en cuántos el calendario coincidió con el archivo.** Si es
100%, decirlo. Si no, listar los que no.

---

## Task 4: El runner y el backtest

**Files:**
- Create: `app/services/garantias_modelo/runner.py`
- Create: `scripts/calcular_predicciones.py`
- Test: `tests/test_gar_modelo_runner.py`

- [ ] **Step 1: El runner**

Recorre los `GarCalculo`, llama a `exposicion_de_calculo` del plan 3 y escribe
`GarComponentePred` con `horizonte_dias=7`, `cuantil=0.9`, `modelo_version="replica-1"`.

- **Idempotente** por `uq_gar_comp_pred`.
- **No escribir predicción cuando `completo` es `False`.** Un período al que le faltan
  días da un número menor que parece bueno. Registrar el motivo en `insumos` y seguir.
  Esto aplica a la semana del 22-28 abr 2026 (los 3 días corruptos de XM).

- [ ] **Step 2: Correr el backtest y reportar**

Usar `backtest.resumen_error` del plan 3, **por componente**.

**El número que decide el proyecto:** la réplica midió 0,0057% de error mediano sobre 70
períodos. ¿Se sostiene sobre los ~145?

- Si el error mediano queda **bajo 0,1%**: la réplica está validada, la tab muestra
  números firmes reales y el estimador del día 14 se puede construir encima.
- Si queda **peor que 1%**: parar y diagnosticar antes de seguir. El bug estará en el
  calendario o en los targets, no en la aritmética — el motor ya reproduce el caso
  verificado al peso.

**Reportar los peores 10 períodos con su fecha y su ventana**, no solo el agregado. Un
error concentrado en fechas concretas es una pista; uno repartido es otra cosa.

---

## Task 5: Cerrar el contrato del frontend

**Files:**
- Modify: `app/services/garantias_modelo/servicio.py`

Hoy `frescura` y `backtest` van en `null`. El frontend ya los maneja como opcionales,
pero con datos reales se pueden poblar.

- [ ] **Step 1: `backtest`**

```json
{"cobertura_semanal": …, "cobertura_mensual": …, "ancho_mediano": …,
 "ancho_baseline": …, "n_vencimientos": …}
```

Sin estimador todavía no hay cobertura ni ancho. **Devolver `null` en esos campos y
poblar solo `n_vencimientos`**, o dejar el bloque en `null` completo. No inventar una
cobertura del 100% porque el número sea firme: es engañoso.

- [ ] **Step 2: `frescura`**

`fecha_dato_generacion` = el `max(fecha_documento)` de `xm_medida` disponible;
`dias_atraso` contra `_hoy_col()`.

- [ ] **Step 3: Generar períodos hacia adelante**

Que `construir_plan` complete el horizonte con vencimientos **futuros** desde
`calendario.py` cuando no existan en `gar_calculo`. Ahí es donde el trabajo se vuelve
visible: la tab muestra los próximos viernes antes de que XM diga nada.

Esos van con `p90: null` mientras no haya estimador, pero **con la ventana y las fechas
ya resueltas**.

- [ ] **Step 4: Verificar contra el frontend real**

El plan 1 dejó un mock en `scripts/mock-modelo-predictivo.mjs`. Levantar el backend
local y la vista contra él, y comprobar que la tab renderiza. Ver
`reference_verificacion_front_local` en memoria.

---

## Estado esperado al terminar

- El calendario genera vencimientos y ventanas sin consultar a XM.
- Los ~145 Excel con `PERIODO BASE` cargados como targets.
- **Medido y reportado** en cuántos el calendario coincide con lo que XM declaró.
- El backtest corrido sobre todos los períodos, con error por componente.
- La tab muestra números firmes reales y los próximos vencimientos.
- Suite en verde desde 2158.

## Lo que este plan no hace

- **No estima el día 14 ni produce un intervalo.** Se decide con el backtest en la mano.
- **No repara los 6 archivos corruptos de XM** (2026-04-26/27/28). Ver
  `project_xm_archivos_corruptos_abril_2026` en memoria.
- **No resuelve la carga a producción.** Todo corre en local. La vía —tarea `*_seed` o
  cron de FTP— sigue sin decidir y es lo que bloquea que esto se vea en Railway.
- **No deriva la mensual.** Ni el vencimiento (17–24 del mes) ni la ventana: se midió y
  la mejor fórmula acierta 3 de 17. Se leen del archivo. Queda la hipótesis de derivar
  el corte de mes liquidado desde `xm_medida` (Task 1, Step 4).
