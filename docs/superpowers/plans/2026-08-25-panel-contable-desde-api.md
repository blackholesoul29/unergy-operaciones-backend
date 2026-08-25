# Panel Contable desde la API de Liquidaciones — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el Panel Contable se arme desde `income_statement_data` en vez del Estado de Resultados en Excel, para todos los proyectos salvo NEU y Nitro.

**Architecture:** `_guardar_panel(db, proyecto_id, periodo, tipo, parsed, er_filename, usuario_id)` ya hace todo el trabajo —líneas base, costos de módulos, reparto por inversionista, IVA— a partir de un `dict` llamado `parsed`. Hoy ese `dict` lo produce `parsear_er()` leyendo el Excel. Se agrega un segundo productor que lo arma desde la API. Nada aguas abajo cambia.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest · httpx

**Orden de despliegue:** cada tarea se puede desplegar sola. Las tareas 1 a 5 no cambian ningún comportamiento visible: agregan capacidades que nadie invoca todavía. El interruptor se enciende en la tarea 6.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/services/panel_desde_api.py` | **Nuevo.** Traduce la respuesta de la API al `dict` que espera `_guardar_panel`. Lógica pura, sin BD ni HTTP. |
| `app/services/costos_panel.py` | **Modificar.** Agregar internet desde Starlink y póliza desde su módulo. |
| `app/api/v1/panel_contable.py` | **Modificar.** Endpoint `POST /cargar-periodo`. |
| `app/services/er_diario.py` | **Nuevo.** La tabla día por día del ER: generación y venta de `market_settlements`, importación de `disp_contracts_ftp_xm`. |
| `app/services/er_export.py` | **Nuevo.** Arma el `.xlsx` conservando la estructura del ER actual. |
| `app/main.py` | **Modificar.** DDL de los datos a corregir. |
| `tests/test_panel_desde_api.py` | **Nuevo.** |
| `tests/test_costos_panel_starlink.py` | **Nuevo.** |
| `tests/test_panel_cargar_periodo.py` | **Nuevo.** |
| `tests/test_er_diario.py` | **Nuevo.** |
| `tests/test_er_export.py` | **Nuevo.** |

---

## Task 1: El traductor de la API al formato del Panel

Es la pieza central y es **lógica pura**: recibe el dict de un proyecto tal como lo devuelve `income_statement_data` y devuelve el `parsed` que consume `_guardar_panel`. Sin BD, sin HTTP, sin sorpresas: se puede probar entera con diccionarios.

**Files:**
- Create: `app/services/panel_desde_api.py`
- Test: `tests/test_panel_desde_api.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_panel_desde_api.py
"""Traducción de income_statement_data al formato que consume el Panel.

El Panel espera exactamente el dict que produce `parsear_er()`. Estas pruebas
fijan esa forma: si cambia, `_guardar_panel` deja de entender lo que recibe.
"""
import pytest

from app.services.panel_desde_api import TOPICOS_QUE_COMPRAN, construir_parsed


def _proyecto_api(**extra):
    base = {
        "project": "vallenata",
        "project_name": "MGS 0007 La Paz Vallenata",
        "generacion_kwh": 213_000.0,
        "ingreso_bruto": 77_464_585.0,
        "venta": 77_464_585.0,
        "compra": 0.0,
        "tiene_bolsa": False,
        "comercializadores": ["Terpel"],
        "ingresos_detalle": [
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 110_000.0, "valor": 40_189_569.0},
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 103_000.0, "valor": 37_275_016.0},
        ],
        "comercializacion": [
            {"concepto": "Energía en bolsa", "name": "energia_bolsa_generador",
             "valor": 834_708.0, "iva": False},
        ],
        "warnings": [],
    }
    base.update(extra)
    return base


def test_suma_los_ingresos_de_todos_los_contratos():
    """Una planta con dos contratos factura por los dos."""
    parsed = construir_parsed(_proyecto_api())
    assert parsed["total_ingresos"] == 77_464_585.0
    assert len(parsed["ingresos_detalle"]) == 2


def test_conserva_una_linea_por_contrato():
    """Colapsarlas perdería de dónde viene cada peso."""
    parsed = construir_parsed(_proyecto_api())
    assert [d["valor"] for d in parsed["ingresos_detalle"]] == [40_189_569.0, 37_275_016.0]
```

- [ ] **Step 2: Correr la prueba y verificar que falla**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.panel_desde_api'`

- [ ] **Step 3: Escribir la implementación mínima**

```python
# app/services/panel_desde_api.py
"""Traduce `income_statement_data` al formato que consume el Panel Contable.

El Panel se arma con `_guardar_panel(..., parsed, ...)`, donde `parsed` es el dict
que hasta ahora producía `parsear_er()` leyendo el Excel. Este módulo produce ese
mismo dict desde la API, para que nada aguas abajo tenga que enterarse de cuál de
los dos se usó.

Es lógica pura a propósito -- sin BD ni HTTP -- porque es donde viven las reglas
de negocio y conviene poder probarlas con diccionarios.
"""
from __future__ import annotations

from typing import Any

# Tópicos que legítimamente compran energía. En cualquier otro proyecto una línea
# `purchase` es un contrato mal clasificado del lado de la API: se ha visto cubrir
# exactamente los mismos kWh que la venta, dejando el ingreso bruto en negativo.
# Verificado con Jessica el 2026-08-25.
TOPICOS_QUE_COMPRAN = frozenset({
    "naos1", "delta_1", "polaris_1", "baraya", "jerico_el_son",
    "ibirico", "mapale", "cacica", "piloneras",
})

# Tipos de línea de ingreso que suman. `purchase` se trata aparte.
TIPOS_VENTA = ("dispatch", "dispatch_fazni")


def construir_parsed(proyecto: dict[str, Any]) -> dict[str, Any]:
    """El `parsed` del Panel a partir de un proyecto de `income_statement_data`."""
    topico = proyecto.get("project") or ""
    detalle = proyecto.get("ingresos_detalle") or []

    ventas = [d for d in detalle if d.get("data_type") in TIPOS_VENTA]
    total_ingresos = round(sum(float(d.get("valor") or 0) for d in ventas), 2)

    return {
        "tipo": "normal",
        "comercializador": (proyecto.get("comercializadores") or [None])[0],
        "tiene_bolsa": bool(proyecto.get("tiene_bolsa")),
        "ingreso_bruto": total_ingresos,
        "total_ingresos": total_ingresos,
        "ingresos_detalle": [
            {"concepto": d.get("concepto"), "valor": float(d.get("valor") or 0),
             "hoja": None, "celda": None}
            for d in ventas
        ],
        "comercializacion": [],
        "costos": [],
        "facturas": [],
        "kwh": float(proyecto.get("generacion_kwh") or 0) or None,
        "snapshot": {},
        "warnings": [],
    }
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/panel_desde_api.py tests/test_panel_desde_api.py
git commit -m "Panel: traductor de income_statement_data al formato del Panel"
```

---

## Task 2: Las compras solo donde corresponde

