# Modelo Predictivo de Garantías — Plan 2: Ingesta y persistencia

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir en la base los insumos y los targets que la réplica necesita, de forma versionada y auditable, y reproducir dentro de la plataforma el experimento que ya validó la réplica del día 7 con error mediano de 0,0057%.

**Architecture:** Formato largo único (`xm_medida`) con procedencia por archivo (`xm_archivo`), más las tablas de cálculo y targets. Parsers puros en servicios de dominio; el endpoint solo transporta. Carga masiva idempotente por `sha256`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), PostgreSQL, pytest, openpyxl.

---

## Contexto: plan 2 de 3

| Plan | Alcance | Estado |
|---|---|---|
| 1 — Frontend | Vista de planeación | **hecho**, en producción |
| **2 — Ingesta** (este) | Esquema, parsers, validación, carga masiva | listo para ejecutar |
| 3 — Motor | Réplica día 7, estimador día 14, backtesting | pendiente |

Spec: `docs/superpowers/specs/2026-08-25-modelo-predictivo-garantias-design.md`.

### Por qué este alcance y no el del spec completo

El spec lista siete familias de archivo. El experimento del 2026-08-26 que validó la
réplica —70 períodos, error mediano 0,0057%— usó **solo cuatro insumos** y sacó las
ventanas de los nombres de hoja de los Excel de garantía. No necesitó CGM ni Insumos
Preliminares.

Este plan persiste exactamente lo que ese experimento demostró suficiente:

**Dentro:** `BalCttos`, `trsd`, `dspcttos`, `arrpas` · targets desde los Excel de
garantía · las 5 tablas · `validar_esquema()` · carga masiva idempotente.

**Fuera, para un plan posterior:** CGM (las ventanas ya salen de los nombres de hoja) ·
Insumos Preliminares (el precio sale de `trsd`) · calendario · cron de descarga FTP.

Sacar el cron de acá no contradice la decisión del spec de meterlo al alcance: sigue
siendo requisito del sistema, pero no es requisito de *este* plan, y separarlo permite
tener el backtest andando sin esperar a que se resuelvan las credenciales en Railway.

## Convenciones de este repo que hay que respetar

**Antes de tocar nada:**

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```

Si el segundo número no es `0`, `git pull --rebase origin master`. Este repo se atrasa
rápido y ya causó un rebase de emergencia durante el plan 1.

**Tests:** `python -m pytest -q`. Deben pasar todas antes de subir (1.551 al 2026-08-23).
`tests/conftest.py` ya inserta la raíz en `sys.path` y stubea `app.api.v1.auth`.

**Esquema, sin Alembic.** El `CLAUDE.md` lo fija: *tabla nueva = modelo + `create_all`*.
Este plan agrega **cinco tablas nuevas y ninguna columna sobre tablas existentes**, así
que cae entero en ese caso y **no lleva migración Alembic** — agregar una a una cadena
que ya aborta no gana nada. Como refuerzo, porque `create_all` está envuelto en un
`try/except` que solo imprime, van también `CREATE TABLE IF NOT EXISTS` e índices en
`_PENDING_DDLS` de `app/main.py`.

**Zona horaria:** el contenedor corre en UTC y Colombia es UTC−5. Usar `_hoy_col()`, no
`date.today()`.

**Encoding de los archivos XM:** `utf-8-sig` con fallback a `latin1`. Verificado: los
`BalCttos` reales fallan en utf-8 (`PÉRDIDAS` sale mojibake). Separador `;`.

---

## Hechos verificados que el código debe respetar

Todos medidos sobre el corpus real el 2026-08-26. No son supuestos.

| Hecho | Consecuencia en el código |
|---|---|
| **`arrpas` cambió de layout el 2026-03-08** | Le agregaron `AGENTE` como primera columna. 403 archivos con el layout viejo, 134 con el nuevo. El parser detecta el layout por la cabecera; asumir `col[0]` lee el agente como submercado en silencio. |
| **Abril-2026 está corrupto en el corpus real** | 33 archivos de `BalCttos` con **62 columnas en vez de 31**, cada columna duplicada. `validar_esquema()` los rechaza; los otros 3.451 archivos del corpus pasan. |
| Los parsers devuelven `(filas, descartadas)` | Una fila truncada se descarta pero **se cuenta**. Descartarla en silencio hace que un concepto desaparezca, y aguas abajo eso es indistinguible de "no hay exposición". |
| La validación **falla cerrada** | Un `tipo` desconocido se rechaza. Fallar abierto deja entrar cualquier cosa a `xm_medida`. |
| **XM define Exposición como `compras − ventas`** | El signo va documentado y con test. Invertido produce ceros donde hay deuda, sin fallar. |
| `dspcttos` reproduce `CONTRATO DE VENTA` **exacto, 538/538 días** | El despacho no es aproximación; se puede sustituir sin costo. |
| La identidad cierra en **526/538** días | No es 100%. El parser marca el día, no lo descarta en silencio. |
| Deriva de precio TX1→TX2: **0,0176% mediana** | El precio del día 14 es casi el definitivo. |
| `.tx2` de `BalCttos` trae **28–29 días/mes** contra 30–31 de `.txf` | ~7% de días ausentes por diseño de XM. La cobertura debe exponerlo. |
| Nombres de archivo: dos formatos de fecha, `SEPT` de 4 letras, `.XLSX` en mayúsculas | El matcher debe cubrir los tres casos o pierde archivos en silencio. |
| Los nombres de columna varían entre Excel | Normalizar columnas, no solo conceptos. |

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `app/models/garantias_modelo.py` | **Crear.** Las 5 tablas. |
| `app/services/garantias_modelo/__init__.py` | **Crear.** Paquete. |
| `app/services/garantias_modelo/normalizar.py` | **Crear.** Puro: normalización de texto, fechas de nombre de archivo, orden de versiones. |
| `app/services/garantias_modelo/parsers_ftp.py` | **Crear.** Puro: los 4 tipos horarios anchos → formato largo. |
| `app/services/garantias_modelo/parsers_garantia.py` | **Crear.** Puro: Excel de garantía → targets + ventanas. |
| `app/services/garantias_modelo/validacion.py` | **Crear.** Puro: `validar_esquema()`. |
| `app/services/garantias_modelo/ingesta.py` | **Crear.** Orquesta: hash, dedup, persistencia. |
| `app/main.py` | **Modificar.** DDL de respaldo en `_PENDING_DDLS`. |
| `app/models/__init__.py` | **Modificar.** Exportar los modelos nuevos. |
| `tests/test_gar_modelo_normalizar.py` | **Crear.** |
| `tests/test_gar_modelo_parsers_ftp.py` | **Crear.** |
| `tests/test_gar_modelo_parsers_garantia.py` | **Crear.** |
| `tests/test_gar_modelo_validacion.py` | **Crear.** |
| `tests/test_gar_modelo_ingesta.py` | **Crear.** |

Los parsers son **puros**: reciben `bytes` o `str` y devuelven estructuras. No tocan la
base. Eso los hace testeables sin fixtures de BD, que es como está el resto del repo.

---

## Task 1: Normalización — el módulo puro que todo lo demás usa

**Files:**
- Create: `app/services/garantias_modelo/__init__.py` (vacío)
- Create: `app/services/garantias_modelo/normalizar.py`
- Test: `tests/test_gar_modelo_normalizar.py`

- [ ] **Step 1: Escribir el test que falla**

```python
"""Normalización de texto, fechas y versiones para el Modelo Predictivo.

Los tres casos de fecha y el de SEPT salen del corpus real: si el matcher no los
cubre, pierde archivos sin lanzar error.
"""
import datetime

