# Garantías · Plan 2 — Parser del costo regulatorio (Cruce facturas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parsear la hoja "Facturas XM" del archivo `Cruce facturas M YYYY txf.xlsx` y calcular el costo regulatorio del mes según la regla de negocio confirmada.

**Architecture:** Módulo nuevo y aislado `app/services/costo_regulatorio.py`. Dos capas: extracción de la hoja (openpyxl) y cálculo **puro** sobre estructuras simples. **NO** define tablas, endpoints ni ingesta todavía (eso va en un plan posterior); es solo la librería de parseo. No toca nada existente.

**Tech Stack:** Python, openpyxl (ya disponible), pytest.

**Regla de negocio (confirmada con el usuario):** El costo regulatorio del mes = suma de los conceptos de las facturas de tipo **GENERADOR**, **excluyendo** el concepto "Energía en bolsa" (eso es "compras", no regulatorio) y **excluyendo** por completo las facturas de tipo **COMERCIALIZADOR**. No sumar líneas de subtotal ("Valor total", "Total servicios de administración sic"). El IVA de las facturas generador **sí** entra. Valor de referencia julio 2026 = **67.191.598**.

**Estructura de la hoja "Facturas XM"** (verificada): columnas A=`campo`, B=`cantidad`, C=`last_value`, D=`current_value`, E=`total`. Filas: encabezado `Factura ASICxxxxx - TIPO` (con E vacío), luego fila header `campo`, luego filas de concepto (concepto en A, monto en E), y filas de subtotal `Valor total` / `Total servicios de administracion sic`. El tipo (`GENERADOR`/`COMERCIALIZADOR`) está en el texto del encabezado tras el guion.

---

## File Structure

- **Create** `app/services/costo_regulatorio.py` — normalizador, extractor de la hoja, cálculo puro.
- **Create** `tests/test_costo_regulatorio.py` — tests puros con fixtures + extractor con workbook en memoria + test de integración contra el archivo real (se salta si no está).

Sin cambios en `app/main.py`, routers, modelos ni tablas.

---

### Task 1: Cálculo puro del costo regulatorio

**Files:**
- Create: `app/services/costo_regulatorio.py`
- Test: `tests/test_costo_regulatorio.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_costo_regulatorio.py
"""Costo regulatorio del mes desde la hoja 'Facturas XM' del Cruce de facturas.
Cálculo puro: sin BD, sin red, sin reloj."""
from app.services.costo_regulatorio import (
    _norm,
    costo_regulatorio_de_facturas,
)


def _factura(asic, tipo, lineas):
    return {"asic": asic, "tipo": tipo, "lineas": lineas}


def test_norm_quita_acentos_y_normaliza():
    assert _norm("  Energía en Bolsa ") == "energia en bolsa"
    assert _norm("COMERCIALIZADOR") == "comercializador"


def test_excluye_comercializador_completo():
    facturas = [
        _factura("ASIC1", "COMERCIALIZADOR", [("Servicios de administracion sic", 800000.0),
                                              ("Valor total", 800000.0)]),
        _factura("ASIC2", "GENERADOR", [("Fazni", 999626.0), ("Valor total", 999626.0)]),
    ]
    assert costo_regulatorio_de_facturas(facturas) == 999626.0


def test_excluye_energia_en_bolsa_y_subtotales():
    facturas = [_factura("ASIC3", "GENERADOR", [
        ("Arranque y parada", 9658866.0),
        ("Cargo por confiabilidad", 19933106.0),
        ("Energia en bolsa", 110102600.0),   # excluido: es "compras"
        ("Valor total", 139694572.0),         # subtotal: no sumar
    ])]
    assert costo_regulatorio_de_facturas(facturas) == 29591972.0


def test_iva_generador_si_entra_y_total_servicios_no():
    facturas = [_factura("ASIC4", "GENERADOR", [
        ("+ i.v.a. (19%)", 1742857.0),
        ("Servicios de administracion sic", 9172932.0),
        ("Servicios despacho y coordinacion cnd", 25684211.0),
        ("Total servicios de administracion sic", 10915789.0),  # subtotal: no sumar
        ("Valor total", 36600000.0),                            # subtotal: no sumar
    ])]
    assert costo_regulatorio_de_facturas(facturas) == 36600000.0


def test_total_julio_2026_reproduce_valor_referencia():
    facturas = [
        _factura("ASIC125059", "COMERCIALIZADOR", [
            ("+ i.v.a. (19%)", 151994.0), ("Servicios de administracion sic", 799970.0),
            ("Servicios despacho y coordinacion cnd", 426693.0),
            ("Total servicios de administracion sic", 951964.0), ("Valor total", 1378657.0)]),
        _factura("ASIC125064", "GENERADOR", [("Fazni", 999626.0), ("Valor total", 999626.0)]),
        _factura("ASIC125263", "GENERADOR", [
            ("Arranque y parada", 9658866.0), ("Cargo por confiabilidad", 19933106.0),
            ("Energia en bolsa", 110102600.0), ("Valor total", 139694572.0)]),
        _factura("ASIC125542", "GENERADOR", [
            ("+ i.v.a. (19%)", 1742857.0), ("Servicios de administracion sic", 9172932.0),
            ("Servicios despacho y coordinacion cnd", 25684211.0),
            ("Total servicios de administracion sic", 10915789.0), ("Valor total", 36600000.0)]),
    ]
    assert costo_regulatorio_de_facturas(facturas) == 67191598.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_costo_regulatorio.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.costo_regulatorio'`