**Files:**
- Modify: `app/services/panel_desde_api.py`
- Test: `tests/test_panel_desde_api.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
# Agregar a tests/test_panel_desde_api.py

COMPRA_FANTASMA = {"concepto": "Terpel Compra", "data_type": "purchase",
                   "energia_kwh": 210_740.66, "valor": -148_282_984.0}


def test_una_compra_inesperada_no_baja_el_ingreso():
    """La Paz Verso traía una compra por los mismos kWh que vendió, con el
    ingreso bruto en -71M. Restarla habría bajado la administración un 7%."""
    parsed = construir_parsed(_proyecto_api(
        project="verso", ingresos_detalle=[
            {"concepto": "Terpel Venta", "data_type": "dispatch",
             "energia_kwh": 210_740.66, "valor": 76_949_845.0},
            COMPRA_FANTASMA,
        ]))
    assert parsed["total_ingresos"] == 76_949_845.0
    assert len(parsed["ingresos_detalle"]) == 1


def test_una_compra_inesperada_queda_avisada():
    """Excluirla en silencio esconde un error de datos aguas arriba."""
    parsed = construir_parsed(_proyecto_api(
        project="verso", ingresos_detalle=[COMPRA_FANTASMA]))
    assert any("compra" in w.lower() for w in parsed["warnings"])


def test_las_compras_legitimas_si_restan():
    """Baraya sí compra: ahí la compra es parte del negocio."""
    parsed = construir_parsed(_proyecto_api(
        project="baraya", ingresos_detalle=[
            {"concepto": "Neu Venta", "data_type": "dispatch",
             "energia_kwh": 100.0, "valor": 69_436_902.0},
            {"concepto": "Neu Compra", "data_type": "purchase",
             "energia_kwh": 50.0, "valor": -12_458_625.0},
        ]))
    assert parsed["total_ingresos"] == 56_978_277.0
    assert len(parsed["ingresos_detalle"]) == 2
    assert parsed["warnings"] == []


@pytest.mark.parametrize("topico", sorted(TOPICOS_QUE_COMPRAN))
def test_ningun_topico_de_la_lista_avisa(topico):
    parsed = construir_parsed(_proyecto_api(
        project=topico, ingresos_detalle=[COMPRA_FANTASMA]))
    assert parsed["warnings"] == []


def test_no_confundir_delta_1_con_delta_2():
    """delta_2, naos2, naos3 y polaris_2 NO están en la lista."""
    for topico in ("delta_2", "naos2", "naos3", "polaris_2"):
        parsed = construir_parsed(_proyecto_api(
            project=topico, ingresos_detalle=[COMPRA_FANTASMA]))
        assert parsed["warnings"], f"{topico} debería avisar"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: FAIL — `test_las_compras_legitimas_si_restan` da 69.436.902 en vez de 56.978.277

- [ ] **Step 3: Implementar**

Reemplazar el cuerpo de `construir_parsed` en `app/services/panel_desde_api.py`:

```python
def construir_parsed(proyecto: dict[str, Any]) -> dict[str, Any]:
    """El `parsed` del Panel a partir de un proyecto de `income_statement_data`."""
    topico = proyecto.get("project") or ""
    detalle = proyecto.get("ingresos_detalle") or []
    avisos: list[str] = []

    ventas = [d for d in detalle if d.get("data_type") in TIPOS_VENTA]
    compras = [d for d in detalle if d.get("data_type") == "purchase"]

    # Una compra en un proyecto que no compra es un contrato mal clasificado. Se
    # deja fuera del cálculo -- restarla bajaría la administración sin que nadie
    # se entere -- pero se avisa, para que el error salga a la luz.
    if compras and topico not in TOPICOS_QUE_COMPRAN:
        total_compra = sum(abs(float(d.get("valor") or 0)) for d in compras)
        avisos.append(
            f"La API reporta {len(compras)} compra(s) por {total_compra:,.0f} en un "
            f"proyecto que no compra energía. Se excluyeron del ingreso: "
            f"revisar la clasificación del contrato en la API."
        )
        compras = []

    lineas = ventas + compras
    total_ingresos = round(sum(float(d.get("valor") or 0) for d in lineas), 2)

    return {
        "tipo": "normal",
        "comercializador": (proyecto.get("comercializadores") or [None])[0],
        "tiene_bolsa": bool(proyecto.get("tiene_bolsa")),
        "ingreso_bruto": total_ingresos,
        "total_ingresos": total_ingresos,
        "ingresos_detalle": [
            {"concepto": d.get("concepto"), "valor": float(d.get("valor") or 0),
             "hoja": None, "celda": None}
            for d in lineas
        ],
        "comercializacion": [],
        "costos": [],
        "facturas": [],
        "kwh": float(proyecto.get("generacion_kwh") or 0) or None,
        "snapshot": {},
        "warnings": avisos,
    }
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: PASS, 16 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/panel_desde_api.py tests/test_panel_desde_api.py
git commit -m "Panel desde API: excluir y avisar las compras inesperadas"
```

---

## Task 3: Comercialización, con FAZNI y cargo por confiabilidad

El Excel no trae esas dos filas y la API sí (parcialmente). Son cargos reales: en julio suman 10.564.281 que hoy no se están cobrando.

**Files:**
- Modify: `app/services/panel_desde_api.py`
- Test: `tests/test_panel_desde_api.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
# Agregar a tests/test_panel_desde_api.py

COMERCIALIZACION_API = [
    {"concepto": "Energía en bolsa", "name": "energia_bolsa_generador",
     "valor": 616_662.0, "iva": False},
    {"concepto": "Servicios de despacho", "name": "servicios_despacho_generador",
     "valor": 500_558.0, "iva": False},
    {"concepto": "FAZNI", "name": "fazni_generador", "valor": 59_000.0, "iva": False},
    {"concepto": "Cargo por confiabilidad", "name": "cargo_confiabilidad_generador",
     "valor": 40_000.0, "iva": False},
]


def test_la_comercializacion_entra_en_negativo():
    """Son costos: el Panel guarda los costos con signo negativo."""
    parsed = construir_parsed(_proyecto_api(comercializacion=COMERCIALIZACION_API))
    valores = {l["concepto"]: l["valor"] for l in parsed["comercializacion"]}
    assert valores["Energía en bolsa"] == -616_662.0


def test_trae_fazni_y_cargo_por_confiabilidad():
    """El Excel no las tiene; son 10,5M de costo real en julio."""
    parsed = construir_parsed(_proyecto_api(comercializacion=COMERCIALIZACION_API))
    conceptos = {l["concepto"] for l in parsed["comercializacion"]}
    assert "FAZNI" in conceptos
    assert "Cargo por confiabilidad" in conceptos


def test_los_warnings_de_la_api_se_conservan():
    """Si la API avisa que le faltó una fila, sus cifras están incompletas y eso
    tiene que llegar a la pantalla, no quedarse en el JSON."""
    parsed = construir_parsed(_proyecto_api(
        warnings=["Falta la fila 'fazni_generador'."]))
    assert any("fazni" in w.lower() for w in parsed["warnings"])


def test_sin_comercializacion_no_revienta():
    parsed = construir_parsed(_proyecto_api(comercializacion=[]))
    assert parsed["comercializacion"] == []
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: FAIL — `parsed["comercializacion"]` viene vacío

- [ ] **Step 3: Implementar**

En `app/services/panel_desde_api.py`, reemplazar `"comercializacion": [],` por
`"comercializacion": _comercializacion(proyecto),` y `"warnings": avisos,` por
`"warnings": avisos + [str(w) for w in (proyecto.get("warnings") or [])],`.
Agregar antes de `construir_parsed`:

```python
def _comercializacion(proyecto: dict[str, Any]) -> list[dict[str, Any]]:
    """Los costos de XM que reparte la API, en negativo como el resto de costos.

    Incluye `fazni_generador` y `cargo_confiabilidad_generador`, que el Excel no
    trae. La API a veces no logra crear esas dos filas -- lo avisa en `warnings`
    y por eso los warnings se conservan tal cual: un cero ahí no significa que el
    cargo no exista, significa que no se pudo calcular.
    """
    return [
        {
            "concepto": c.get("concepto"),
            "valor": -abs(float(c.get("valor") or 0)),
            "hoja": None,
            "celda": None,
        }
        for c in (proyecto.get("comercializacion") or [])
    ]
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_panel_desde_api.py -q`
Expected: PASS, 20 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/panel_desde_api.py tests/test_panel_desde_api.py
git commit -m "Panel desde API: comercializacion con FAZNI y cargo por confiabilidad"
```

---

## Task 4: Elegir el contrato de representación correcto

Hay 66 contratos de representación para 38 proyectos y algunos con tarifas
contradictorias: Joropo tiene tres, dos en 0 y uno en 5. El código toma el de menor
`id` y **hoy acierta en los 38** -- no hay ninguno donde el de menor id tenga menos
tarifa que otro disponible. Pero eso es suerte, no diseño: basta que se borre el
contrato 108 de Joropo o que aparezca uno con id menor para que empiece a leer ceros
en silencio. Esta tarea cambia la casualidad por una regla.

**Files:**
- Modify: `app/services/costos_panel.py:138-148`
- Test: `tests/test_costos_panel_contrato.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_costos_panel_contrato.py
"""Cuál contrato de representación manda cuando hay varios.

Un proyecto puede tener más de uno -- 66 filas para 38 proyectos -- y algunos con
tarifas contradictorias: Joropo tiene tres, dos con las tarifas en cero. Hoy gana
el de menor id, que da la casualidad de ser el correcto en los 38 proyectos. Estas
pruebas fijan la regla para que deje de depender de la casualidad.
"""
import types