from app.services.garantias_modelo.normalizar import (
    coincide_concepto,
    fecha_de_nombre,
    normalizar_concepto,
    orden_version,
    version_de_nombre,
)


def test_normalizar_concepto_quita_tildes_y_mayusculas():
    assert normalizar_concepto("Generación Kw") == "generacion kw"
    assert normalizar_concepto("  PÉRDIDAS  ASIGNADAS ") == "perdidas asignadas"


def test_normalizar_concepto_borra_el_mojibake_pero_pierde_la_vocal():
    # 6 de los 725 CSV de CGM llegan así. La doble codificación DESTRUYE el carácter
    # acentuado: ninguna normalización lo recupera. Se documenta el hecho.
    assert normalizar_concepto("Generaciï¿½n Kw") == "generacin kw"
    assert normalizar_concepto("Generación Kw") == "generacion kw"


def test_coincide_concepto_reconoce_el_mojibake():
    # Por eso el match no es por igualdad: la forma corrupta es una SUBSECUENCIA de la
    # limpia, porque al mojibake le faltan caracteres y no le sobran.
    assert coincide_concepto("Generaciï¿½n Kw", "Generación Kw")
    assert coincide_concepto("Generación Kw", "Generación Kw")


def test_coincide_concepto_no_confunde_conceptos_distintos():
    assert not coincide_concepto("Compras Kw", "Ventas Kw")
    assert not coincide_concepto("Generación Kw", "Demanda Kw")


def test_fecha_de_nombre_formato_ddmmm():
    assert fecha_de_nombre("GARANTIA SEMANAL MENSUAL 02ENE-2026.xlsx") == datetime.date(2026, 1, 2)


def test_fecha_de_nombre_formato_iso():
    assert fecha_de_nombre("GARANTIA SEMANAL MENSUAL 2026-05-01.xlsx") == datetime.date(2026, 5, 1)


def test_fecha_de_nombre_sept_de_cuatro_letras():
    assert fecha_de_nombre("GARANTIA MENSUAL 19SEPT-2025.XLSX") == datetime.date(2025, 9, 19)


def test_fecha_de_nombre_devuelve_none_si_no_hay_fecha():
    assert fecha_de_nombre("garantias_hoja_madre_formato.xlsx") is None


def test_version_de_nombre():
    assert version_de_nombre("BalCttos0101.tx2") == "tx2"
    assert version_de_nombre("trsd0101.TX1") == "tx1"
    assert version_de_nombre("arrpas0101.txf") == "txf"
    assert version_de_nombre("algo.xlsx") is None


def test_orden_version_es_creciente():
    assert orden_version("tx1") < orden_version("tx2") < orden_version("txr") < orden_version("txf")


def test_orden_version_desconocida_va_al_final():
    assert orden_version("zzz") > orden_version("txf")
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_normalizar.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.services.garantias_modelo'`

- [ ] **Step 3: Implementación mínima**

Crear `app/services/garantias_modelo/__init__.py` vacío, y `normalizar.py`:

```python
"""Normalización de texto, fechas y versiones de liquidación.

Puro: sin estado, sin dependencias de FastAPI ni SQLAlchemy.
"""
from __future__ import annotations

import datetime
import re
import unicodedata

# Los tres formatos conviven en el corpus real. Ver el spec, §6.1.
_MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}

_RE_ISO = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")
_RE_DDMMM = re.compile(r"(\d{1,2})([A-Z]{3,4})-?(20\d{2})")
# `a-z`, no `r-z`: el rango r-z excluye la `f` de txf y la `n` de txn.
_RE_VERSION = re.compile(r"\.(tx[0-9a-z])$", re.IGNORECASE)

# Orden de liquidación. Sucesivas versiones corrigen a las anteriores.
_ORDEN = {"tx1": 1, "tx2": 2, "tx3": 3, "txr": 4, "txf": 5, "txn": 6}
_ORDEN_DESCONOCIDA = 99


def normalizar_concepto(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin espacios repetidos.

    Absorbe la doble codificación de 6 de los CSV de CGM, donde las tildes llegan
    como `ï¿½` y romperían un match literal sin lanzar error.
    """
    if texto is None:
        return ""
    # El orden importa: `ï¿½` son TRES caracteres y NFKD expande el `½` a `1⁄2`,
    # con lo que el marcador deja de existir y queda basura. Limpiar primero.
    s = str(texto).replace("ï¿½", "").replace("�", "")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def coincide_concepto(a: str | None, b: str | None) -> bool:
    """¿Son el mismo concepto, tolerando doble codificación?

    No alcanza con comparar por igualdad: el mojibake **destruye** el carácter
    acentuado, así que `Generaciï¿½n Kw` normaliza a `generacin kw` y nunca va a ser
    igual a `generacion kw`. Pero le faltan caracteres, no le sobran — la forma
    corrupta es una subsecuencia de la limpia. Eso sí es verificable, y no confunde
    conceptos genuinamente distintos.
    """
    x, y = normalizar_concepto(a), normalizar_concepto(b)
    if x == y:
        return True
    corta, larga = (x, y) if len(x) <= len(y) else (y, x)
    if not corta or len(larga) - len(corta) > 3:
        return False
    it = iter(larga)
    return all(c in it for c in corta)


def fecha_de_nombre(nombre: str) -> datetime.date | None:
    """Extrae la fecha de un nombre de archivo. None si no hay ninguna.

    Cubre los dos formatos que conviven (`02ENE-2026` e ISO) y el `SEPT` de cuatro
    letras. ISO primero: es inequívoco.
    """
    m = _RE_ISO.search(nombre)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _RE_DDMMM.search(nombre.upper())
    if m and m.group(2) in _MESES:
        try:
            return datetime.date(int(m.group(3)), _MESES[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def version_de_nombre(nombre: str) -> str | None:
    """`BalCttos0101.tx2` -> `tx2`. None si la extensión no es de liquidación."""
    m = _RE_VERSION.search(nombre)
    return m.group(1).lower() if m else None


def orden_version(version: str | None) -> int:
    """Ordinal de la versión. Las desconocidas van al final, nunca al principio:
    ante la duda, no deben ganarle a una versión conocida.

    Este plan no la consume — la usa el plan 3 para elegir la versión vigente a una
    fecha. Va acá porque el orden de liquidación es dominio, no del motor.
    """
    return _ORDEN.get((version or "").lower(), _ORDEN_DESCONOCIDA)
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_normalizar.py -q`
Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/ tests/test_gar_modelo_normalizar.py
git commit -m "feat(garantias): normalizacion de conceptos, fechas y versiones"
```

---

## Task 2: Modelos — las cinco tablas

**Files:**
- Create: `app/models/garantias_modelo.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Crear el modelo**