- [ ] **Step 3: Implementación mínima**

```python
# app/services/costo_regulatorio.py
"""Costo regulatorio del mes desde la hoja 'Facturas XM' del `Cruce facturas M YYYY txf.xlsx`.

AISLADO: no toca modelos, tablas ni endpoints. Dos capas: `extraer_facturas_xm` lee la
hoja (openpyxl); `costo_regulatorio_de_facturas` calcula sobre estructuras simples.

Regla (confirmada): sumar los conceptos de las facturas GENERADOR, excluyendo "Energía en
bolsa" (eso es compras) y excluyendo las facturas COMERCIALIZADOR. No sumar subtotales
('Valor total', 'Total servicios ...'). El IVA de generador sí entra.
"""
from __future__ import annotations

import unicodedata

# Concepto que es "compras", no regulatorio.
_CONCEPTO_COMPRAS = "energia en bolsa"
# Tipo de factura que se excluye por completo.
_TIPO_EXCLUIDO = "comercializador"


def _norm(texto) -> str:
    """minúsculas, sin acentos, sin espacios extremos."""
    s = unicodedata.normalize("NFKD", str(texto or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


def _es_subtotal(concepto_norm: str) -> bool:
    """Las filas 'Valor total' y 'Total servicios ...' son subtotales, no conceptos."""
    return concepto_norm.startswith("valor total") or concepto_norm.startswith("total ")


def costo_regulatorio_de_facturas(facturas: list[dict]) -> float:
    """facturas = [{'asic','tipo','lineas':[(concepto, monto), ...]}] -> total regulatorio."""
    total = 0.0
    for f in facturas:
        if _norm(f.get("tipo")) == _TIPO_EXCLUIDO:
            continue
        for concepto, monto in f.get("lineas", []):
            cn = _norm(concepto)
            if _es_subtotal(cn) or cn == _CONCEPTO_COMPRAS:
                continue
            try:
                total += float(monto)
            except (TypeError, ValueError):
                continue
    return total
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_costo_regulatorio.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/costo_regulatorio.py tests/test_costo_regulatorio.py
git commit -m "feat(garantias): calculo puro del costo regulatorio (regla facturas GENERADOR)"
```

---

### Task 2: Extractor de la hoja "Facturas XM" (openpyxl)

**Files:**
- Modify: `app/services/costo_regulatorio.py`
- Test: `tests/test_costo_regulatorio.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# añadir en tests/test_costo_regulatorio.py
import openpyxl
from app.services.costo_regulatorio import extraer_facturas_xm


def _hoja_demo():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturas XM"
    filas = [
        ["Factura ASIC1 - COMERCIALIZADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Servicios de administracion sic", 1, 0, 0, 800000.0],
        ["Valor total", 1, 0, 0, 800000.0],
        [None, None, None, None, None],
        ["Factura ASIC2 - GENERADOR", None, None, None, None],
        ["campo", "cantidad", "last_value", "current_value", "total"],
        ["Fazni", 1, 0, 0, 999626.0],
        ["Valor total", 1, 0, 0, 999626.0],
    ]
    for r in filas:
        ws.append(r)
    return ws


def test_extraer_facturas_separa_encabezado_tipo_y_lineas():
    facturas = extraer_facturas_xm(_hoja_demo())
    assert [f["asic"] for f in facturas] == ["ASIC1", "ASIC2"]
    assert [f["tipo"] for f in facturas] == ["COMERCIALIZADOR", "GENERADOR"]
    assert ("Fazni", 999626.0) in facturas[1]["lineas"]
    # la fila 'campo' (header) NO es una línea de concepto
    assert all(l[0] != "campo" for f in facturas for l in f["lineas"])


def test_extraer_y_calcular_da_solo_generador():
    from app.services.costo_regulatorio import costo_regulatorio_de_facturas
    assert costo_regulatorio_de_facturas(extraer_facturas_xm(_hoja_demo())) == 999626.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_costo_regulatorio.py::test_extraer_facturas_separa_encabezado_tipo_y_lineas -q`
Expected: FAIL — `ImportError: cannot import name 'extraer_facturas_xm'`