from app.services.costos_panel import elegir_contrato_representacion


def _c(id_, estado="vigente", rep=5.0, cgm=5.0, admin=0.038):
    return types.SimpleNamespace(id=id_, estado=estado, tarifa_representacion=rep,
                                 tarifa_cgm=cgm, tarifa_admin=admin)


def test_prefiere_el_vigente():
    assert elegir_contrato_representacion([
        _c(1, estado="terminado"), _c(2, estado="vigente")]).id == 2


def test_entre_vigentes_prefiere_el_que_tiene_tarifas():
    """El caso Joropo: dos en cero y uno con tarifa real."""
    assert elegir_contrato_representacion([
        _c(1, rep=0.0, cgm=0.0), _c(2, rep=5.0, cgm=5.0)]).id == 2


def test_a_igualdad_de_condiciones_gana_el_mas_reciente():
    assert elegir_contrato_representacion([_c(1), _c(9), _c(4)]).id == 9


def test_sin_contratos_devuelve_none():
    assert elegir_contrato_representacion([]) is None


def test_si_ninguno_esta_vigente_igual_devuelve_uno():
    """Mejor la tarifa de un contrato terminado que ninguna: el Panel decide
    después si la usa."""
    assert elegir_contrato_representacion([
        _c(1, estado="terminado"), _c(5, estado="terminado")]).id == 5
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_costos_panel_contrato.py -q`
Expected: FAIL con `ImportError: cannot import name 'elegir_contrato_representacion'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/costos_panel.py`:

```python
def elegir_contrato_representacion(contratos):
    """El contrato que manda cuando un proyecto tiene varios.

    Ordena por: vigente primero, luego el que sí tiene tarifas cargadas, y a
    igualdad de condiciones el más reciente. Antes se tomaba el de menor `id`:
    hoy acierta en los 38 proyectos, pero Joropo tiene dos contratos con las
    tarifas en cero esperando a que un cambio de ids los deje ganar.
    """
    if not contratos:
        return None

    def _puntaje(c):
        tiene_tarifa = bool(c.tarifa_representacion or c.tarifa_cgm or c.tarifa_admin)
        return (c.estado == "vigente", tiene_tarifa, c.id)

    return max(contratos, key=_puntaje)
```

Y reemplazar en `valores_facturas_modulo` el bloque que hoy dice:

```python
    c = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.proyecto_id == proyecto_id)
        .order_by(ContratoServicio.id)
        .first()
    )
    if c is None:
        return {}
```

por:

```python
    c = elegir_contrato_representacion(
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.proyecto_id == proyecto_id)
        .all()
    )
    if c is None:
        return {}
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_costos_panel_contrato.py tests/ -q -k "costos_panel or panel"`
Expected: PASS, sin regresiones

- [ ] **Step 5: Commit**

```bash
git add app/services/costos_panel.py tests/test_costos_panel_contrato.py
git commit -m "Costos del panel: elegir el contrato de representacion vigente y con tarifa"
```

---

## Task 5: Datos a corregir en producción

Sin esto, Cedillanos no cruza con la API y dos proyectos se quedan sin tarifas.

**Files:**
- Modify: `app/main.py` (al final de `_PENDING_DDLS`, antes del `]`)

- [ ] **Step 1: Agregar los DDL**

```python
    # Cedillanos liquida por `cedillanosexc` ("Cedillanos_excedentes"), no por
    # `cedillanos`, que en la API es el lado de consumo (from_generator=False).
    # Con el tópico corregido cuadra al peso con el Panel: 21.140.803 (2026-08-25).
    "UPDATE proyectos SET topico_liquidaciones = 'cedillanosexc' "
    "WHERE sub_project = 'cedillanos' AND topico_liquidaciones IS NULL",
    # Tarifas que faltaban y que hasta ahora se calculaban por fuera del Excel.
    # Cedillanos administra al 5%, no al 3,8% del resto (confirmado 2026-08-25).
    "UPDATE contratos_servicio SET tarifa_admin = 0.05 "
    "WHERE servicio_aplica = 'representacion' AND tarifa_admin IS NULL "
    "  AND proyecto_id = (SELECT id FROM proyectos WHERE sub_project = 'cedillanos')",