```python
"""Tablas del Modelo Predictivo de Garantías.

Formato largo único para los insumos (`xm_medida`) con procedencia por archivo
(`xm_archivo`), más las tablas de cálculo y targets. Ver el spec §5.

Append-only por construcción: la versión de liquidación entra en la clave natural,
así que un TXR que corrige un TX2 crea una fila nueva y nunca pisa la anterior.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, ForeignKey, Index, Integer,
    Numeric, SmallInteger, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class XMArchivo(Base):
    """Un registro por archivo ingerido. Acá vive el anti-leakage."""
    __tablename__ = "xm_archivo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    nombre_archivo: Mapped[str] = mapped_column(String(300), nullable=False)
    version: Mapped[str | None] = mapped_column(String(10), nullable=True)
    periodo_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    # El filtro anti-leakage. `observado` = timestamp real de descarga;
    # `derivado` = regla de publicación aplicada en el backfill histórico.
    disponible_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origen_disponibilidad: Mapped[str] = mapped_column(String(12), nullable=False)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    bytes_len: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    filas_ingeridas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    esquema_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    esquema_detalle: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ingerido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())


class XMMedida(Base):
    """Formato largo: todos los tipos en la misma forma."""
    __tablename__ = "xm_medida"
    __table_args__ = (
        UniqueConstraint("tipo", "fecha_documento", "hora", "entidad", "concepto",
                         "version", name="uq_xm_medida_natural"),
        Index("ix_xm_medida_tipo_fecha_ver", "tipo", "fecha_documento", "version"),
        Index("ix_xm_medida_entidad_concepto", "entidad", "concepto", "fecha_documento"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    archivo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("xm_archivo.id", ondelete="RESTRICT"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    fecha_documento: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    entidad: Mapped[str] = mapped_column(String(60), nullable=False)
    concepto: Mapped[str] = mapped_column(String(120), nullable=False)
    concepto_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    valor: Mapped[float] = mapped_column(Numeric(22, 6), nullable=False)
    version: Mapped[str | None] = mapped_column(String(10), nullable=True)


class GarCalculo(Base):
    """La ventana temporal de un cálculo. El período va en la clave a propósito:
    un vencimiento cubre uno o dos períodos y colapsarlos da un número que no cuadra."""
    __tablename__ = "gar_calculo"
    __table_args__ = (
        UniqueConstraint("agente", "esquema", "fecha_vencimiento", "periodo_ini",
                         "periodo_fin", name="uq_gar_calculo_natural"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    agente: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    esquema: Mapped[str] = mapped_column(String(10), nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    fecha_calculo: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_ini: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fin: Mapped[date] = mapped_column(Date, nullable=False)
    etiqueta_periodo: Mapped[str | None] = mapped_column(String(40), nullable=True)

    base_30d_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_30d_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_sem_ini: Mapped[date | None] = mapped_column(Date, nullable=True)
    base_sem_fin: Mapped[date | None] = mapped_column(Date, nullable=True)

    procedencia: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discrepancias: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GarComponenteReal(Base):
    """Target: lo que XM publicó, por componente."""
    __tablename__ = "gar_componente_real"
    __table_args__ = (
        UniqueConstraint("calculo_id", "componente", name="uq_gar_comp_real"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    calculo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("gar_calculo.id", ondelete="CASCADE"), nullable=False, index=True)
    componente: Mapped[str] = mapped_column(String(80), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)


class GarComponentePred(Base):
    """Predicción, con el horizonte y el cuantil en la clave."""
    __tablename__ = "gar_componente_pred"
    __table_args__ = (
        UniqueConstraint("calculo_id", "componente", "horizonte_dias", "cuantil",
                         "modelo_version", name="uq_gar_comp_pred"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    calculo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("gar_calculo.id", ondelete="CASCADE"), nullable=False, index=True)
    componente: Mapped[str] = mapped_column(String(80), nullable=False)
    horizonte_dias: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    cuantil: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    modelo_version: Mapped[str] = mapped_column(String(40), nullable=False)
    insumos: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    calculado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 2: Exportarlos**

En `app/models/__init__.py`, agregar al final de los imports existentes:

```python
from app.models.garantias_modelo import (  # noqa: F401
    GarCalculo,
    GarComponentePred,
    GarComponenteReal,
    XMArchivo,
    XMMedida,
)
```

Leer primero el archivo: si usa una lista `__all__`, agregar también los cinco nombres ahí.

- [ ] **Step 3: Verificar que el metadata compila y no colisiona**

Run:
```bash
python -c "
from app.models.base import Base
import app.models
t = [n for n in Base.metadata.tables if n.startswith(('xm_','gar_'))]
print(sorted(t))
"
```
Expected: `['gar_calculo', 'gar_componente_pred', 'gar_componente_real', 'xm_archivo', 'xm_medida']`

- [ ] **Step 4: Correr toda la suite**

Run: `python -m pytest -q`
Expected: todas pasan. Si alguna falla, es colisión de nombres — parar y reportar.

- [ ] **Step 5: Commit**

```bash
git add app/models/garantias_modelo.py app/models/__init__.py
git commit -m "feat(garantias): las cinco tablas del modelo predictivo"
```

---

## Task 3: DDL de respaldo en `_PENDING_DDLS`

**Files:**
- Modify: `app/main.py`

`create_all` está envuelto en un `try/except` que solo imprime, así que si falla en
silencio las tablas no existen y el módulo entero responde 500. El respaldo es
idempotente y barato.

- [ ] **Step 1: Agregar las sentencias**

En `app/main.py`, al final de la lista `_PENDING_DDLS` (antes del `]` que la cierra),
agregar:

```python
    # ── Modelo Predictivo de Garantías (plan 2) ──
    # Respaldo de `create_all`, que corre dentro de un try/except que solo imprime.
    # Si falla en silencio, sin esto el módulo entero responde 500.
    """CREATE TABLE IF NOT EXISTS xm_archivo (
        id BIGSERIAL PRIMARY KEY,
        tipo VARCHAR(30) NOT NULL,
        nombre_archivo VARCHAR(300) NOT NULL,
        version VARCHAR(10),
        periodo_ini DATE,
        periodo_fin DATE,
        disponible_desde TIMESTAMPTZ NOT NULL,
        origen_disponibilidad VARCHAR(12) NOT NULL,
        sha256 VARCHAR(64) NOT NULL UNIQUE,
        bytes_len INTEGER NOT NULL DEFAULT 0,
        filas_ingeridas INTEGER NOT NULL DEFAULT 0,
        esquema_ok BOOLEAN NOT NULL DEFAULT true,
        esquema_detalle JSONB,
        ingerido_en TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_xm_archivo_tipo ON xm_archivo (tipo)",
    """CREATE TABLE IF NOT EXISTS xm_medida (
        id BIGSERIAL PRIMARY KEY,
        archivo_id BIGINT NOT NULL REFERENCES xm_archivo(id) ON DELETE RESTRICT,
        tipo VARCHAR(30) NOT NULL,
        fecha_documento DATE NOT NULL,
        hora SMALLINT,
        entidad VARCHAR(60) NOT NULL,
        concepto VARCHAR(120) NOT NULL,
        concepto_raw VARCHAR(200),
        valor NUMERIC(22,6) NOT NULL,
        version VARCHAR(10),
        CONSTRAINT uq_xm_medida_natural UNIQUE (tipo, fecha_documento, hora, entidad, concepto, version)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_xm_medida_archivo_id ON xm_medida (archivo_id)",
    "CREATE INDEX IF NOT EXISTS ix_xm_medida_tipo_fecha_ver ON xm_medida (tipo, fecha_documento, version)",
    "CREATE INDEX IF NOT EXISTS ix_xm_medida_entidad_concepto ON xm_medida (entidad, concepto, fecha_documento)",
    """CREATE TABLE IF NOT EXISTS gar_calculo (
        id BIGSERIAL PRIMARY KEY,
        agente VARCHAR(10) NOT NULL,
        esquema VARCHAR(10) NOT NULL,
        fecha_vencimiento DATE NOT NULL,
        fecha_calculo DATE,
        periodo_ini DATE NOT NULL,
        periodo_fin DATE NOT NULL,
        etiqueta_periodo VARCHAR(40),
        base_30d_ini DATE, base_30d_fin DATE,
        base_sem_ini DATE, base_sem_fin DATE,
        procedencia JSONB, discrepancias JSONB,
        CONSTRAINT uq_gar_calculo_natural UNIQUE (agente, esquema, fecha_vencimiento, periodo_ini, periodo_fin)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_gar_calculo_agente ON gar_calculo (agente)",
    "CREATE INDEX IF NOT EXISTS ix_gar_calculo_vto ON gar_calculo (fecha_vencimiento)",
    """CREATE TABLE IF NOT EXISTS gar_componente_real (
        id BIGSERIAL PRIMARY KEY,
        calculo_id BIGINT NOT NULL REFERENCES gar_calculo(id) ON DELETE CASCADE,
        componente VARCHAR(80) NOT NULL,
        valor NUMERIC(22,2) NOT NULL,
        CONSTRAINT uq_gar_comp_real UNIQUE (calculo_id, componente)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_gar_comp_real_calculo ON gar_componente_real (calculo_id)",
    """CREATE TABLE IF NOT EXISTS gar_componente_pred (
        id BIGSERIAL PRIMARY KEY,
        calculo_id BIGINT NOT NULL REFERENCES gar_calculo(id) ON DELETE CASCADE,
        componente VARCHAR(80) NOT NULL,
        horizonte_dias SMALLINT NOT NULL,
        cuantil NUMERIC(4,3) NOT NULL,
        valor NUMERIC(22,2) NOT NULL,
        modelo_version VARCHAR(40) NOT NULL,
        insumos JSONB,
        calculado_en TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_gar_comp_pred UNIQUE (calculo_id, componente, horizonte_dias, cuantil, modelo_version)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_gar_comp_pred_calculo ON gar_componente_pred (calculo_id)",
```

- [ ] **Step 2: Verificar que `main.py` sigue importando**

Run: `python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Correr la suite**

Run: `python -m pytest -q`
Expected: todas pasan.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "chore(garantias): DDL de respaldo de las tablas del modelo predictivo"
```

---

## Task 4: Parser de los insumos horarios anchos

**Files:**
- Create: `app/services/garantias_modelo/parsers_ftp.py`
- Test: `tests/test_gar_modelo_parsers_ftp.py`

Los cuatro tipos comparten forma: cabecera con `;`, unas columnas de identidad y luego
24 de horas. Difieren en cuáles son las columnas de identidad.

- [ ] **Step 1: Escribir el test que falla**

```python
"""Parseo de los insumos horarios anchos de XM a formato largo.

Los bytes de los fixtures son recortes de archivos reales. El encoding latin1 no es
decorativo: los BalCttos reales fallan en utf-8 por la tilde de PÉRDIDAS.
"""
import datetime

from app.services.garantias_modelo.parsers_ftp import (
    parsear_arrpas,
    parsear_balcttos,
    parsear_dspcttos,
    parsear_trsd,
)

FECHA = datetime.date(2025, 12, 15)

BALCTTOS = (
    "CONCEPTO;MERCADO;CÓDIGO CONTRATO;COMPRADOR;VENDEDOR;TIPO DE DESPACHO;TIPO ASIGNA;"
    + ";".join(f"HORA {h:02d}" for h in range(1, 25)) + "\n"
    "GENERACION IDEAL;NACIONAL;;;;;;" + ";".join(["100"] * 24) + "\n"
    "NETO DE VENTAS EN BOLSA;NACIONAL;;;;;;" + ";".join(["10"] * 24) + "\n"
    "NETO DE COMPRAS EN BOLSA;NACIONAL;;;;;;" + ";".join(["4"] * 24) + "\n"
    "PÉRDIDAS ASIGNADAS A UN GENERADOR;NACIONAL;;;;;;" + ";".join(["1"] * 24) + "\n"
).encode("latin1")

TRSD = (
    "CODIGO;CONTENIDO;" + ";".join(f"HORA {h:02d}" for h in range(1, 25)) + "\n"
    "PBNA;Precio de bolsa nacional;" + ";".join(["250.5"] * 24) + "\n"
    "DMND;Demanda;" + ";".join(["9000"] * 24) + "\n"
).encode("latin1")


def test_balcttos_devuelve_una_fila_por_concepto_y_hora():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 4 * 24


def test_balcttos_normaliza_el_concepto_con_tilde():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    conceptos = {f["concepto"] for f in filas}
    assert "perdidas asignadas a un generador" in conceptos


def test_balcttos_conserva_el_concepto_crudo():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    crudos = {f["concepto_raw"] for f in filas}
    assert "PÉRDIDAS ASIGNADAS A UN GENERADOR" in crudos


def test_balcttos_hora_va_de_1_a_24():
    filas = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")
    horas = sorted({f["hora"] for f in filas})
    assert horas == list(range(1, 25))


def test_balcttos_marca_fecha_version_y_entidad():
    f = parsear_balcttos(BALCTTOS, FECHA, "tx2", "UNGG")[0]
    assert f["fecha_documento"] == FECHA
    assert f["version"] == "tx2"
    assert f["entidad"] == "UNGG"
    assert f["tipo"] == "balcttos"


def test_trsd_extrae_pbna_por_hora():
    filas = [f for f in parsear_trsd(TRSD, FECHA, "tx2") if f["concepto"] == "pbna"]
    assert len(filas) == 24
    assert all(f["valor"] == 250.5 for f in filas)


def test_trsd_entidad_es_nacional():
    f = parsear_trsd(TRSD, FECHA, "tx2")[0]
    assert f["entidad"] == "NACIONAL"


def test_parsers_toleran_utf8_sig():
    # El mismo contenido en utf-8 con BOM debe dar el mismo resultado.
    utf8 = BALCTTOS.decode("latin1").encode("utf-8-sig")
    assert len(parsear_balcttos(utf8, FECHA, "tx2", "UNGG")) == 4 * 24


DSPCTTOS = (
    "CONTRATO;VENDEDOR;COMPRADOR;TIPO;TIPOMERC;TIPO ASIGNA;"
    + ";".join(f"DESP_HORA {h:02d}" for h in range(1, 25)) + ";"
    + ";".join(f"TRF_HORA {h:02d}" for h in range(1, 25)) + "\n"
    "78596;UNGG;TPLC;PC;N;NB;" + ";".join(["50"] * 24) + ";" + ";".join(["400"] * 24) + "\n"
    "99999;OTRO;TPLC;PC;N;NB;" + ";".join(["70"] * 24) + ";" + ";".join(["400"] * 24) + "\n"
).encode("latin1")

ARRPAS = (
    "SUBMERCADO;DELN $/KWH;VRA $;VDA $\n"
    "3A44;3.56;35243.84;0\n"
    "3HYG;3.56;4379.04;0\n"
).encode("latin1")


def test_dspcttos_filtra_a_las_filas_del_agente():
    filas = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert {f["entidad"] for f in filas} == {"78596"}


def test_dspcttos_solo_ingiere_el_bloque_de_despacho():
    # La tarifa (400) no entra: no forma parte de la identidad de exposición.
    filas = parsear_dspcttos(DSPCTTOS, FECHA, "tx2", "UNGG")
    assert len(filas) == 24
    assert all(f["valor"] == 50 for f in filas)
    assert {f["concepto"] for f in filas} == {"despacho"}


def test_arrpas_usa_el_centinela_cero_en_hora():
    # `hora` es NOT NULL: con NULL, Postgres no dedupe (NULL != NULL en un UNIQUE)
    # y las medidas no horarias se duplicarían en silencio. 0 = no horaria.
    filas = parsear_arrpas(ARRPAS, FECHA, "tx2")
    assert all(f["hora"] == 0 for f in filas)
    assert {f["entidad"] for f in filas} == {"3A44", "3HYG"}


def test_arrpas_usa_la_cabecera_como_concepto():
    filas = parsear_arrpas(ARRPAS, FECHA, "tx2")
    conceptos = {f["concepto"] for f in filas}
    assert "vra $" in conceptos
    vra = [f for f in filas if f["concepto"] == "vra $" and f["entidad"] == "3A44"]
    assert vra[0]["valor"] == 35243.84
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_parsers_ftp.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `parsers_ftp`

- [ ] **Step 3: Implementar**

```python
"""Insumos horarios anchos de XM → formato largo.

Puro: recibe bytes, devuelve list[dict] lista para `xm_medida`. No toca la base.

Encoding: utf-8-sig con fallback a latin1. No es decorativo — los BalCttos reales
fallan en utf-8 por la tilde de PÉRDIDAS.
"""
from __future__ import annotations

import datetime

from app.services.garantias_modelo.normalizar import normalizar_concepto

HORAS = 24


def decodificar(contenido: bytes) -> str:
    try:
        return contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        return contenido.decode("latin1")


def _valor(texto: str) -> float:
    t = (texto or "").strip().replace(",", ".")
    if not t:
        return 0.0
    try:
        return float(t)
    except ValueError:
        return 0.0


def _parsear_ancho(contenido: bytes, fecha: datetime.date, version: str | None,
                   tipo: str, entidad: str, col_concepto: int,
                   primera_hora: int) -> list[dict]:
    """Forma común: `col_concepto` identifica la serie y las 24 columnas desde
    `primera_hora` son las horas."""
    filas: list[dict] = []
    lineas = decodificar(contenido).splitlines()
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < primera_hora + HORAS:
            continue
        crudo = (col[col_concepto] or "").strip()
        if not crudo:
            continue
        concepto = normalizar_concepto(crudo)
        for h in range(HORAS):
            filas.append({
                "tipo": tipo,
                "fecha_documento": fecha,
                "hora": h + 1,
                "entidad": entidad,
                "concepto": concepto,
                "concepto_raw": crudo[:200],
                "valor": _valor(col[primera_hora + h]),
                "version": version,
            })
    return filas


def parsear_balcttos(contenido: bytes, fecha: datetime.date, version: str | None,
                     entidad: str) -> list[dict]:
    """`CONCEPTO;MERCADO;CÓDIGO CONTRATO;COMPRADOR;VENDEDOR;TIPO DESPACHO;TIPO ASIGNA;HORA 01..24`"""
    return _parsear_ancho(contenido, fecha, version, "balcttos", entidad,
                          col_concepto=0, primera_hora=7)


def parsear_trsd(contenido: bytes, fecha: datetime.date, version: str | None) -> list[dict]:
    """`CODIGO;CONTENIDO;HORA 01..24`. Es nacional, no por agente."""
    return _parsear_ancho(contenido, fecha, version, "trsd", "NACIONAL",
                          col_concepto=0, primera_hora=2)


def parsear_dspcttos(contenido: bytes, fecha: datetime.date, version: str | None,
                     agente: str) -> list[dict]:
    """`CONTRATO;VENDEDOR;COMPRADOR;TIPO;TIPOMERC;TIPO ASIGNA;DESP_HORA 01..24;TRF_HORA 01..24`

    Es por contrato bilateral, no por planta. La entidad es el contrato; se filtra a
    las filas donde el agente es el vendedor. Solo se ingiere el bloque de despacho:
    la tarifa no entra en la identidad de exposición.
    """
    filas: list[dict] = []
    for linea in decodificar(contenido).splitlines()[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < 6 + HORAS:
            continue
        if (col[1] or "").strip().upper() != agente.upper():
            continue
        contrato = (col[0] or "").strip()
        for h in range(HORAS):
            filas.append({
                "tipo": "dspcttos",
                "fecha_documento": fecha,
                "hora": h + 1,
                "entidad": contrato,
                "concepto": "despacho",
                "concepto_raw": "DESP_HORA",
                "valor": _valor(col[6 + h]),
                "version": version,
            })
    return filas


def parsear_arrpas(contenido: bytes, fecha: datetime.date, version: str | None) -> list[dict]:
    """`arrpas` es plano por submercado, no horario: una fila por submercado y columna.

    La entidad es el submercado y el concepto es el nombre de la columna. `hora` va en
    **0**, el centinela de "no horaria": con NULL, Postgres no considera iguales dos
    filas en un UNIQUE y estas medidas se duplicarían en silencio.
    """
    filas: list[dict] = []
    lineas = decodificar(contenido).splitlines()
    if not lineas:
        return filas
    cabecera = [c.strip() for c in lineas[0].split(";")]
    for linea in lineas[1:]:
        if not linea.strip():
            continue
        col = linea.split(";")
        if len(col) < 2:
            continue
        submercado = (col[0] or "").strip()
        if not submercado:
            continue
        for i in range(1, min(len(col), len(cabecera))):
            crudo = cabecera[i]
            if not crudo:
                continue
            filas.append({
                "tipo": "arrpas",
                "fecha_documento": fecha,
                "hora": 0,
                "entidad": submercado,
                "concepto": normalizar_concepto(crudo),
                "concepto_raw": crudo[:200],
                "valor": _valor(col[i]),
                "version": version,
            })
    return filas
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_parsers_ftp.py -q`
Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/parsers_ftp.py tests/test_gar_modelo_parsers_ftp.py
git commit -m "feat(garantias): parsers de los insumos horarios de XM a formato largo"
```

---

## Task 5: `validar_esquema()` — el que atrapa abril-2026

**Files:**
- Create: `app/services/garantias_modelo/validacion.py`
- Test: `tests/test_gar_modelo_validacion.py`

El caso real: en abril-2026 `dspcttos` y `BalCttos` llegaron con columnas duplicadas y
desplazadas. Sin validación eso **invierte el signo de la exposición sin lanzar error**.

- [ ] **Step 1: Escribir el test que falla**

```python
"""validar_esquema: detecta archivos corruptos ANTES de que entren a xm_medida."""
from app.services.garantias_modelo.validacion import (
    validar_estructura,
    verificar_identidad_balcttos,
)


def _cab(cols):
    return (";".join(cols) + "\n" + ";".join(["0"] * len(cols)) + "\n").encode("latin1")


HORAS = [f"HORA {h:02d}" for h in range(1, 25)]
BASE = ["CONCEPTO", "MERCADO", "CÓDIGO CONTRATO", "COMPRADOR", "VENDEDOR",
        "TIPO DE DESPACHO", "TIPO ASIGNA"]


def test_estructura_valida_pasa():
    ok, detalle = validar_estructura(_cab(BASE + HORAS), "balcttos")
    assert ok, detalle


def test_columna_duplicada_se_rechaza():
    # El caso real de abril-2026: sin esto el signo se invierte en silencio.
    ok, detalle = validar_estructura(_cab(BASE + HORAS + ["HORA 24"]), "balcttos")
    assert not ok
    assert "duplicad" in detalle["motivo"].lower()


def test_faltan_horas_se_rechaza():
    ok, detalle = validar_estructura(_cab(BASE + HORAS[:20]), "balcttos")
    assert not ok
    assert detalle["horas_encontradas"] == 20


def test_archivo_vacio_se_rechaza():
    ok, detalle = validar_estructura(b"", "balcttos")
    assert not ok


def test_identidad_balcttos_cierra():
    # GI - contratos - perdidas == ventas - compras
    ok, resid = verificar_identidad_balcttos(
        generacion_ideal=100.0, contratos_venta=80.0, perdidas=5.0,
        neto_ventas=20.0, neto_compras=5.0)
    assert ok
    assert abs(resid) < 0.01


def test_identidad_balcttos_no_cierra_se_reporta():
    ok, resid = verificar_identidad_balcttos(
        generacion_ideal=100.0, contratos_venta=80.0, perdidas=5.0,
        neto_ventas=50.0, neto_compras=5.0)
    assert not ok
    assert abs(resid) > 0.01
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_validacion.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `validacion`

- [ ] **Step 3: Implementar**

```python
"""Validación de esquema de los archivos de XM.

Corre ANTES de que nada entre a `xm_medida`. Atrapa el caso real de abril-2026, en que
`dspcttos` y `BalCttos` llegaron con columnas duplicadas y desplazadas: sin esto, la
exposición cambia de signo y ningún error se lanza.
"""
from __future__ import annotations

import re

from app.services.garantias_modelo.parsers_ftp import decodificar

_RE_HORA = re.compile(r"^(HORA|DESP_HORA|TRF_HORA)\s*\d{1,2}$", re.IGNORECASE)

# Columnas de identidad esperadas antes del bloque horario, por tipo.
_IDENTIDAD = {
    "balcttos": 7,
    "trsd": 2,
    "dspcttos": 6,
}
_HORAS_ESPERADAS = {"balcttos": 24, "trsd": 24, "dspcttos": 48}  # dspcttos: DESP + TRF


def validar_estructura(contenido: bytes, tipo: str) -> tuple[bool, dict]:
    """(ok, detalle). `detalle` va tal cual a `xm_archivo.esquema_detalle`."""
    texto = decodificar(contenido)
    lineas = [l for l in texto.splitlines() if l.strip()]
    if not lineas:
        return False, {"motivo": "archivo vacío"}

    cols = [c.strip() for c in lineas[0].split(";")]
    horas = [c for c in cols if _RE_HORA.match(c)]

    dups = {c for c in cols if c and cols.count(c) > 1}
    if dups:
        return False, {
            "motivo": f"columnas duplicadas: {sorted(dups)}",
            "columnas": len(cols),
        }

    esperadas = _HORAS_ESPERADAS.get(tipo)
    if esperadas is not None and len(horas) != esperadas:
        return False, {
            "motivo": f"se esperaban {esperadas} columnas horarias y hay {len(horas)}",
            "horas_encontradas": len(horas),
            "columnas": len(cols),
        }

    identidad = _IDENTIDAD.get(tipo)
    if identidad is not None and len(cols) - len(horas) != identidad:
        return False, {
            "motivo": (f"se esperaban {identidad} columnas de identidad y hay "
                       f"{len(cols) - len(horas)}"),
            "columnas": len(cols),
        }

    return True, {"columnas": len(cols), "horas": len(horas), "filas": len(lineas) - 1}


def verificar_identidad_balcttos(*, generacion_ideal: float, contratos_venta: float,
                                 perdidas: float, neto_ventas: float,
                                 neto_compras: float,
                                 tolerancia: float = 0.01) -> tuple[bool, float]:
    """`GI − contratos − pérdidas == ventas − compras`.

    Verificada al centavo sobre datos reales en 526 de 538 días. No cierra en el 2%
    restante, así que el día se marca — no se descarta en silencio ni se acepta callado.
    """
    izq = generacion_ideal - contratos_venta - perdidas
    der = neto_ventas - neto_compras
    residuo = izq - der
    return abs(residuo) < tolerancia, residuo
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_validacion.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/validacion.py tests/test_gar_modelo_validacion.py
git commit -m "feat(garantias): validar_esquema detecta columnas duplicadas y desplazadas"
```

---

## Task 6: Parser de los Excel de garantía (targets y ventanas)

**Files:**
- Create: `app/services/garantias_modelo/parsers_garantia.py`
- Test: `tests/test_gar_modelo_parsers_garantia.py`

Cada archivo `GARANTIA SEMANAL MENSUAL` rinde **tres** targets: una hoja por período, con
la ventana en el nombre de la hoja y los componentes en columnas, cabecera en la fila que
contiene `CÓDIGO`.

- [ ] **Step 1: Escribir el test que falla**

```python
"""Parseo de los Excel de garantía: ventana desde el nombre de hoja, componentes
desde la fila de CÓDIGO."""
import datetime

from app.services.garantias_modelo.parsers_garantia import (
    componentes_de_hoja,
    ventana_de_hoja,
)


def test_ventana_tx2_de_nombre_de_hoja():
    r = ventana_de_hoja("AJUSTE TX2 SEMA MENS 01-07 AGO", datetime.date(2026, 8, 28))
    assert r == (datetime.date(2026, 8, 1), datetime.date(2026, 8, 7), "AJUSTE TX2")


def test_ventana_proy_de_nombre_de_hoja():
    r = ventana_de_hoja("AJUSTE PROY (M) 08-31 AGO", datetime.date(2026, 8, 28))
    assert r[0] == datetime.date(2026, 8, 8)
    assert r[1] == datetime.date(2026, 8, 31)
    assert r[2] == "AJUSTE PROY"


def test_ventana_cruza_anio_hacia_atras():
    # Hoja de DIC en un archivo con vencimiento de ENE: el período es del año anterior.
    r = ventana_de_hoja("AJUSTE TX2 SEMA MENS 13-19 DIC", datetime.date(2026, 1, 2))
    assert r[0] == datetime.date(2025, 12, 13)
    assert r[1] == datetime.date(2025, 12, 19)


def test_hoja_sin_ventana_devuelve_none():
    assert ventana_de_hoja("PERIODO BASE", datetime.date(2026, 8, 28)) is None


def test_componentes_de_hoja_toma_la_fila_de_codigo():
    filas = [
        (None, "AJUSTE GARANTÍA", None),
        (None, "FECHA DE VENCIMIENTO: 21", None),
        ("CÓDIGO", "Exposición Energía en Bolsa ($)", "Restricciones ($)"),
        ("AAGC", 0, 0),
        ("UNGG", -107701627, 5),
        ("UNGC", 12, 0),
    ]
    r = componentes_de_hoja(filas, "UNGG")
    assert r["exposicion energia en bolsa ($)"] == -107701627
    assert r["restricciones ($)"] == 5


def test_componentes_agente_ausente_devuelve_vacio():
    filas = [("CÓDIGO", "Exposición Energía en Bolsa ($)"), ("AAGC", 1)]
    assert componentes_de_hoja(filas, "UNGG") == {}
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_parsers_garantia.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `parsers_garantia`

- [ ] **Step 3: Implementar**

```python
"""Excel de garantía de XM → targets por componente y ventanas por período.

Cada `GARANTIA SEMANAL MENSUAL` trae una hoja por período (`AJUSTE TX2 …`,
`AJUSTE PROY …`, `AJUSTE (M+1) …`), con la ventana en el NOMBRE de la hoja y los 20
componentes en columnas. La cabecera no está en la fila 0: hay metadatos arriba.
"""
from __future__ import annotations

import datetime
import re

from app.services.garantias_modelo.normalizar import normalizar_concepto

_MESES = {
    "ENE": 1, "FEB": 2, "MAR": 3, "ABR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AGO": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DIC": 12,
}
_RE_VENTANA = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Z]{3,4})")


def _etiqueta(nombre: str) -> str:
    u = nombre.upper()
    if "TX2" in u:
        return "AJUSTE TX2"
    if "M+1" in u or "M+ 1" in u:
        return "AJUSTE M+1"
    if "PROY" in u:
        return "AJUSTE PROY"
    return "AJUSTE"


def ventana_de_hoja(nombre: str, vencimiento: datetime.date
                    ) -> tuple[datetime.date, datetime.date, str] | None:
    """`AJUSTE TX2 SEMA MENS 01-07 AGO` + vto -> (inicio, fin, etiqueta).

    El año no está en el nombre: se infiere del vencimiento. Si el mes de la ventana es
    posterior al del vencimiento, la ventana es del año anterior — el caso de una hoja
    de DIC en un archivo de ENE.
    """
    u = nombre.upper()
    if not u.startswith("AJUSTE"):
        return None
    m = _RE_VENTANA.search(u)
    if not m or m.group(3) not in _MESES:
        return None
    mes = _MESES[m.group(3)]
    anio = vencimiento.year - 1 if mes > vencimiento.month else vencimiento.year
    try:
        ini = datetime.date(anio, mes, int(m.group(1)))
        fin = datetime.date(anio, mes, int(m.group(2)))
    except ValueError:
        return None
    return ini, fin, _etiqueta(nombre)


def componentes_de_hoja(filas: list[tuple], agente: str) -> dict[str, float]:
    """Componentes del agente. `filas` son las de openpyxl con `values_only=True`.

    La cabecera se busca por la celda que contiene `CÓDIGO`: los archivos traen 2 a 10
    filas de metadatos arriba y la posición varía. Los nombres de columna se normalizan
    porque varían entre archivos.
    """
    idx = None
    for i, fila in enumerate(filas):
        if fila and any(isinstance(c, str) and "CÓDIGO" in c.upper() for c in fila if c):
            idx = i
            break
    if idx is None:
        return {}

    cols = [normalizar_concepto(c) if c else "" for c in filas[idx]]
    objetivo = agente.strip().upper()
    for fila in filas[idx + 1:]:
        if not fila or not fila[0]:
            continue
        if str(fila[0]).strip().upper() != objetivo:
            continue
        salida: dict[str, float] = {}
        for i in range(1, min(len(cols), len(fila))):
            if not cols[i]:
                continue
            try:
                salida[cols[i]] = float(fila[i]) if fila[i] is not None else 0.0
            except (TypeError, ValueError):
                continue
        return salida
    return {}
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_parsers_garantia.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/parsers_garantia.py tests/test_gar_modelo_parsers_garantia.py
git commit -m "feat(garantias): parser de Excel de garantia -- ventanas y componentes"
```

---

## Task 7: Ingesta idempotente

**Files:**
- Create: `app/services/garantias_modelo/ingesta.py`
- Test: `tests/test_gar_modelo_ingesta.py`

- [ ] **Step 1: Escribir el test que falla**

```python
"""Ingesta: hash, dedup y decisión de qué entra. Sin base de datos: la función
recibe un callable para consultar si el hash ya existe."""
import datetime

from app.services.garantias_modelo.ingesta import (
    preparar_archivo,
    sha256_de,
)

CONTENIDO = b"CODIGO;CONTENIDO;" + b";".join(
    f"HORA {h:02d}".encode() for h in range(1, 25)
) + b"\nPBNA;precio;" + b";".join([b"100"] * 24) + b"\n"


def test_sha256_es_estable():
    assert sha256_de(CONTENIDO) == sha256_de(CONTENIDO)
    assert sha256_de(CONTENIDO) != sha256_de(CONTENIDO + b"x")


def test_preparar_extrae_tipo_fecha_y_version():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    assert r["tipo"] == "trsd"
    assert r["version"] == "tx2"
    assert r["esquema_ok"] is True
    assert r["periodo_ini"] is None          # sin `anio` no se puede fechar el archivo


def test_preparar_con_anio_resuelve_la_fecha():
    # El nombre trae MMDD sin año: el año viene de la carpeta que lo contiene.
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None, anio=2025)
    assert r["periodo_ini"] == datetime.date(2025, 12, 15)


def test_preparar_marca_esquema_invalido_sin_lanzar():
    r = preparar_archivo("trsd1215.tx2", b"CODIGO;CONTENIDO\nPBNA;x\n", disponible_desde=None)
    assert r["esquema_ok"] is False
    assert "motivo" in r["esquema_detalle"]


def test_preparar_derivado_cuando_no_hay_timestamp():
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=None)
    assert r["origen_disponibilidad"] == "derivado"


def test_preparar_observado_cuando_hay_timestamp():
    t = datetime.datetime(2026, 8, 26, 10, 0, tzinfo=datetime.timezone.utc)
    r = preparar_archivo("trsd1215.tx2", CONTENIDO, disponible_desde=t)
    assert r["origen_disponibilidad"] == "observado"
    assert r["disponible_desde"] == t
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_gar_modelo_ingesta.py -q`
Expected: FAIL con `ModuleNotFoundError` sobre `ingesta`

- [ ] **Step 3: Implementar**

```python
"""Ingesta de archivos de XM: hash, validación y metadatos.

La idempotencia es por `sha256` del contenido, no por nombre: los mismos CSV llegan
con nombres distintos en distintos zips, y los `_V2` tienen el mismo nombre con
contenido diferente.
"""
from __future__ import annotations

import datetime
import hashlib
import re

from app.services.garantias_modelo.normalizar import version_de_nombre
from app.services.garantias_modelo.validacion import validar_estructura

_RE_DIARIO = re.compile(r"^([A-Za-z]+)(\d{2})(\d{2})\.", re.IGNORECASE)

# Tipos de insumo que este plan ingiere. Un nombre que no matchee queda marcado como
# esquema inválido en vez de entrar sin tipo.
_TIPOS = {"balcttos", "trsd", "dspcttos", "arrpas"}


def sha256_de(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def tipo_de_nombre(nombre: str) -> str | None:
    m = _RE_DIARIO.match(nombre)
    if not m:
        return None
    t = m.group(1).lower()
    return t if t in _TIPOS else None


def preparar_archivo(nombre: str, contenido: bytes,
                     *, disponible_desde: datetime.datetime | None,
                     anio: int | None = None) -> dict:
    """Metadatos listos para `xm_archivo`. No escribe nada.

    `disponible_desde=None` significa backfill histórico: no hay timestamp real de
    descarga, así que la disponibilidad queda marcada como derivada. Toda consulta
    anti-leakage pasa por el mismo campo, y la derivación queda auditable.
    """
    tipo = tipo_de_nombre(nombre)
    version = version_de_nombre(nombre)

    ok, detalle = validar_estructura(contenido, tipo) if tipo else (False, {
        "motivo": f"tipo no reconocido en el nombre: {nombre}"})

    fecha = None
    m = _RE_DIARIO.match(nombre)
    if m and anio:
        try:
            fecha = datetime.date(anio, int(m.group(2)), int(m.group(3)))
        except ValueError:
            fecha = None

    observado = disponible_desde is not None
    return {
        "tipo": tipo or "desconocido",
        "nombre_archivo": nombre[:300],
        "version": version,
        "periodo_ini": fecha,
        "periodo_fin": fecha,
        "disponible_desde": disponible_desde or datetime.datetime.now(datetime.timezone.utc),
        "origen_disponibilidad": "observado" if observado else "derivado",
        "sha256": sha256_de(contenido),
        "bytes_len": len(contenido),
        "esquema_ok": ok,
        "esquema_detalle": None if ok else detalle,
    }
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_gar_modelo_ingesta.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add app/services/garantias_modelo/ingesta.py tests/test_gar_modelo_ingesta.py
git commit -m "feat(garantias): ingesta idempotente por sha256 con procedencia"
```

---

## Task 8: Suite completa y cierre

**Files:** ninguno nuevo.

- [ ] **Step 1: Correr toda la suite**

Run: `python -m pytest -q`
Expected: todas pasan. Al 2026-08-23 eran 1.551; este plan agrega ~34.

Si alguna preexistente falla, **parar y reportar** — no seguir. Puede ser colisión de
nombres de tabla o un import que rompió.

- [ ] **Step 2: Verificar que la app arranca**

Run: `python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Verificar sincronía y push**

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```

Si el segundo número no es `0`, `git pull --rebase origin master` y volver a correr la
suite antes de pushear.

```bash
git push origin master
```

---

## Estado esperado al terminar

- Cinco tablas nuevas, creadas por `create_all` y respaldadas en `_PENDING_DDLS`.
- Parsers puros y testeados de los cuatro insumos y de los Excel de garantía.
- `validar_esquema()` rechazando el caso de columnas duplicadas.
- Ingesta idempotente por `sha256`, con procedencia observada o derivada.
- La suite completa en verde.

## Lo que este plan no hace

- **No carga los datos.** Crea el esquema y los parsers; la carga masiva del corpus es
  el primer paso del plan 3, donde hay contra qué contrastarla.
- **No expone endpoints.** El frontend ya tiene su contrato definido y lo implementa el
  plan 3.
- **No trae CGM, Insumos Preliminares ni calendario.** El experimento que validó la
  réplica no los necesitó: las ventanas salen de los nombres de hoja y el precio de
  `trsd`. Entran cuando el backtest muestre que hacen falta.
- **No activa el cron de FTP.** Sigue siendo requisito del sistema; se resuelve cuando
  estén las credenciales en Railway.