- [ ] **Step 3: Implementación mínima**

```python
# añadir en app/services/costo_regulatorio.py
NOMBRE_HOJA = "Facturas XM"


def extraer_facturas_xm(ws) -> list[dict]:
    """Lee una worksheet 'Facturas XM' -> [{'asic','tipo','lineas':[(concepto, monto)]}].

    Detecta cada factura por el encabezado 'Factura ASICxxxx - TIPO' (col A). Las filas
    siguientes con concepto en A y monto numérico en E (columna 'total') son líneas;
    ignora la fila header 'campo'.
    """
    facturas: list[dict] = []
    actual: dict | None = None
    for fila in ws.iter_rows(min_row=1, values_only=True):
        a = fila[0] if len(fila) > 0 else None
        total = fila[4] if len(fila) > 4 else None
        if a is None:
            continue
        texto = str(a).strip()
        if texto.lower().startswith("factura "):
            # 'Factura ASIC125059 - COMERCIALIZADOR'
            resto = texto[len("factura "):].strip()
            asic, _, tipo = resto.partition("-")
            actual = {"asic": asic.strip(), "tipo": tipo.strip(), "lineas": []}
            facturas.append(actual)
            continue
        if actual is None or texto.lower() == "campo":
            continue
        if isinstance(total, (int, float)):
            actual["lineas"].append((texto, float(total)))
    return facturas


def costo_regulatorio_de_archivo(path: str) -> float:
    """Abre el xlsx y devuelve el costo regulatorio de su hoja 'Facturas XM'."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[NOMBRE_HOJA] if NOMBRE_HOJA in wb.sheetnames else wb[wb.sheetnames[0]]
    return costo_regulatorio_de_facturas(extraer_facturas_xm(ws))
```

- [ ] **Step 4: Correr y ver que pasa**

Run: `python -m pytest tests/test_costo_regulatorio.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/costo_regulatorio.py tests/test_costo_regulatorio.py
git commit -m "feat(garantias): extractor de la hoja Facturas XM (openpyxl)"
```

---

### Task 3: Test de integración contra el archivo real (julio 2026)

**Files:**
- Test: `tests/test_costo_regulatorio.py`

- [ ] **Step 1: Escribir el test (se salta si el archivo no está, p. ej. en CI)**

```python
# añadir en tests/test_costo_regulatorio.py
import os
import pytest
from app.services.costo_regulatorio import costo_regulatorio_de_archivo

_ARCHIVO_JULIO = r"C:\Users\jessi\OneDrive\Documentos\Estado Resultados\2026\07_Julio\Cruce facturas 7 2026 txf.xlsx"


@pytest.mark.skipif(not os.path.exists(_ARCHIVO_JULIO),
                    reason="archivo Cruce facturas de julio no disponible (CI)")
def test_archivo_real_julio_reproduce_67_191_598():
    assert costo_regulatorio_de_archivo(_ARCHIVO_JULIO) == 67191598.0
```

- [ ] **Step 2: Correr**

Run: `python -m pytest tests/test_costo_regulatorio.py -q`
Expected (con el archivo presente): PASS (8 passed). Si el archivo no está: 7 passed, 1 skipped.

Si el test de integración FALLA (da un número distinto a 67191598), NO ajustar el número esperado: es señal de que el extractor no está leyendo la hoja como se espera. Reportar como BLOCKED con el número obtenido para revisar.

- [ ] **Step 3: Commit**

```bash
git add tests/test_costo_regulatorio.py
git commit -m "test(garantias): integracion del costo regulatorio contra archivo real julio 2026"
```

---

## Self-Review

- **Cobertura del spec:** regla GENERADOR sin "Energía en bolsa" ✓, exclusión COMERCIALIZADOR ✓, no sumar subtotales ✓, IVA generador incluido ✓, valor de referencia julio 67.191.598 verificado en test puro y en test de integración ✓. Aislado (nadie lo importa; sin tablas/endpoints) ✓.
- **Placeholders:** ninguno.
- **Consistencia de tipos:** `_norm(x)->str`, `extraer_facturas_xm(ws)->list[dict]` con forma `{'asic','tipo','lineas':[(str,float)]}`, `costo_regulatorio_de_facturas(list)->float`, `costo_regulatorio_de_archivo(str)->float`. Estable entre tareas.

## Fuera de alcance de este plan (decisión + planes siguientes)
- **DECISIÓN PENDIENTE (usuario):** cómo llega el archivo al backend — ¿un endpoint de subida (multipart) o el backend lo lee del Drive de Estados de Resultados? De eso depende el plan de ingesta.
- Tabla `costo_regulatorio_mensual` + persistencia + fallback "último mes disponible" (plan de ingesta/persistencia).
- Motor de garantía, `garantia_snapshot`, endpoint (Plan 3).
- Sub-pestaña Proyecciones (Plan 4).