```

- [ ] **Step 2: Verificar que no rompe las pruebas**

Run: `python -m pytest -q`
Expected: PASS, todas

- [ ] **Step 3: Commit y desplegar**

```bash
git add app/main.py
git commit -m "Datos: topico de liquidaciones de Cedillanos y su tarifa de administracion"
git push origin master
```

- [ ] **Step 4: Verificar en producción tras el deploy**

```bash
railway run --service postgres python -c "
import os, psycopg
dsn=(f\"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}\"
     f\"@{os.environ['RAILWAY_TCP_PROXY_DOMAIN']}:{os.environ['RAILWAY_TCP_PROXY_PORT']}\"
     f\"/{os.environ['POSTGRES_DB']}?sslmode=disable\")
with psycopg.connect(dsn) as c, c.cursor() as k:
    k.execute(\"SELECT topico_liquidaciones FROM proyectos WHERE sub_project='cedillanos'\")
    print('topico:', k.fetchone())
"
```
Expected: `topico: ('cedillanosexc',)`

- [ ] **Step 5: Crear a mano el contrato de Sabana de Torres**

No va por DDL: crear un contrato de servicio es un acto de negocio, no una
migración. Desde la vista de Contratos de servicio, para *MiniGranja 0033 -
Sabana de Torres*: `servicio_aplica = representacion`, `tarifa_admin = 0.038`,
`tarifa_representacion = 6`, `tarifa_cgm = 6`.

---

## Task 6: Internet desde Starlink

Verificado contra 2026-07: 26 proyectos, los 26 al peso, 3.894.133 en ambos lados.

**Files:**
- Modify: `app/services/costos_panel.py`
- Test: `tests/test_costos_panel_starlink.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_costos_panel_starlink.py
"""Internet sale de la factura real de Starlink, no del Excel.

Cruzado contra 2026-07: los 26 proyectos que tienen internet en el Panel cuadran
al peso con Starlink. Las líneas de Starlink que no cruzan son plantas no
operativas, y por eso el total de Starlink es mayor.
"""
import types

from app.services.costos_panel import CONCEPTO_INTERNET, internet_desde_starlink


def _linea(proyecto_id, sin_iva, iva, excluido=False):
    return types.SimpleNamespace(proyecto_id=proyecto_id, sin_iva=sin_iva,
                                 iva=iva, excluido=excluido)


def test_devuelve_la_base_en_negativo():
    out = internet_desde_starlink([_linea(1, 64_706.0, 12_294.0)])
    assert out[CONCEPTO_INTERNET]["valor"] == -64_706.0


def test_marca_la_fuente():
    """La vista muestra de dónde salió cada costo."""
    out = internet_desde_starlink([_linea(1, 64_706.0, 12_294.0)])
    assert out[CONCEPTO_INTERNET]["fuente"] == "starlink"


def test_suma_varias_lineas_del_mismo_proyecto():
    """Perija tiene dos sitios: 64.706 + 64.707 = 129.413."""
    out = internet_desde_starlink([_linea(1, 64_706.0, 0.0), _linea(1, 64_707.0, 0.0)])
    assert out[CONCEPTO_INTERNET]["valor"] == -129_413.0


def test_ignora_las_lineas_excluidas():
    out = internet_desde_starlink([_linea(1, 64_706.0, 0.0),
                                   _linea(1, 999.0, 0.0, excluido=True)])
    assert out[CONCEPTO_INTERNET]["valor"] == -64_706.0


def test_sin_lineas_no_devuelve_el_concepto():
    """Devolver 0 pisaría el valor del Excel con un cero falso."""
    assert internet_desde_starlink([]) == {}
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_costos_panel_starlink.py -q`
Expected: FAIL con `ImportError: cannot import name 'internet_desde_starlink'`

- [ ] **Step 3: Implementar**

Agregar a `app/services/costos_panel.py`:

```python
def internet_desde_starlink(lineas) -> dict[str, dict]:
    """Internet del período a partir de la factura de Starlink.

    `lineas` son las `StarlinkFacturaLinea` del proyecto en ese período. Se suman
    porque un proyecto puede tener más de un sitio. El IVA no se devuelve: el
    Panel lo deriva por cliente al leer.

    Sin líneas devuelve `{}` y no `0`: un cero pisaría el valor que traiga el ER.
    """
    vivas = [l for l in lineas if not getattr(l, "excluido", False)]
    if not vivas:
        return {}
    base = sum(float(l.sin_iva or 0) for l in vivas)
    return {CONCEPTO_INTERNET: {"grupo": "costos", "valor": -abs(round(base, 2)),
                                "fuente": "starlink"}}
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_costos_panel_starlink.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Conectarlo a `valores_modulo_costos`**

En `app/services/costos_panel.py`, dentro de `valores_modulo_costos`, después de
resolver O&M y arriendo, agregar:

```python
    # Internet: manda la factura real de Starlink sobre el contrato de servicio,
    # que solo tiene tarifa en 4 proyectos.
    from app.models.starlink import StarlinkFactura, StarlinkFacturaLinea

    lineas_sl = (
        db.query(StarlinkFacturaLinea)
        .join(StarlinkFactura, StarlinkFactura.id == StarlinkFacturaLinea.factura_id)
        .filter(StarlinkFacturaLinea.proyecto_id == proyecto_id,
                StarlinkFactura.periodo == periodo)
        .all()
    )
    out.update(internet_desde_starlink(lineas_sl))
```

- [ ] **Step 6: Correr todas las pruebas**

Run: `python -m pytest -q`
Expected: PASS, todas

- [ ] **Step 7: Commit**

```bash
git add app/services/costos_panel.py tests/test_costos_panel_starlink.py
git commit -m "Costos del panel: internet desde la factura de Starlink"
```

---

## Task 7: El endpoint que arma el período completo

Aquí se enciende el interruptor. Hasta esta tarea nada cambió de comportamiento.

**Files:**
- Modify: `app/api/v1/panel_contable.py`
- Test: `tests/test_panel_cargar_periodo.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_panel_cargar_periodo.py
"""Armar los paneles de un período desde la API, sin subir archivos.

NEU y Nitro se saltan a propósito: su dato de API está malo y siguen cargando el
Excel. Saltarlos en silencio sería peor que no hacer nada, así que el endpoint
informa cuáles omitió.
"""
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import panel_contable
from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.base import Base
from app.models.clientes import Cliente
from app.models.panel_contable import ClasificacionLiquidacion, PanelContable
from app.models.proyectos import Proyecto


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Proyecto(id=1, nombre_comercial="MGS 0007 La Paz Vallenata",
                   sub_project="vallenata"))
    s.add(Proyecto(id=2, nombre_comercial="Minigranja Solar Baraya",
                   sub_project="baraya"))
    s.add(ClasificacionLiquidacion(proyecto_id=2, periodo="2026-07", tipo="neu"))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(panel_contable.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(
        id=1, rol=types.SimpleNamespace(value="admin"))
    return TestClient(app)


RESPUESTA_API = {
    "month": 7, "year": 2026, "version": "txf", "count": 2,
    "results": [
        {"project": "vallenata", "project_name": "MGS 0007 La Paz Vallenata",
         "generacion_kwh": 213_000.0, "ingreso_bruto": 77_464_585.0,
         "venta": 77_464_585.0, "compra": 0.0, "tiene_bolsa": False,
         "comercializadores": ["Terpel"],
         "ingresos_detalle": [{"concepto": "Terpel Venta", "data_type": "dispatch",
                               "energia_kwh": 213_000.0, "valor": 77_464_585.0}],
         "comercializacion": [], "participantes": [], "warnings": []},
        {"project": "baraya", "project_name": "Minigranja Solar Baraya",
         "generacion_kwh": 100.0, "ingreso_bruto": 56_978_276.0,
         "venta": 69_436_902.0, "compra": 12_458_625.0, "tiene_bolsa": True,
         "comercializadores": ["Neu"], "ingresos_detalle": [],
         "comercializacion": [], "participantes": [], "warnings": []},
    ],
    "errors": [],
}


def test_arma_el_panel_de_un_proyecto_normal(client, db, monkeypatch):
    monkeypatch.setattr(panel_contable.liquidaciones_api, "estado_resultados_json",
                        lambda **kw: RESPUESTA_API)
    r = client.post("/api/v1/panel-contable/cargar-periodo",
                    json={"periodo": "2026-07", "tipo": "oficial"})
    assert r.status_code == 200, r.text
    panel = db.query(PanelContable).filter(PanelContable.proyecto_id == 1).one()
    assert float(panel.ingreso_bruto_cop) == 77_464_585.0


def test_no_toca_los_neu(client, db, monkeypatch):
    """Baraya es NEU: su panel sigue siendo el del Excel."""
    monkeypatch.setattr(panel_contable.liquidaciones_api, "estado_resultados_json",
                        lambda **kw: RESPUESTA_API)
    client.post("/api/v1/panel-contable/cargar-periodo",
                json={"periodo": "2026-07", "tipo": "oficial"})
    assert db.query(PanelContable).filter(PanelContable.proyecto_id == 2).count() == 0


def test_informa_que_omitio_los_neu(client, monkeypatch):
    """Saltarlos en silencio haría creer que el período quedó completo."""
    monkeypatch.setattr(panel_contable.liquidaciones_api, "estado_resultados_json",
                        lambda **kw: RESPUESTA_API)
    r = client.post("/api/v1/panel-contable/cargar-periodo",
                    json={"periodo": "2026-07", "tipo": "oficial"})
    assert "Minigranja Solar Baraya" in str(r.json()["omitidos"])


def test_rechaza_un_periodo_mal_formado(client):
    r = client.post("/api/v1/panel-contable/cargar-periodo",
                    json={"periodo": "julio", "tipo": "oficial"})
    assert r.status_code == 422
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_panel_cargar_periodo.py -q`
Expected: FAIL con 404 — el endpoint no existe

- [ ] **Step 3: Implementar**

En `app/api/v1/panel_contable.py`, agregar el import arriba:

```python
from app.services import liquidaciones_api
from app.services.panel_desde_api import construir_parsed
```

Y el endpoint, después de `cargar_er`:

```python
class CargarPeriodoIn(BaseModel):
    periodo: str            # YYYY-MM
    tipo: str = "oficial"   # preliquidacion | oficial
    version: str = "txf"


@router.post("/cargar-periodo")
def cargar_periodo(
    data: CargarPeriodoIn,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(_require_write),
):
    """Arma los paneles del período desde la API, sin subir archivos.

    NEU y Nitro se omiten a propósito: su dato de API está malo y siguen cargando
    el Excel. Se informan en `omitidos` -- saltarlos en silencio haría creer que
    el período quedó completo.
    """
    try:
        y, m = data.periodo.strip().split("-")
        periodo = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    try:
        er = liquidaciones_api.estado_resultados_json(
            month=int(m), year=int(y), version=data.version)
    except liquidaciones_api.LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    # Un proyecto sin registro de clasificación es 'normal'.
    clasif = {
        c.proyecto_id: c.tipo
        for c in db.query(ClasificacionLiquidacion)
        .filter(ClasificacionLiquidacion.periodo == periodo).all()
    }
    por_topico = {
        (p.topico_liquidaciones or p.sub_project): p
        for p in db.query(Proyecto).filter(Proyecto.deleted_at.is_(None)).all()
        if (p.topico_liquidaciones or p.sub_project)
    }

    armados, omitidos, sin_cruce = [], [], []
    for proy_api in (er.get("results") or []):
        proyecto = por_topico.get(proy_api.get("project") or "")
        if proyecto is None:
            sin_cruce.append(proy_api.get("project"))
            continue
        if clasif.get(proyecto.id, "normal") != "normal":
            omitidos.append({"proyecto": proyecto.nombre_comercial,
                             "motivo": clasif[proyecto.id]})
            continue
        _guardar_panel(db, proyecto.id, periodo, data.tipo,
                       construir_parsed(proy_api), None, usuario.id)
        armados.append(proyecto.nombre_comercial)

    return {"periodo": periodo, "tipo": data.tipo,
            "armados": len(armados), "proyectos": armados,
            "omitidos": omitidos, "sin_cruce": sin_cruce,
            "errores_api": er.get("errors") or []}
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_panel_cargar_periodo.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Correr todas las pruebas**

Run: `python -m pytest -q`
Expected: PASS, todas

- [ ] **Step 6: Commit**

```bash
git add app/api/v1/panel_contable.py tests/test_panel_cargar_periodo.py
git commit -m "Panel: armar el periodo completo desde la API, sin subir archivos"
```

---

## Task 8: Contraste contra el Excel antes de confiar

Antes de que alguien liquide con esto, hay que ver en qué se diferencia de lo que produjo el Excel. Las diferencias esperadas están en el spec; cualquier otra es un fallo.

**Files:**
- Modify: `app/api/v1/panel_contable.py`
- Test: `tests/test_panel_contraste.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_panel_contraste.py
"""Comparar lo que da la API contra lo que dio el Excel, sin guardar nada.

Es el paso previo a confiar en el cambio: deja ver proyecto por proyecto en qué
se diferencian, para distinguir las diferencias esperadas (administración de los
9 GD, FAZNI y confiabilidad) de un fallo de traducción.
"""
from app.api.v1.panel_contable import comparar_lineas


def test_marca_lo_que_solo_esta_en_uno_de_los_dos():
    dif = comparar_lineas(
        excel=[{"grupo": "facturas", "concepto": "Administración", "valor": -5_836_668.0}],
        api=[],
    )
    assert dif[0]["solo_en"] == "excel"


def test_marca_las_diferencias_de_valor():
    dif = comparar_lineas(
        excel=[{"grupo": "ingresos", "concepto": "Terpel", "valor": 100.0}],
        api=[{"grupo": "ingresos", "concepto": "Terpel", "valor": 150.0}],
    )
    assert dif[0]["excel"] == 100.0 and dif[0]["api"] == 150.0


def test_no_reporta_lo_que_coincide():
    assert comparar_lineas(
        excel=[{"grupo": "ingresos", "concepto": "Terpel", "valor": 100.0}],
        api=[{"grupo": "ingresos", "concepto": "Terpel", "valor": 100.0}],
    ) == []


def test_tolera_diferencias_de_redondeo():
    """Un peso de diferencia por redondeo no es una discrepancia."""
    assert comparar_lineas(
        excel=[{"grupo": "ingresos", "concepto": "T", "valor": 100.00}],
        api=[{"grupo": "ingresos", "concepto": "T", "valor": 100.004}],
    ) == []
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_panel_contraste.py -q`
Expected: FAIL con `ImportError: cannot import name 'comparar_lineas'`

- [ ] **Step 3: Implementar**

Agregar a `app/api/v1/panel_contable.py`:

```python
def comparar_lineas(excel: list[dict], api: list[dict]) -> list[dict]:
    """Diferencias entre dos juegos de líneas, por (grupo, concepto).

    Solo devuelve lo que NO cuadra: una lista vacía significa que la API produce
    exactamente lo mismo que el Excel. Se toleran diferencias menores a un peso,
    que son redondeo y no discrepancia.
    """
    def _indexar(lineas):
        out: dict[tuple, float] = {}
        for l in lineas:
            clave = (l["grupo"], l["concepto"])
            out[clave] = out.get(clave, 0.0) + float(l.get("valor") or 0)
        return out

    ex, ap = _indexar(excel), _indexar(api)
    diferencias = []
    for clave in sorted(set(ex) | set(ap)):
        v_ex, v_ap = ex.get(clave), ap.get(clave)
        if v_ex is not None and v_ap is not None and abs(v_ex - v_ap) < 1:
            continue
        diferencias.append({
            "grupo": clave[0], "concepto": clave[1],
            "excel": v_ex, "api": v_ap,
            "solo_en": "excel" if v_ap is None else ("api" if v_ex is None else None),
            "diferencia": round((v_ap or 0) - (v_ex or 0), 2),
        })
    return diferencias
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_panel_contraste.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Exponerlo como endpoint de solo lectura**

```python
@router.get("/contraste")
def contraste_api_vs_excel(
    periodo: str = Query(..., description="YYYY-MM"),
    tipo: str = Query("oficial"),
    version: str = Query("txf"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """En qué se diferencia lo que daría la API de lo que dio el Excel.

    No guarda nada: es para mirar antes de decidir. Las diferencias esperadas
    están en el spec; cualquier otra hay que entenderla antes de liquidar.
    """
    try:
        y, m = periodo.strip().split("-")
        periodo = f"{int(y):04d}-{int(m):02d}"
    except Exception:
        raise HTTPException(422, "El período debe tener formato YYYY-MM")

    try:
        er = liquidaciones_api.estado_resultados_json(
            month=int(m), year=int(y), version=version)
    except liquidaciones_api.LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    api_por_topico = {p["project"]: p for p in (er.get("results") or [])}
    salida = []
    paneles = (
        db.query(PanelContable)
        .filter(PanelContable.periodo == periodo, PanelContable.tipo == tipo)
        .all()
    )
    for panel in paneles:
        proyecto = db.get(Proyecto, panel.proyecto_id)
        topico = proyecto.topico_liquidaciones or proyecto.sub_project
        proy_api = api_por_topico.get(topico or "")
        if proy_api is None:
            salida.append({"proyecto": proyecto.nombre_comercial,
                           "sin_dato_en_api": True})
            continue
        # Las líneas del panel están divididas por inversionista: se reagrupan al
        # 100% para poder compararlas con lo que produce la API.
        excel = [{"grupo": l.grupo, "concepto": l.concepto,
                  "valor": float(l.valor_cop or 0)} for l in panel.lineas]
        parsed = construir_parsed(proy_api)
        api_lineas = _construir_lineas_base(parsed)
        salida.append({
            "proyecto": proyecto.nombre_comercial,
            "topico": topico,
            "diferencias": comparar_lineas(excel, api_lineas),
            "avisos": parsed["warnings"],
        })
    return {"periodo": periodo, "tipo": tipo, "proyectos": salida}
```

- [ ] **Step 6: Correr todas las pruebas y commitear**

```bash
python -m pytest -q
git add app/api/v1/panel_contable.py tests/test_panel_contraste.py
git commit -m "Panel: endpoint de contraste API vs Excel, sin guardar nada"
```

---

## Task 9: Los datos diarios del ER

El ER no es un resumen: tiene una tabla **día por día** con generación, importación
y venta, y de ahí salen los totales. Sin eso, el archivo que generemos no se parece
al que hoy usan.

Verificado contra `sanagustin_elektra` (el ER de ejemplo) y `agustin_2`:

| Columna del ER | De dónde sale |
|---|---|
| Generación (kWh) | `market_settlements`, líneas `dispatch`, por día |
| **Importación (kWh)** | **suma de `con_hour01..24` de `disp_contracts_ftp_xm`** |
| `{comercializador}` Venta (kwh) y ($) | `market_settlements`, por día |

La importación cuadra al peso: `agustin_2` reporta `importacion_kwh = 621,66` en
`income_statement_data` y la suma de sus 31 días de `disp_contracts_ftp_xm` da
exactamente 621,66.

**Files:**
- Create: `app/services/er_diario.py`
- Test: `tests/test_er_diario.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_er_diario.py
"""La tabla día por día del Estado de Resultados.

La importación es el consumo: la suma de las 24 horas de `disp_contracts_ftp_xm`.
Verificado contra agustin_2 en 2026-07, donde da 621,66 igual que el
`importacion_kwh` mensual que reporta la API.
"""
from app.services.er_diario import construir_tabla_diaria


def _despacho(fecha, energia, precio, tipo="dispatch"):
    return {"date": fecha, "energy": energia, "price": precio, "data_type": tipo}


def _consumo(fecha, por_hora):
    fila = {"date": fecha}
    fila.update({f"con_hour{h:02d}": por_hora for h in range(1, 25)})
    return fila


def test_una_fila_por_dia():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 5629.63, 4_491_783.26),
                   _despacho("2026-07-02", 3597.46, 2_839_856.69)],
        consumos=[_consumo("2026-07-01", 1.0), _consumo("2026-07-02", 1.0)],
    )
    assert [f["fecha"] for f in tabla] == ["2026-07-01", "2026-07-02"]


def test_la_importacion_es_la_suma_de_las_24_horas():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0)],
        consumos=[_consumo("2026-07-01", 0.94)],
    )
    assert tabla[0]["importacion_kwh"] == 22.56


def test_un_dia_sin_consumo_va_en_cero_no_desaparece():
    """La tabla tiene que traer todos los días del período."""
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-05", 100.0, 1000.0)], consumos=[])
    assert tabla[0]["importacion_kwh"] == 0.0


def test_un_dia_solo_con_consumo_tambien_aparece():
    """Un día sin generación pero con consumo es información, no un hueco."""
    tabla = construir_tabla_diaria(
        despachos=[], consumos=[_consumo("2026-07-05", 1.0)])
    assert tabla[0]["fecha"] == "2026-07-05"
    assert tabla[0]["generacion_kwh"] == 0.0


def test_suma_varios_contratos_del_mismo_dia():
    """Una planta con dos contratos despacha dos veces el mismo día."""
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-01", 50.0, 500.0)],
        consumos=[])
    assert tabla[0]["generacion_kwh"] == 150.0
    assert tabla[0]["venta_cop"] == 1500.0


def test_las_compras_no_suman_como_generacion():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-01", 30.0, -300.0, tipo="purchase")],
        consumos=[])
    assert tabla[0]["generacion_kwh"] == 100.0


def test_los_totales_cuadran_con_las_filas():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-02", 200.0, 2000.0)],
        consumos=[_consumo("2026-07-01", 1.0)])
    assert sum(f["generacion_kwh"] for f in tabla) == 300.0
    assert sum(f["importacion_kwh"] for f in tabla) == 24.0
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_er_diario.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.er_diario'`

- [ ] **Step 3: Implementar**

```python
# app/services/er_diario.py
"""La tabla día por día del Estado de Resultados.

El ER no es un resumen: arranca con una fila por día -- generación, importación y
venta -- y de ahí salen los totales. Se arma cruzando dos históricos de la API:

* `market_settlements` da la generación y la venta de cada día.
* `disp_contracts_ftp_xm` da el consumo por hora; la importación del día es la
  suma de sus 24 horas. Verificado contra agustin_2 en 2026-07: sus 31 días suman
  621,66, que es exactamente el `importacion_kwh` mensual que reporta la API.

Lógica pura: recibe las listas ya traídas y devuelve las filas.
"""
from __future__ import annotations

from typing import Any

TIPOS_VENTA = ("dispatch", "dispatch_fazni")


def construir_tabla_diaria(despachos: list[dict[str, Any]],
                           consumos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Una fila por día, ordenadas.

    Un día aparece si tiene generación **o** consumo: si solo se tomaran los días
    con despacho, una planta parada se vería sin importación cuando en realidad
    siguió consumiendo.
    """
    filas: dict[str, dict[str, Any]] = {}

    def _fila(fecha: str) -> dict[str, Any]:
        return filas.setdefault(fecha, {
            "fecha": fecha, "generacion_kwh": 0.0,
            "importacion_kwh": 0.0, "venta_kwh": 0.0, "venta_cop": 0.0,
        })

    for d in despachos:
        if d.get("data_type") not in TIPOS_VENTA:
            continue
        f = _fila(str(d.get("date") or "")[:10])
        energia = float(d.get("energy") or 0)
        f["generacion_kwh"] = round(f["generacion_kwh"] + energia, 2)
        f["venta_kwh"] = round(f["venta_kwh"] + energia, 2)
        f["venta_cop"] = round(f["venta_cop"] + float(d.get("price") or 0), 2)

    for c in consumos:
        f = _fila(str(c.get("date") or "")[:10])
        horas = sum(float(c.get(f"con_hour{h:02d}") or 0) for h in range(1, 25))
        f["importacion_kwh"] = round(f["importacion_kwh"] + horas, 2)

    return [filas[k] for k in sorted(filas)]
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_er_diario.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/er_diario.py tests/test_er_diario.py
git commit -m "ER: tabla diaria con generacion, importacion y venta"
```

---

## Task 10: El Estado de Resultados propio, con la estructura real

La estética se puede mejorar, pero **la estructura se conserva**. Del ER de ejemplo
(*QUANTUM ENERGY · GRANJA SOLAR SAN AGUSTIN, 7 2026*), `Sheet1` tiene seis bloques:

| Bloque | Contenido |
|---|---|
| Tabla diaria (C3:I35) | Fecha · Generación (kWh) · **Importación (kWh)** · `{com}` Venta bolsa (kwh) · `{com}` Venta bolsa ($) · Ingresos brutos · Ingreso inversionista neto plataforma. Con fila TOTAL |
| Tarifa actualizada | Un valor |
| Ingresos y costos XM | Arranque y parada · Energía en Bolsa · IVA (Com/Gen) · Servicios Despacho CND (Com/Gen) · Servicios Administración SIC (Com/Gen) · **Total Comercialización** |
| Ingresos y costos | Ingreso bruto venta energía · Intereses · Indemnización · Ajustes · **Total Ingresos** |
| Costos operativos | Cobro OPEX Representación · CGM · Arrendamiento · Fondo de mantenimiento · Póliza · Servicios públicos e internet · **Total Costos Operativos fijos** · **Total costos operativos + Comercialización** |
| Bloque por inversionista (F51:G74) | Nombre · % participación · Energía · Ingresos brutos · Costos XM · **Valor a pagar** · los 7 cobros numerados · IVA · **Factura UNERGY** · Tarifa bruta · Tarifa neta · Tarifa Comercialización / Representación / CGM · % Admin |

Y tres hojas más: `Arranque y Parada` (por día), `Precios Bolsa Horarios` (24 h × día)
y `Precios Bolsa Diarios`.

**Alcance de esta tarea:** `Sheet1` completa. Las tres hojas de apoyo quedan para
después: son insumos de cálculo, no lo que lee contabilidad.

**Files:**
- Create: `app/services/er_export.py`
- Test: `tests/test_er_export.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
# tests/test_er_export.py
"""El ER que generamos nosotros, en Excel.

Se conserva la estructura del que usan hoy: tabla diaria arriba, los tres bloques
de totales, y el bloque por inversionista a la derecha. Con los valores ya
calculados -- no fórmulas sin evaluar, que es el defecto del archivo de la API y
la razón por la que hoy hace falta LibreOffice.
"""
import io
import types

from openpyxl import load_workbook

from app.services.er_export import generar_er_xlsx


def _linea(grupo, concepto, valor, inv="QUANTUM ENERGY S.A.S", pct=100.0):
    return types.SimpleNamespace(grupo=grupo, concepto=concepto, valor_cop=valor,
                                 inversionista_nombre=inv, porcentaje=pct, orden=0)


PANEL = types.SimpleNamespace(
    periodo="2026-07",
    comercializador="UNERGY ENERGIA DIGITAL S.A.S ESP",
    lineas=[
        _linea("ingresos", "Venta bolsa", 118_673_860.5),
        _linea("comercializacion", "Energia en Bolsa (Gen)", -603_083.64),
        _linea("comercializacion", "Arranque y parada", -171_129.13),
        _linea("costos", "Cobro OPEX: Representacion", -1_011_610.02),
        _linea("facturas", "CGM", -1_011_610.02),
    ],
)

DIARIO = [
    {"fecha": "2026-07-01", "generacion_kwh": 5629.63, "importacion_kwh": 22.52,
     "venta_kwh": 5629.63, "venta_cop": 4_491_783.26},
    {"fecha": "2026-07-02", "generacion_kwh": 3597.46, "importacion_kwh": 23.62,
     "venta_kwh": 3597.46, "venta_cop": 2_839_856.69},
]


def _celdas(contenido):
    wb = load_workbook(io.BytesIO(contenido), data_only=True)
    return [c.value for fila in wb.active.iter_rows() for c in fila]


def test_la_tabla_diaria_trae_la_importacion():
    """El consumo es una columna del ER, no un dato aparte."""
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "Importación (kWh)" in valores
    assert 22.52 in valores


def test_la_tabla_diaria_trae_una_fila_por_dia():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "2026-07-01" in valores and "2026-07-02" in valores


def test_la_fila_total_suma_las_columnas():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert "TOTAL" in valores
    assert round(5629.63 + 3597.46, 2) in valores       # generación
    assert round(22.52 + 23.62, 2) in valores           # importación


def test_el_encabezado_de_venta_nombra_al_comercializador():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    assert any(isinstance(v, str) and "UNERGY ENERGIA DIGITAL" in v for v in valores)


def test_trae_los_tres_bloques_de_totales():
    valores = _celdas(generar_er_xlsx(PANEL, "San Agustin", diario=DIARIO))
    for titulo in ("Ingresos y costos XM", "Total Comercialización",
                   "Total Ingresos", "Total Costos Operativos fijos"):
        assert titulo in valores, titulo


def test_los_valores_van_calculados_no_como_formula():
    """Si fueran fórmulas haría falta LibreOffice para leerlos, que es justo lo
    que este cambio elimina."""
    assert 118_673_860.5 in _celdas(generar_er_xlsx(PANEL, "X", diario=DIARIO))


def test_el_bloque_del_inversionista_trae_el_valor_a_pagar():
    valores = _celdas(generar_er_xlsx(PANEL, "X", diario=DIARIO))
    assert "Valor a pagar" in valores
    assert "Porcentaje participación" in valores


def test_filtrar_por_inversionista_deja_solo_lo_suyo():
    panel = types.SimpleNamespace(periodo="2026-07", comercializador="X", lineas=[
        _linea("ingresos", "Venta", 100.0, inv="ACME", pct=60.0),
        _linea("ingresos", "Venta", 40.0, inv="OTRA", pct=40.0),
    ])
    valores = _celdas(generar_er_xlsx(panel, "X", diario=[], inversionista="ACME"))
    assert 100.0 in valores and 40.0 not in valores


def test_sin_inversionista_trae_el_proyecto_completo():
    panel = types.SimpleNamespace(periodo="2026-07", comercializador="X", lineas=[
        _linea("ingresos", "Venta", 100.0, inv="ACME", pct=60.0),
        _linea("ingresos", "Venta", 40.0, inv="OTRA", pct=40.0),
    ])
    assert 140.0 in _celdas(generar_er_xlsx(panel, "X", diario=[]))


def test_sin_datos_diarios_no_revienta():
    """Un período sin FTP descargado igual tiene que poder verse."""
    assert _celdas(generar_er_xlsx(PANEL, "X", diario=[]))
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_er_export.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.er_export'`

- [ ] **Step 3: Implementar**

```python
# app/services/er_export.py
"""Genera el Estado de Resultados en Excel desde las líneas del Panel.

Conserva la estructura del ER que usan hoy: la tabla día por día arriba, los tres
bloques de totales debajo, y el bloque por inversionista a la derecha. Lo que
cambia es que los valores van **calculados**: el archivo que genera la API viene
con fórmulas sin evaluar, y por eso hace falta LibreOffice para leerlo.
"""
from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

_MORADO = "2C2039"
_LILA = "F1EAF9"
_MONEDA = '#,##0'
_ENERGIA = '#,##0.00'

# Las columnas de la tabla diaria, con el formato de cada una.
_COLUMNAS_DIARIAS = [
    ("generacion_kwh", _ENERGIA),
    ("importacion_kwh", _ENERGIA),
    ("venta_kwh", _ENERGIA),
    ("venta_cop", _MONEDA),
    ("venta_cop", _MONEDA),      # Ingresos brutos: igual a la venta
]

# Los bloques de totales, en el orden en que se leen.
BLOQUES = [
    ("comercializacion", "Ingresos y costos XM", "Total Comercialización"),
    ("ingresos", "Ingresos y costos", "Total Ingresos"),
    ("costos", "Costos operativos", "Total Costos Operativos fijos"),
]


def _titulo(ws, fila: int, texto: str) -> int:
    celda = ws.cell(fila, 3, texto)
    celda.font = Font(bold=True, color=_MORADO)
    celda.fill = PatternFill("solid", fgColor=_LILA)
    ws.cell(fila, 4).fill = PatternFill("solid", fgColor=_LILA)
    return fila + 1


def _tabla_diaria(ws, diario: list[dict[str, Any]], comercializador: str | None) -> int:
    """Las filas día por día, con su TOTAL. Devuelve la fila siguiente libre."""
    com = comercializador or "Comercializador"
    encabezados = [
        "Fecha", "Generación (kWh)", "Importación (kWh)",
        f"{com} Venta bolsa (kwh)", f"{com} Venta bolsa ($)", "Ingresos brutos",
    ]
    for i, texto in enumerate(encabezados):
        celda = ws.cell(3, 3 + i, texto)
        celda.font = Font(bold=True, size=9, color=_MORADO)
        celda.alignment = Alignment(wrap_text=True, vertical="center")

    fila = 4
    for d in diario:
        ws.cell(fila, 3, d["fecha"])
        for i, (clave, formato) in enumerate(_COLUMNAS_DIARIAS):
            celda = ws.cell(fila, 4 + i, d.get(clave, 0.0))
            celda.number_format = formato
        fila += 1

    ws.cell(fila, 3, "TOTAL").font = Font(bold=True)
    for i, (clave, formato) in enumerate(_COLUMNAS_DIARIAS):
        celda = ws.cell(fila, 4 + i, round(sum(d.get(clave, 0.0) for d in diario), 2))
        celda.font = Font(bold=True)
        celda.number_format = formato
    return fila + 3


def _bloques_totales(ws, lineas, fila: int) -> tuple[int, dict[str, float]]:
    """Los tres bloques de conceptos. Devuelve la fila libre y los subtotales."""
    subtotales: dict[str, float] = {}
    for clave, titulo, etiqueta_total in BLOQUES:
        del_bloque = [l for l in lineas if l.grupo == clave]
        # Las facturas de Unergy se leen dentro de costos operativos, como en el
        # ER de hoy: son cobros del mismo bloque.
        if clave == "costos":
            del_bloque = del_bloque + [l for l in lineas if l.grupo == "facturas"]
        if not del_bloque:
            subtotales[clave] = 0.0
            continue

        fila = _titulo(ws, fila, titulo)
        por_concepto: dict[str, float] = {}
        for l in del_bloque:
            por_concepto[l.concepto] = por_concepto.get(l.concepto, 0.0) + float(l.valor_cop or 0)

        subtotal = 0.0
        for concepto, valor in por_concepto.items():
            ws.cell(fila, 3, concepto)
            celda = ws.cell(fila, 4, round(abs(valor), 2))
            celda.number_format = _MONEDA
            subtotal += abs(valor)
            fila += 1

        ws.cell(fila, 3, etiqueta_total).font = Font(bold=True)
        celda = ws.cell(fila, 4, round(subtotal, 2))
        celda.font = Font(bold=True)
        celda.number_format = _MONEDA
        subtotales[clave] = subtotal
        fila += 2

    ws.cell(fila, 3, "Total de costos operativos + Comercialización").font = Font(bold=True)
    celda = ws.cell(fila, 4, round(subtotales.get("costos", 0.0)
                                   + subtotales.get("comercializacion", 0.0), 2))
    celda.font = Font(bold=True)
    celda.number_format = _MONEDA
    return fila + 2, subtotales


def _bloque_inversionista(ws, lineas, subtotales: dict[str, float],
                          diario: list[dict[str, Any]], fila_inicio: int = 51) -> None:
    """El detalle por partícipe, en las columnas F y G como en el ER de hoy."""
    nombres = {l.inversionista_nombre for l in lineas if l.inversionista_nombre}
    nombre = next(iter(nombres)) if len(nombres) == 1 else "Proyecto (100%)"
    pct = next((float(l.porcentaje or 0) for l in lineas if l.porcentaje), 100.0)

    ingresos = subtotales.get("ingresos", 0.0)
    costos_xm = subtotales.get("comercializacion", 0.0)
    energia = round(sum(d.get("generacion_kwh", 0.0) for d in diario), 2)

    filas: list[tuple[str, float | None]] = [
        (nombre, None),
        ("Porcentaje participación", round(pct / 100, 4)),
        ("Energia", energia),
        ("Ingresos brutos", round(ingresos, 2)),
        ("Costos XM", round(costos_xm, 2)),
        ("Valor a pagar", round(ingresos - costos_xm, 2)),
    ]
    for i, l in enumerate([l for l in lineas if l.grupo == "facturas"], start=1):
        filas.append((f"{i}. {l.concepto}", round(abs(float(l.valor_cop or 0)), 2)))

    fila = fila_inicio
    for etiqueta, valor in filas:
        celda = ws.cell(fila, 6, etiqueta)
        if valor is None:
            celda.font = Font(bold=True, color=_MORADO)
        else:
            v = ws.cell(fila, 7, valor)
            v.number_format = _MONEDA if abs(valor) > 100 else '#,##0.0000'
        fila += 1

    # Tarifa bruta y neta: lo que recibe el inversionista por kWh, antes y después
    # de los cobros. Con energía en cero no se calculan (división por cero).
    if energia:
        ws.cell(fila + 1, 6, "Tarifa bruta").font = Font(bold=True)
        ws.cell(fila + 1, 7, round(ingresos / energia, 4))
        cobros = sum(abs(float(l.valor_cop or 0)) for l in lineas if l.grupo == "facturas")
        ws.cell(fila + 2, 6, "Tarifa neta").font = Font(bold=True)
        ws.cell(fila + 2, 7, round((ingresos - costos_xm - cobros) / energia, 4))


def generar_er_xlsx(panel, nombre_proyecto: str,
                    diario: list[dict[str, Any]] | None = None,
                    inversionista: str | None = None) -> bytes:
    """El `.xlsx` del período. Con `inversionista`, solo la parte de esa persona."""
    lineas = list(panel.lineas)
    if inversionista:
        lineas = [l for l in lineas if l.inversionista_nombre == inversionista]
    diario = diario or []

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    ws["A1"] = nombre_proyecto
    ws["A1"].font = Font(bold=True, size=14, color=_MORADO)
    ws["A2"] = f"Período {panel.periodo}"
    ws["A2"].font = Font(size=10, color="666666")

    fila = _tabla_diaria(ws, diario, getattr(panel, "comercializador", None))
    fila, subtotales = _bloques_totales(ws, lineas, fila)
    _bloque_inversionista(ws, lineas, subtotales, diario)

    ws.column_dimensions["C"].width = 52
    for col in ("D", "E", "F", "G", "H"):
        ws.column_dimensions[col].width = 20

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Correr y verificar que pasan**

Run: `python -m pytest tests/test_er_export.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Exponerlo como endpoint**

En `app/api/v1/panel_contable.py`:

```python
@router.get("/{panel_id}/estado-resultados")
def descargar_estado_resultados(
    panel_id: int,
    inversionista: str | None = Query(None, description="Solo la parte de este inversionista"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """El Estado de Resultados del panel, en Excel.

    La tabla diaria se arma con los dos históricos de la API: los despachos dan
    generación y venta, y el consumo por hora da la importación.
    """
    from fastapi.responses import Response
    from app.services.er_diario import construir_tabla_diaria
    from app.services.er_export import generar_er_xlsx

    panel = db.get(PanelContable, panel_id)
    if panel is None:
        raise HTTPException(404, "Panel no encontrado")
    proyecto = db.get(Proyecto, panel.proyecto_id)
    topico = proyecto.topico_liquidaciones or proyecto.sub_project
    y, m = panel.periodo.split("-")

    diario: list[dict] = []
    if topico:
        try:
            diario = construir_tabla_diaria(
                despachos=liquidaciones_api.listar_liquidaciones_mercado(
                    year=int(y), month=int(m), project=topico),
                consumos=liquidaciones_api.listar_contratos_despachados(
                    year=int(y), month=int(m), project=topico),
            )
        except liquidaciones_api.LiquidacionesAPIError:
            # El ER se puede leer sin la tabla diaria; que falle la API no debe
            # impedir descargarlo.
            diario = []

    contenido = generar_er_xlsx(panel, proyecto.nombre_comercial, diario, inversionista)
    sufijo = f"_{inversionista}" if inversionista else ""
    nombre = f"ER_{proyecto.nombre_comercial}_{panel.periodo}{sufijo}.xlsx"
    return Response(
        contenido,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
```

- [ ] **Step 6: Correr todas las pruebas y commitear**

```bash
python -m pytest -q
git add app/services/er_export.py app/api/v1/panel_contable.py tests/test_er_export.py
git commit -m "ER propio en Excel: estructura del original, con tabla diaria y consumo"
```

---

## Task 11: Frontend

**Files:**
- Modify: `unergy-operaciones-frontend/src/views/Liquidaciones/PanelContableView.vue`

- [ ] **Step 1: Botón "Armar desde la API"**

Junto al de cargar ER, llamando a `POST /panel-contable/cargar-periodo` con el
período en pantalla. Al terminar, mostrar cuántos se armaron y **listar los
omitidos con su motivo**: sin eso parece que el período quedó completo.

- [ ] **Step 2: Vista de contraste**

Un diálogo que llame a `GET /panel-contable/contraste` y muestre una tabla por
proyecto con sus diferencias. Es lo que se mira antes de decidir cambiar de
fuente.

- [ ] **Step 3: Botón de descarga del ER**

En el detalle del panel, con un selector de inversionista que por defecto trae el
proyecto completo.

- [ ] **Step 4: Verificar en el navegador y commitear**

Levantar el preview, revisar consola y red, y confirmar que el botón responde y
lista los omitidos.

---

## Verificación final

Con el período 2026-07 cargado por los dos caminos, `GET /panel-contable/contraste`
solo debería mostrar las diferencias que el spec ya explica:

- Administración ausente en los 9 proyectos GD sin `tarifa_admin`
- FAZNI y cargo por confiabilidad presentes en la API y ausentes en el Excel
- Los 4 proyectos NEU, que ni siquiera se arman desde la API

Cualquier otra diferencia es un fallo de traducción y hay que entenderla antes de
liquidar con esto.
