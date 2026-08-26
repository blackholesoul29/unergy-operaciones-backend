# Modelo Predictivo de Garantías XM — Diseño

**Fecha:** 2026-08-25
**Ubicación:** Comercialización → Garantías → *Modelo Predictivo* (tercera tab)
**Estado:** diseño aprobado, pendiente plan de implementación

---

## 1. Objetivo

XM publica el monto de la garantía **7 días antes** del vencimiento. El negocio
necesita saberlo **14 días antes** — el día en que cierra la ventana base de datos, y
una semana antes de que XM calcule.

Esto no es un problema de pronóstico. El día 14 todos los días de la ventana base ya
ocurrieron: las plantas generaron, el precio de bolsa se formó, los contratos se
despacharon. Lo único pendiente es que XM **liquide** esos días en versión TX2.

> El sistema estima qué dirá la liquidación TX2 sobre días ya transcurridos.
> No predice el futuro.

Evidencia de que es tratable: comparando TX2 contra TXF sobre 510 días, **86%
resultan idénticos**.

### Timeline verificado (vencimiento 28-AGO-2026)

| Hito | Fecha | Días antes del vencimiento |
|---|---|---|
| Ventana TX2 (semana S−1) | 08 → 14 AGO | cierra en 14 |
| Ventana proyecciones (30 días) | 16 JUL → 14 AGO | cierra en 14 |
| Fecha de cálculo de XM | 21 AGO | 7 |
| Vencimiento del pago | 28 AGO | 0 |

Regla general: ambas ventanas base cierran 14 días antes del vencimiento; XM calcula 7
días antes; el vencimiento es viernes.

Esta regla aplica a la garantía **semanal**. La mensual tiene su propio objetivo.

### Anticipación mensual: 30 días antes del mes garantizado

Verificado sobre **8 meses** (nov-2025 → sep-2026): la ventana base del cálculo mensual
cierra antes de la fecha objetivo en **8/8 casos**, con margen mediano de **3 días**
(rango 0 a 10).

Ejemplo (mes garantizado SEP-2026):

| Hito | Fecha |
|---|---|
| Cierra la ventana base | 29 JUL |
| **Objetivo de conocimiento** | **2 AGO** |
| XM publica | 6 AGO |

Se le gana a XM por **4 días**.

> **Requisito operativo.** Un margen mediano de 3 días — y de **0 en el peor caso** — no
> tolera retrasos. La ingesta de generación debe correr **diariamente**, no semanal: un
> atraso de 2 días elimina el margen por completo.
>
> Esto ya está cubierto por infraestructura existente. `app/main.py` corre APScheduler
> en producción con `gen_sync_am` / `gen_sync_pm` (7:00 y 19:00, ventana móvil de 7 días
> hacia `generacion_diaria`) y `reporte_energia_clasificar` (3:30 diario, hacia
> `reporte_energia_generacion`). La ventana móvil de 7 días absorbe además atrasos
> puntuales. No hay que construir el cron: hay que **monitorear** que no se caiga, y
> alertar si el dato más reciente tiene más de 1 día.

### La fecha de cálculo es determinística

No se estima: viene del calendario oficial de XM, publicado con **años** de
anticipación. Lo único incierto es la ventana base, no el momento del cálculo. Eso
mueve el calendario de "una fuente más" a **la fuente autoritativa de `fecha_calculo`**
(ver §5.3).

### Sistema de dos velocidades

| Esquema | Estimación temprana | Número firme | Se le gana a XM por |
|---|---|---|---|
| **Semanal** | 14 días antes del vencimiento | 7 días antes | 7 días |
| **Mensual** | ~30 días antes del mes garantizado | cuando XM publica | ~4 días (ej. SEP-2026) |

En ambos carriles la salida temprana es un **rango** (valor central + cuantil superior)
producido por reconstrucción con insumos propios más el residual calibrado; la firme es
la réplica determinística con el TX2 ya publicado.

La estimación temprana se reemplaza por la firme cuando XM publica. El valor del sistema
es la anticipación que gana entre ambos momentos.

---

## 2. Contexto de negocio

UNERGY está registrada ante XM como **dos agentes independientes**, y XM calcula
garantías por separado para cada uno. Ambos entran en este diseño:

- **UNGG** — actividad generador.
- **UNGC** — actividad comercializador. Suele no aparecer en las hojas DEPÓSITO porque
  su ajuste da cero, pero tiene actividad real: en el TXR de julio 2026 su exposición
  en bolsa fue de −249.346.890 COP, más del doble que UNGG. Está bajo el piso hoy, pero
  puede cruzarlo si cambian las condiciones de mercado.

Representamos ~54 fronteras de generación solar distribuida. Siendo generadores solares
somos **vendedores netos**, así que la exposición en bolsa es fuertemente negativa y la
suma de componentes suele quedar bajo cero. Operamos justo en la frontera del piso.

### La fórmula

```
Valor Garantía       = max(0, Σ 20 componentes)
Valor Garantía Final = max(0, Valor Garantía − Garantías TIES)
Total Ajuste a pagar = Valor Garantía Final − Estimado
```

Verificada empíricamente sobre `GARANTIA_TXR_11AGO-2026-V2.xlsx`, hoja `PERIODOS A
GARANTIZAR`, 368 agentes: 366/367 en las dos primeras identidades y 368/368 exacto en
la tercera. La única excepción es el agente CHVC.

### Por qué el esfuerzo va a un solo componente

Desglose real de UNGG (TXR julio 2026):

| Componente | COP |
|---|---|
| Exposición Energía en Bolsa | **−107.701.627** |
| Cargo por Confiabilidad | +19.171.860 |
| Valores Adicionales Merc. Nal. e Internal. | +9.127.453 |
| Ajustes SIC | +9.382.905 |
| Servicios CND-SIC-FAZNI | +37.561.953 |
| **Σ** | **−32.457.456** → piso → **0** |

Los cuatro componentes administrativos suman +75,2M y son comparativamente estables.
Exposición en Bolsa es el término volátil y el que decide si la suma cruza cero. La
pregunta de negocio es unidimensional: **¿alcanza la exposición negativa a tapar los
~+75M administrativos?**

Por eso este spec modela Exposición en serio y trata los otros 19 componentes como un
agregado por persistencia. La varianza está en un solo lugar.

---

## 3. Alcance

### Dentro

- Ingesta y persistencia versionada de los insumos necesarios para Exposición en Bolsa,
  más los targets por componente.
- Construcción de la ventana temporal real de cada cálculo, con procedencia.
- Réplica determinística de Exposición en Bolsa (día 7).
- Estimador con intervalo de Exposición en Bolsa (día 14).
- Agregado por persistencia de los otros 19 componentes.
- Piso en cero aplicado sobre los cuantiles.
- Backtesting con cobertura y ancho de intervalo, sobre el rango cubierto por los
  targets (ver §6.1).
- **Vista de planeación** (§10): cuánto se necesita para las próximas semanas y para el
  mes, con los dos totales — suma de P90 semanales y P90 del horizonte completo — y la
  brecha entre ellos.
- Agregación del horizonte por **remuestreo de bloques históricos consecutivos**, para
  no asumir independencia entre semanas.
- **UNGG y UNGC**, ambos. Es el mismo camino de código con otra entidad.
- **Semanal y mensual**, cada uno con su propio objetivo de anticipación (§1).
- Alerta de frescura sobre la ingesta diaria de generación: si el dato más reciente
  tiene más de 1 día, el margen de la anticipación mensual está en riesgo y hay que
  avisarlo antes de que el número salga mal.
- **Cron de descarga FTP**, con credenciales en variables de entorno de Railway. Estaba
  fuera de alcance y se corrigió: de los cuatro insumos del día 14, tres exigen hoy
  acción manual (despachos, `trsd`, `arrpas`), y eso es incompatible con un margen de 0
  días. El objetivo es que **nadie tenga que subir nada**. El downloader ya existe y
  funciona; lo que falta es persistir las credenciales, que hoy se teclean en cada uso.

### Fuera

| Qué | Por qué |
|---|---|
| Garantía TIE | Proyecta hacia adelante mientras la nacional ajusta hacia atrás. Se reparte por participación en compras en bolsa y usa TRM del día. Lógica aparte, spec aparte. |
| Los otros 19 componentes en detalle | Entran como agregado por persistencia. Se refinan cuando el backtest muestre que su error es material. |
| Cualquier modelo de ML | Fase 3 del brief, contingente a que la vía determinística + residual deje error material. |
| Saldo de cuenta custodia / "efectivo a conseguir" | Retirado del alcance por la adenda corregida del 2026-08-25. |
| Pronóstico de precio de mercado | El sistema predice qué cobrará XM, no qué hará el mercado. XM proyecta con los 3 últimos meses facturados; acertarle al precio real nos alejaría de su número (§8.2.1). |

---

## 4. Decisiones de arquitectura

### 4.1 Vive dentro de Plataforma Operaciones

No se crea un repo nuevo. La plataforma ya tiene lo que un proyecto nuevo tendría que
reconstruir desde cero:

- `app/services/xm/` — cliente FTP, downloader con reintentos y caché local, y
  `TIPOS_CONFIG` que ya cubre los 7 tipos necesarios (`dspcttos`, `BalCttos`, `grip`,
  `arrpas`, `tgrl`, `trsd`, `cxcsb`), con rutas pública y privada y
  `AGENTES_VALIDOS = {UNGG, UNGC}`.
- Garantías ya tiene las tabs *Ajustes XM* (parser de los Excel de garantía, que son el
  ground truth del backtesting) y *Proyecciones*.
- `reporte_energia_generacion` ya guarda generación real por frontera y fecha con curva
  horaria, validada contra el ASIC.
- Auth, roles, Alembic y el deploy en Railway.

Un repo separado dejaría el ground truth en otra base de datos y obligaría a
sincronizarlo o volver a parsearlo.

**Backend:** `app/services/garantias_modelo/` para el dominio,
`app/api/v1/garantias_modelo.py` solo para transporte. Nada de lógica en las views.
**Frontend:** tercera tab en `src/views/Garantias/GarantiasView.vue`, roles `admin` y
`liquidaciones`, `DataTable` de PrimeVue como el resto del módulo.

### 4.2 DDL por doble vía

El estado de Alembic en este repo obliga a ello, y conviene dejarlo escrito:

- El grafo de Alembic está **sano**: un solo head (`098`), cadena lineal.
- `app/main.py` ejecuta `Base.metadata.create_all(bind=engine)` en el arranque, que
  materializa las tablas nuevas desde los modelos. Cuando después corre la migración que
  hace `CREATE TABLE` sobre esa misma tabla, falla. Alembic es secuencial: la primera
  que falla aborta la cadena y **ninguna posterior corre**.
- `start.sh` envuelve `alembic upgrade head` en un `if !`, así que el server arranca
  igual. Deploy verde, `/health` ok, y la pantalla entera en 500.
- Por eso `_PENDING_DDLS` creció a 1.493 líneas y es hoy la fuente de verdad real de
  producción.

**Regla para este módulo — sin Alembic.** El `CLAUDE.md` del repo la fija: *tabla nueva
= modelo + `create_all`*. Este módulo agrega **cinco tablas nuevas y ninguna columna
sobre tablas existentes**, así que cae entero en ese caso.

Y es lo correcto, no solo lo convencional: escribir una migración Alembic para estas
tablas agregaría **otra** migración a una cadena que ya aborta, sin ganar nada — las
tablas las crea `create_all` igual. Se verificó que no hay colisión de nombres: ningún
modelo existente usa los prefijos `xm_` ni `gar_`.

Dos refuerzos, porque `create_all` está envuelto en un `try/except` que solo imprime:

- `CREATE TABLE IF NOT EXISTS` de las cinco tablas en `_PENDING_DDLS`, como respaldo si
  `create_all` falla en silencio.
- Los índices compuestos de §5.2 explícitos en `_PENDING_DDLS` con `IF NOT EXISTS`.
  `create_all` crea los del modelo, pero conviene no depender de eso para los que
  sostienen el rendimiento de las consultas del backtest.

Se extiende `tests/test_modelo_vs_ddl.py` a las cinco tablas nuevas.

Si más adelante el módulo necesita **agregar una columna a una tabla existente**, ahí sí
aplica la otra regla del repo: `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. Nota práctica:
el `CLAUDE.md` la ubica en `add_columns()` de `init_db.py` (39 sentencias, corre primero
en `start.sh`), pero el trabajo reciente va a `_PENDING_DDLS` de `app/main.py` (272
sentencias, corre en `_deferred_init`). Las dos funcionan; usar la segunda, que es donde
está el resto.

Arreglar Alembic de verdad — auditar qué se aplicó contra el esquema vivo, stampear,
sacar `create_all`, quitar el `if !` — es un proyecto aparte y no entra acá.

### 4.3 Formato largo único para los insumos crudos

XM cambia formatos: pasó con `arrpas` en marzo 2026. Una tabla ancha tipada por tipo de
archivo obligaría a una migración Alembic por cada cambio, que en este repo es riesgo
real. En formato largo, un concepto nuevo entra como filas nuevas.

Dimensionamiento filtrando a entidades propias (UNGG/UNGC + ~54 plantas): ≈3M filas por
año. No es restricción para el Postgres de Railway.

---

## 5. Modelo de datos

Cinco tablas nuevas. Ninguna colisiona con lo existente (`garantias_ajustes`,
`garantia_snapshot`, `garantia_pagado`, `balcttos_neto`).

### 5.1 `xm_archivo` — un registro por archivo ingerido

Es donde vive el anti-leakage.

| Campo | Tipo | Nota |
|---|---|---|
| `id` | bigserial | |
| `tipo` | varchar | `balcttos`, `trsd`, `tgrl`, `grip`, `dspcttos`, `arrpas`, `cxcsb`, `gargm_con`, `gargm_car`, `gargm_ene`, `insumos_prelim`, `calendario`, `garantia_excel` |
| `nombre_archivo` | varchar | tal como llegó |
| `version` | varchar null | `tx1 tx2 tx3 txr txf txn`, con ordinal explícito en código |
| `periodo_ini`, `periodo_fin` | date | a qué días aplica el contenido |
| `disponible_desde` | timestamptz **NOT NULL** | el filtro de leakage |
| `origen_disponibilidad` | varchar | `observado` \| `derivado` |
| `sha256` | char(64) **UNIQUE** | idempotencia real, no por nombre |
| `bytes_len`, `filas_ingeridas` | int | |
| `esquema_ok` | bool | resultado de `validar_esquema()` |
| `esquema_detalle` | jsonb | qué falló, cuándo falló |
| `ingerido_en` | timestamptz | |

`disponible_desde` es `observado` cuando es el timestamp real de descarga, y `derivado`
cuando sale de la regla de publicación de XM aplicada en el backfill histórico. Toda
consulta pasa por un solo camino — `disponible_desde <= fecha_calculo` — y la derivación
queda marcada y auditable.

### 5.2 `xm_medida` — formato largo, todos los tipos en la misma forma

| Campo | Tipo | Nota |
|---|---|---|
| `id` | bigserial | |
| `archivo_id` | bigint FK | → `xm_archivo` |
| `tipo` | varchar | denormalizado para índice |
| `fecha_documento` | date | |
| `hora` | smallint null | null en los no horarios |
| `entidad` | varchar | agente, planta, submercado o contrato según el tipo |
| `concepto` | varchar | **normalizado sin tildes** |
| `concepto_raw` | varchar | el literal original |
| `valor` | numeric | |
| `version` | varchar null | denormalizada para índice |

```sql
UNIQUE (tipo, fecha_documento, hora, entidad, concepto, version)
INDEX  (tipo, fecha_documento, version)
INDEX  (entidad, concepto, fecha_documento)
```

**Append-only por construcción.** Un TXR que corrige un TX2 entra como fila nueva con
otra `version`; nunca pisa. Se puede reconstruir qué se sabía en cualquier momento.

`concepto` normalizado sin tildes desactiva de entrada la trampa de los 6 CSV de CGM con
doble codificación (`Generaciï¿½n Kw`), que rompen el match por nombre y fallan en
silencio.

### 5.3 `gar_calculo` — la ventana temporal

| Campo | Tipo | Nota |
|---|---|---|
| `id` | bigserial | |
| `agente` | varchar | `UNGG` \| `UNGC` |
| `esquema` | varchar | `semanal` \| `mensual` |
| `fecha_vencimiento` | date | |
| `fecha_calculo` | date | 7 días antes del vencimiento |
| `periodo_ini`, `periodo_fin` | date | el período garantizado |
| `base_30d_ini`, `base_30d_fin` | date | ventana de proyecciones |
| `base_sem_ini`, `base_sem_fin` | date | ventana TX2 de la semana |
| `procedencia` | jsonb | qué fuente dio cada fecha |
| `discrepancias` | jsonb | cuando dos fuentes disponibles se contradicen |

```sql
UNIQUE (agente, esquema, fecha_vencimiento, periodo_ini, periodo_fin)
```

**El período va en la clave a propósito.** El corpus tiene **162 vencimientos**
(nov-2023 → ago-2026) y la mayoría cubre dos períodos, no uno. Ejemplo real de julio 2026:

| Vencimiento | Período garantizado | Duración | Corresponde a |
|---|---|---|---|
| 2026-07-03 | 2026-06-20 → 06-30 | 11 d | cierre mes anterior |
| 2026-07-03 | 2026-07-01 → 07-31 | 31 d | proyección mes actual |
| 2026-07-24 | 2026-07-11 → 07-31 | 21 d | resto del mes |
| 2026-07-24 | 2026-08-01 → 08-31 | 31 d | proyección M+1 |

Eso explica la estructura del desglose semanal: `AJUSTE`, `AJUSTE PROY` y `AJUSTE M+1`
son períodos distintos del mismo vencimiento. Colapsarlos en una fila produce un número
que no cuadra con nada.

#### Precedencia de fuentes para la ventana

Orden fijo, y cada fecha guarda de cuál de las cuatro salió:

1. Hoja `PERIODO BASE` del Excel de garantía — la ventana **real** que usó XM.
2. Nombre del archivo CGM:
   `{PREFIJO}Vto{YYYY-MM-DD}_Gar{YYYY-MM-DD}_{YYYY-MM-DD}.csv`
3. Calendario oficial
   `CalendarioPublicacionProyeccionesDeGarantiasMensuales-{AÑO}.xlsx`
4. Derivada de la regla general (ventanas cierran en 14, cálculo en 7).

Si dos fuentes disponibles se contradicen, se registra en `discrepancias` y **no** se
frena la carga.

**Excepción: `fecha_calculo` no entra en esta precedencia.** Sale siempre del calendario
oficial, que XM publica con años de anticipación. No se infiere ni se deriva de las
otras fuentes. Si el `PERIODO BASE` de un Excel la contradice, gana el calendario y la
diferencia se registra en `discrepancias` para revisarla.

#### Ventanas candidatas: cuando la ventana base no es derivable

Medido sobre el histórico, la ventana base del cálculo mensual **cierra entre 5 y 16
días antes de la fecha de cálculo, sin patrón derivable**. No hay una regla que la
prediga.

La respuesta no es adivinar una: es **calcular sobre todas las ventanas candidatas** y
dejar que la dispersión entre ellas se convierta en ancho del intervalo. Si las 12
ventanas posibles dan casi el mismo número, el intervalo es angosto y la incertidumbre
de ventana era irrelevante. Si dan números muy distintos, el intervalo se ensancha — que
es la respuesta honesta.

En `gar_calculo`, `base_30d_ini` / `base_30d_fin` guardan la ventana **observada** cuando
existe. Cuando no, se guarda el rango candidato y `procedencia` lo marca como
`candidatas`, con el conjunto evaluado en el mismo jsonb. Un cálculo con ventana
observada y uno con ventana candidata **nunca se promedian en la misma métrica**: la tab
los separa siempre.

Esto importa porque aplicando una ventana uniforme de 30 días a todos los vencimientos,
solo **13 de 127** quedaron dentro de ±3%. Sin separar "ventana observada" de "ventana
derivada", el backtest no puede distinguir el error del modelo del error de la ventana.

### 5.4 `gar_componente_real` — el target

| Campo | Nota |
|---|---|
| `calculo_id` | FK → `gar_calculo` |
| `componente` | uno de los 20, o `agregado_administrativos` |
| `valor` | numeric |

`UNIQUE (calculo_id, componente)`.

**Los targets salen de tres formatos, no de uno.** Verificado sobre los archivos reales:

| Archivo | Dónde está el desglose | Rinde |
|---|---|---|
| `GARANTIA TXR *.xlsx` | hoja `PERIODOS A GARANTIZAR` | 1 target por archivo |
| `GARANTIA SEMANAL MENSUAL *.xlsx` | **una hoja por período** (`AJUSTE TX2 SEMA MENS 01-07 AGO`, `AJUSTE PROY (M) 08-31 AGO`, `AJUSTE (M+1) 01-30 SEPT`) | **3 targets por archivo** |
| `GARANTIA MENSUAL *.xlsx` | hoja del período (`01-30 SEP`) + `PERIODO BASE` | 1 target por archivo |

En los tres casos la cabecera está en la fila que contiene `CÓDIGO` (fila 3 en las hojas
`AJUSTE …`), con una fila por agente del mercado y una columna por componente.

**El nombre de la hoja lleva la ventana.** `AJUSTE TX2 SEMA MENS 01-07 AGO` dice
literalmente que ese bloque corresponde al 01–07 de agosto. Es la fuente de ventana más
directa que existe y entra en la precedencia de §5.3 junto al `PERIODO BASE`.

#### Fuente derivada: el consolidado interno

`Automatizado_2026_Valor_Garantias_Semanales.xlsx` tiene **22 hojas de vencimiento**
(2025-12-26 → 2026-06-26), cada una con ambos agentes, el desglose por período con la
ventana en la etiqueta (`AJUSTE PROY 13 AL 31 DIC`), TIE, TOTAL A PAGAR y custodia.

Es **de segunda mano**: lo arma el equipo, no XM. Se ingiere con
`origen_disponibilidad = derivado` y se usa para (a) cubrir vencimientos sin el Excel
original y (b) contrastar contra los de XM donde haya ambos. Nunca reemplaza al archivo
de XM cuando existe.

Trampas verificadas en ese archivo, todas silenciosas:

- Hojas que **no** son vencimientos: `Inicio`, `Prueba` y `13MARMIO` — esta última es un
  duplicado manual de `13MAR`. Filtrar por el patrón `\d{2}[A-Z]{3}` no alcanza para
  `13MARMIO`; hay que exigir coincidencia exacta.
- **Faltan 5 viernes** dentro del rango: 16, 23 y 30 de enero, 6 de febrero y 29 de mayo
  de 2026. Ausencia, no ceros: no se pueden contar como vencimientos sin garantía.
- Un mismo tipo de ajuste puede aparecer **dos veces** en una hoja cuando el período
  cruza fin de mes (`AJUSTE 1 25 AL 30 ABR` y `AJUSTE 1 01 AL 01 MAY` en la hoja
  `15MAY`). El parser no puede asumir uno por tipo.
- **El año no está en ninguna parte del contenido.** Verificado celda por celda sobre las
  22 hojas: ni como texto ni como fecha. `26DIC` es solo eso. El único lugar donde
  aparece el año es el **nombre del archivo** (`Automatizado_2026_...`). El parser debe
  tomarlo de ahí y registrarlo explícitamente; si algún día existe un `Automatizado_2025`
  con el mismo formato, sus hojas serán indistinguibles de las de 2026. Además hay que
  manejar el cruce de año: en `Automatizado_2026`, la hoja `26DIC` es de **2025**.

### 5.5 `gar_componente_pred` — la predicción

| Campo | Nota |
|---|---|
| `calculo_id` | FK → `gar_calculo` |
| `componente` | |
| `horizonte_dias` | smallint: días de anticipación respecto a la publicación de XM |
| `cuantil` | `0.5` \| `0.9` (configurable) |
| `valor` | numeric |
| `modelo_version` | qué versión del código lo produjo |
| `insumos` | jsonb: qué archivo y qué versión alimentó cada término |
| `calculado_en` | timestamptz |

```sql
UNIQUE (calculo_id, componente, horizonte_dias, cuantil, modelo_version)
```

`horizonte_dias` es un entero, no un enum: el objetivo de anticipación difiere por
esquema y no conviene cablearlo en el tipo.

| Esquema | Estimación temprana | Número firme |
|---|---|---|
| Semanal | 14 días antes del vencimiento | 7 días antes (XM publica) |
| Mensual | ~30 días antes del mes garantizado | cuando XM publica |

Guardarlo explícitamente permite medir lo que la adenda quiere saber: **cuánto se gana
adelantándose**, por esquema y por vencimiento. `insumos` es lo que permite auditar por
qué cambió un número entre corridas.

---

## 6. Ingesta y validación

### 6.1 Origen de los archivos

#### Inventario real disponible (verificado 2026-08-25)

Deduplicado por contenido entre los tres zips del workspace: **1.263 archivos únicos**.

| Familia | Únicos | Rango |
|---|---|---|
| CGM | 785 | **162 vencimientos**, nov-2023 → ago-2026 |
| Insumos Preliminares UNGG | 203 | jun-2023 → ago-2026 |
| Insumos Preliminares UNGC | 256 | mar-2022 → ago-2026 |
| `DemandaXAgenteSTR` | 19 | — |

Insumos del FTP, en `XM_*.zip`, cobertura **2025-01 → 2026-07**:

| Tipo | `.tx2` | Otras | Nota |
|---|---|---|---|
| `BalCttos` | **538** | 577 `.txf` | |
| `trsd` | **539** | 577 `.txf`, **516 `.tx1`** | el `.tx1` habilita una estimación aún más temprana |
| `dspcttos` | **538** | 577 `.txf` | |
| `arrpas` | **537** | 577 `.txf` | |

**536 días con los CUATRO insumos en `.tx2` simultáneamente**, del 2025-01-01 al
2026-07-29. Solo 3 días quedan fuera por desalineación entre series (2025-06-23,
2026-05-24, 2026-06-08). Esa intersección es el rango efectivamente calculable sin
leakage, y cubre los cuatro términos de la identidad — ya no hay ninguno que dependa de
datos que no existían en la fecha de cálculo.

**El CGM no es por agente.** Se verificó: los 725 CSV comunes a los dos zips son
byte a byte **idénticos**. El nombre del archivo codifica el período y el vencimiento,
**no** el agente — este viene en la columna `Entidad` del contenido. Tratar el nombre
como clave completa mezclaría UNGG con UNGC sin que nada falle.

**Colisión de nomenclatura.** El repo ya usa "CGM" para otra cosa
(`scripts/seed_contratos_cgm.py`, `Data/contratosCGM.json`, en el contexto de
Representación). Por eso los tipos de este módulo se llaman `gargm_*` y no `cgm_*`.

#### Cómo llega cada familia

| Familia | Cómo llega |
|---|---|
| 7 tipos FTP | `app/services/xm/` ya los descarga. Falta persistir credenciales. |
| CGM e Insumos Preliminares | Carga masiva desde carpeta local, deduplicando por `sha256` |
| Calendario | Carga manual, un archivo por año |
| Excel de garantía (targets) | Carga manual |

**Credenciales FTP:** hoy `app/core/config.py` no declara variables de FTP;
`ejecutar_job` recibe `ftp_params` como dict que viene en el request — alguien las
teclea en la UI cada vez. Para cualquier automatización hay que moverlas a variables de
entorno en Railway. Entra en este spec como cambio de configuración, sin activar todavía
el cron.

### 6.2 `validar_esquema()`

Corre **antes** de que nada entre a `xm_medida`, en dos niveles:

- **Estructural** — columnas esperadas por tipo, sin duplicados, en orden. Es lo que
  atrapa el caso real de abril 2026, en que `dspcttos` y `BalCttos` llegaron con
  columnas duplicadas y desplazadas. Sin esta validación, eso **invierte el signo de la
  exposición sin lanzar ningún error**.
- **Semántica** — la identidad de `BalCttos` tiene que cerrar; rangos y signos
  plausibles en precio y kWh.

**Política ante archivo corrupto:** entra en `xm_archivo` con `esquema_ok = false` y el
detalle del fallo, **no** entra a `xm_medida`, y queda visible en la tab.

En carga masiva se procesan **todos** los archivos, ninguno corrupto entra, y el comando
termina con error y el listado completo de rechazados. Morir en el tercero de 725
significa no enterarse de los otros 722; procesar todo y fallar al final cumple el
"nunca pasa en silencio" sin volver la carga masiva inutilizable.

### 6.3 Notas de parseo ya descubiertas

- Encoding: `utf-8-sig` con fallback a `latin1`. Separador `;`. CRLF.
- Nombres FTP: `{tipo}MMDD.{ext}` diarios, `{tipo}MM.{ext}` mensuales.
- `BalCttos` llega con extensión `.txf`, en formato horario ancho.
- `dspcttos` es por **contrato bilateral**, no por planta:
  `CONTRATO;VENDEDOR;COMPRADOR` con dos bloques horarios `DESP_HORA` y `TRF_HORA`.
- `grip` es horario ancho, ~1200 plantas y ~82 códigos en la columna `TIPO`.
- Los CGM son formato largo `Entidad,Concepto,Valor` — hay que pivotear por concepto.
- Los Excel de garantía **no** tienen los encabezados en la fila 0: hay 8–10 filas de
  metadatos. Buscar dinámicamente la fila que contiene `CÓDIGO`. Hay una fila `TOTAL` al
  final que debe excluirse.
- Los Insumos Preliminares tienen layout fijo 52×14 en la hoja `Insumos`.

---

## 7. Réplica determinística (día 7)

Para cada `gar_calculo`, con `WHERE disponible_desde <= gar_calculo.fecha_calculo`:

```
Exposición Energía en Bolsa
    = Σ_días_de_la_ventana ( exposición_neta_kWh_día × precio_día )
```

donde la exposición sale de la identidad ya verificada al centavo en `BalCttos`:

```
Generación Ideal − Contratos de venta − Pérdidas asignadas
    = Neto ventas en bolsa − Neto compras en bolsa
    = EXPOSICIÓN NETA EN BOLSA (kWh)
```

Esa identidad se usa además como **check de integridad**: si los dos lados no coinciden
en un día, ese día se marca corrupto en vez de propagarse. Es la misma clase de fallo
que el `arrpas` de marzo 2026.

### Dos correcciones que no son negociables

**El precio es ponderado, no promedio simple.** XM publica *Precio de Bolsa Ponderado
($/kWh)* en los Insumos Preliminares. Usar la media aritmética de `PBNA` desvía todo el
componente. Cuando el Insumo Preliminar no esté disponible se pondera `PBNA` por la
energía horaria y se marca la procedencia como derivada.

**Granularidad del producto energía × precio.** Tanto la exposición como `PBNA` son
horarios, así que el producto se hace **hora a hora** y recién después se agrega al día
y al período:

```
Exposición_período = Σ_horas ( exposición_neta_kWh_hora × PBNA_hora )
```

Agregar primero a día y multiplicar por un precio diario da un número distinto siempre
que la exposición horaria esté correlacionada con el precio horario — que en solar lo
está, y fuerte: generamos al mediodía, cuando el precio es distinto del promedio del
día. El *Precio de Bolsa Ponderado* que publica XM **no** se usa como multiplicador:
se usa como **check de reconciliación** — el precio implícito de nuestra suma horaria
(`Σ energía×precio / Σ energía`) debe coincidir con el que publica XM, y si no
coincide es señal de que la ventana o los datos están mal.

**La versión es TX2, no TXF.** XM lo declara explícitamente en el propio archivo:
*"Período base: últimos 30 días liquidados y última semana completa liquidada en versión
TX2 o superior"*. Usar `.txf` es data leakage — no existía en la fecha de cálculo — y
además arroja valores distintos: de 510 días comparados, 70 difieren y en varios el
signo de la exposición se invierte.

Con `disponible_desde` en el esquema esto no se hardcodea: cae solo del filtro temporal.

### Validación ya realizada

- Generación Ideal reconstruida desde `BalCttos` `.tx2` vs. la publicada por XM para el
  período base 2026-06-25 → 2026-07-24: **28 de 28 días exactos**, diferencia 0,00 kWh.
- Vto 2026-07-03 / Gar julio completo: Generación Kw publicada por XM 7.624.550,2 vs.
  reconstrucción 7.623.618,2 → **0,01%**.

---

## 8. Estimador con intervalo (día 14)

### 8.1 La ventana se arma con insumos propios

Ninguno de los cuatro términos requiere que XM haya liquidado:

| Término | Fuente | Nota |
|---|---|---|
| Generación ideal | `reporte_energia_generacion.curva_final` | por frontera, horaria, ya validada contra el ASIC |
| Contratos de venta | `dspcttos` crudo (**no** `despacho_contrato_dia`, ver abajo) | XM declara: *"No se incluyen datos de despacho de contratos dado que esta información es conocida el día de cálculo"* |
| Pérdidas asignadas | `arrpas` | FTP público |
| Precio | `PBNA` horario de `trsd` (§8.1.1) | FTP público, versionado |

Es literalmente la identidad de `BalCttos` reconstruida sin `BalCttos`.

**Nota sobre las pérdidas.** Son el 0,38% de la generación ideal, pero el **5,8% de la
exposición neta** — la exposición es la diferencia entre dos números grandes, así que un
término trivial contra el bruto pesa contra el neto. No se puede descartar por pequeño.
`arrpas` ya está disponible en `.tx2` (537 días), así que este término no introduce
leakage. La UI conserva de todos modos la marca de insumo contaminado por versión: si
algún día un insumo llega solo en `.txf`, tiene que verse en la pantalla y no pasar
inadvertido.

#### 8.1.1 De dónde sale el precio — y de dónde no

El precio de bolsa **cambia semana a semana**, así que no puede tomarse de un valor
agregado por mes. Lo que la plataforma tiene hoy no sirve para este cálculo:

| Fuente existente | Qué guarda | Por qué no sirve |
|---|---|---|
| `precio_bolsa_mensual` | Un valor por mes, cargado a mano desde `facturacion.py` | Un solo número por mes no puede valorizar una ventana semanal |
| `precios_bolsa_diario` | Diario, campo `precio_promedio` | Es **promedio simple**, que §7 prohíbe explícitamente; además no es horario |
| Origen de ambas | Cron `bolsa_ingest` → EVO `/dailyspot/latest` | Proveedor **externo**, un día a la vez. El cálculo debe reconciliar contra el precio que publica **XM** |

**La fuente autoritativa es `PBNA` horario de `trsd`**, que ya tenemos versionado: 539
días en `.tx2` y 516 en `.tx1`. Es horario, es de XM, y lleva versión de liquidación —
las tres cosas que las tablas existentes no tienen.

**El portal público de XM cubre los huecos**: días fuera del rango de `trsd`, y el
precio del día en curso antes de que exista el `.tx2`. Entra como un tipo más en
`xm_archivo` con su propio `disponible_desde`, sin tratamiento especial.

Las tablas de EVO **no se tocan**: siguen alimentando facturación, que es para lo que
existen. Este módulo no las lee ni las escribe.

#### 8.1.2 Los despachos ya están en la plataforma, con dos límites

`despacho_contrato_dia` (`periodo`, `codigo_sic_contrato`, `fecha`, `kwh`) ya se puebla
al subir el archivo de despachos en `facturacion.py`. Es útil, pero no reemplaza al
`dspcttos` crudo:

- Es **diaria, no horaria**. §7 exige el producto energía × precio hora a hora, y
  agregar a día antes de multiplicar da otro número.
- **No está versionada.** Se llena con `delete` + `insert` por período, así que es "lo
  último que alguien subió", sin distinguir `tx1` / `tx2` / `txf`. Eso rompe el
  anti-leakage: no se puede saber qué se conocía en la fecha de cálculo.

Uso: sirve como contraste operativo y para el estimador del día 14 a granularidad
diaria. La réplica auditable del día 7 usa el `dspcttos` crudo ingerido en `xm_medida`.

**TX1 como señal aún más temprana.** Hay 516 días de `trsd` en `.tx1` (2025-01 →
2026-05). El TX1 sale antes que el TX2, así que abre la puerta a estimar antes del día
14 — con más residual, pero con la misma maquinaria: es otra `version` en `xm_medida`,
con su propio `disponible_desde`. No entra en este spec, pero el esquema ya lo soporta
sin cambios.

### 8.2 El residual es el modelo

```
residual = Exposición_XM_TX2 − Exposición_reconstruida
```

No se modela la garantía: se modela **cuánto se desvía nuestra reconstrucción de lo que
XM termina liquidando**. Hay dos pares históricos ya medibles para calibrarlo, sin
conseguir datos nuevos:

1. `reporte_energia_generacion.energia_final_kwh` (propia) vs `energia_cgm_kwh` (XM), ya
   en la base, por frontera y fecha.
2. TX2 vs TXF sobre 510 días — 86% idénticos, 70 difieren.

El intervalo son los **cuantiles empíricos del residual** aplicados a la reconstrucción.
Calibración estrictamente temporal: los cuantiles de un vencimiento se estiman solo con
residuales de vencimientos anteriores.

#### Tres fuentes de incertidumbre, un solo intervalo

Todas se expresan en la misma unidad — ancho del intervalo — y por eso se pueden
componer en vez de reportarse por separado:

| Fuente | Cómo se trata | Cuándo desaparece |
|---|---|---|
| **Liquidación** — qué dirá TX2 sobre días ya ocurridos | Cuantiles empíricos del residual | Cuando XM publica (día 7) |
| **Ventana base** — cierra entre 5 y 16 días antes del cálculo, sin patrón | Calcular sobre todas las ventanas candidatas; la dispersión entre ellas es el aporte | Cuando aparece el `PERIODO BASE` observado |
| **Días sin liquidar al final de la ventana** | Se cubren con generación **medida** de la API de Unergy, no con proyección | Cuando XM liquida esos días |
| **Precio en períodos proyectados** (§8.2.1) | Error de replicar la metodología de XM, calibrado sobre la diferencia histórica entre lo que XM proyectó y lo que terminó liquidando | Cuando el período pasa a estar liquidado |

La tercera es la que justifica el requisito de ingesta diaria: si el dato medido llega
tarde, esos días no se pueden cubrir con medición y hay que proyectarlos, lo que
ensancha el intervalo justo en el momento en que más importa que sea angosto.

**La descomposición se reporta.** No basta con un ancho total: la tab muestra cuánto
aporta cada fuente. Es lo que dice dónde invertir el siguiente esfuerzo — si el 80% del
ancho viene de ventanas candidatas, conseguir los `PERIODO BASE` históricos vale más que
cualquier refinamiento del modelo de residual.

#### 8.2.1 Períodos proyectados: replicar a XM, no pronosticar el mercado

El precio de bolsa se mueve con violencia. Medido sobre los 539 días de `trsd` en
`.tx2`, el promedio mensual va de **111 $/kWh (jun-2025) a 786 $/kWh (jul-2026)** — un
factor de 7 — con saltos mes a mes de hasta **+87%**:

| Mes | $/kWh | vs. anterior |
|---|---|---|
| 2026-04 | 275,04 | +25,9% |
| 2026-05 | 514,06 | **+86,9%** |
| 2026-06 | 531,74 | +3,4% |
| 2026-07 | **786,12** | **+47,8%** |

Eso importa distinto según el período:

- **Ventana ya cerrada** (`estimado`): el precio de esos días **ya se formó y XM ya lo
  publicó** en `trsd`. No hay incertidumbre de precio. Solo falta la liquidación.
- **Períodos proyectados** (`AJUSTE PROY`, `AJUSTE M+1`, garantía mensual del mes
  siguiente, estado `preliminar`): el precio es futuro.

**Para los proyectados no se pronostica el mercado.** El sistema predice *qué va a
cobrar XM*, y XM tampoco pronostica: su metodología, declarada en el propio archivo de
Insumos Preliminares, es *"variables proyectadas con los 3 últimos meses facturados"*.
XM proyecta mirando hacia atrás.

Acertarle al precio real nos **alejaría** del número de XM. Lo correcto es replicar su
método y usar su propia proyección como ancla: los bloques *Proyección 3 meses* y
*Proyección 1 mes* de los Insumos Preliminares.

**Disponibilidad al día 14.** Los Insumos Preliminares semanales se publican casi
siempre miércoles o jueves, así que el de *nuestro* cálculo todavía no existe el día 14.
Sí existe el de la semana anterior. Como la base son 3 meses facturados, ese número se
mueve lento y sirve de ancla; la diferencia entre versiones consecutivas se calibra y
alimenta el intervalo.

**Consecuencia aprovechable.** Cuando un salto como el de julio (+47,8%) entre a la
ventana de 3 meses de XM, sus proyecciones darán un escalón. Nosotros ya sabemos que el
salto ocurrió, así que podemos anticipar ese escalón antes de que la proyección de XM lo
incorpore.

### 8.3 El piso en cero se resuelve por monotonía

El brief advertía que la variable objetivo está censurada en cero, que una regresión
estándar sobre el monto final es incorrecta, y pedía un modelo en dos partes
(clasificador + regresión condicional).

Con salida por cuantiles no hace falta. `max(0, ·)` es monótona no decreciente, así que:

```
P90( max(0, S) ) = max(0, P90(S) )
```

Se modela la suma **antes** del piso, se flooréan los cuantiles al final, y la censura
queda resuelta sin clasificador ni regresión condicional. Esto preserva además la señal
de los componentes, que era la razón por la que el brief prefería esa vía.

### 8.4 Los otros 19 componentes

Agregado por persistencia: el valor del vencimiento comparable anterior, con su propia
banda a partir de la volatilidad histórica del agregado. Se registran en
`gar_componente_real` y `gar_componente_pred` bajo el componente
`agregado_administrativos`, de modo que refinarlos después no cambia el esquema.

---

## 9. Métricas

**La métrica no es MAE.** Un intervalo se evalúa con dos números que solo tienen sentido
juntos:

| Métrica | Qué mide |
|---|---|
| **Cobertura empírica** | ¿el valor real cayó dentro del intervalo el % de veces prometido? |
| **Ancho mediano** | ¿cuán angosto es? |

Un rango que siempre acierta pero va de $0 a $300M no sirve. Ambas se reportan siempre
juntas, por vencimiento y agregadas, y **separadas por procedencia de ventana**
(observada vs. derivada).

### Baseline obligatorio

Persistencia: el valor del vencimiento anterior, con intervalo de la volatilidad
histórica ($96M de mediana semana a semana). Cualquier cosa que construyamos debe
producir un intervalo **más angosto a igual cobertura**. Si no le gana, no sirve.

### Referencia histórica (31 semanas)

- 61% de las semanas hay pago, 39% reintegro.
- Entre las de pago: mediana $60M, máximo $270M.
- Volatilidad semana a semana: mediana $96M.

Con solo ~31 observaciones de target consolidado y 20 componentes, un modelo entrenado
directamente sobre el total tendría más parámetros que datos. Esa es la razón de fondo
por la que la vía determinística + residual es el camino principal y no un paso previo
al ML.

### Agregación del horizonte

El P90 de un conjunto de vencimientos **no es la suma de sus P90**, y tampoco se obtiene
asumiendo independencia. Se estima remuestreando bloques históricos consecutivos
completos de la misma longitud que el horizonte, y tomando el cuantil empírico de sus
sumas. Ese procedimiento preserva la correlación entre semanas sin estimarla.

Se reportan las dos cifras y su brecha: la suma de P90 es el techo (reserva por semana),
el P90 del bloque es el piso (pozo común), y la diferencia es el capital que libera
juntar el pozo.

### Validación temporal

`train_test_split` con `shuffle` está **prohibido**. Toda evaluación es train pasado /
test futuro.

---

## 10. Interfaz

**Es una vista de planeación, no un reporte de backtest.** La pregunta que responde es
*cuánto necesito para las semanas que vienen y para el mes*. El backtest existe para
justificar que ese número es creíble, no para ser la portada — va al pie, en una línea.

### 10.1 Encabezado: los dos totales

Dos cifras arriba, y la diferencia entre ellas:

| Cifra | Qué responde |
|---|---|
| **Suma de los P90 semanales** | Cuánto necesito si reservo semana a semana, cada una con su colchón |
| **P90 del total del horizonte** | Cuánto necesito si mantengo un pozo común |
| **La brecha** | El capital que libera juntar el pozo |

Las dos son válidas y responden preguntas distintas de tesorería; se muestran juntas y
etiquetadas.

> **El P90 del total no se calcula asumiendo independencia.** Las semanas comparten
> régimen de generación, precio de bolsa y plantas: están correlacionadas. Asumir
> independencia reportaría un ahorro inexistente y dejaría corta la reserva.
>
> Se calcula **remuestreando bloques históricos consecutivos completos** — ventanas
> reales de N semanas seguidas, y la distribución empírica de sus sumas. Eso preserva la
> correlación sin estimarla ni modelarla.
>
> Si la correlación resulta cercana a 1 las dos cifras convergen y la brecha se va a
> cero. Ese resultado **se muestra igual**: significa que juntar el pozo no compra nada,
> y es información, no una falla.

### 10.2 Semanal y mensual, separados por toggle

No un filtro sobre una tabla común: un toggle que cambia la vista. Un filtro invita a
quitarlo y mirar todo junto, y **la cobertura agregada sobre semanal + mensual no
significa nada** — tienen estructuras de incertidumbre distintas (el mensual arrastra
ventana candidata, el semanal no). Las métricas se reportan siempre por separado.

| | Semanal | Mensual |
|---|---|---|
| Presentación | Filas de tabla | Tarjetas |
| Filas por vencimiento | 3 (`AJUSTE`, `PROY`, `M+1`) | 1 (el mes) |
| Fechas a mostrar | 3 | 4 — cierre de ventana, objetivo, publicación XM, mes garantizado |
| Alerta de margen | No aplica | Siempre visible |
| Chip de ventana | `observada` / `derivada` | `observada` / `candidatas` |

El mensual va en tarjeta porque cuatro fechas no entran en una fila sin volverla
ilegible.

### 10.3 Tres estados, no dos

Cada vencimiento futuro se marca con uno:

| Estado | Significa | Confianza |
|---|---|---|
| `firme` | XM ya publicó | Exacto |
| `estimado` | La ventana base **ya cerró**; solo falta que XM liquide días ya ocurridos | Alta |
| `preliminar` | La ventana base **sigue abierta**: hay días futuros de verdad | Menor |

La distinción entre `estimado` y `preliminar` es la que evita tratar un pronóstico real
como si fuera una reconstrucción de días pasados. No son la misma clase de número y no
merecen la misma confianza.

### 10.4 Frescura de datos

Arriba de todo, en rojo cuando aplica: **antigüedad del dato de generación más
reciente**. Más de 1 día compromete el margen de la anticipación mensual. Va primero
porque es el único elemento que puede invalidar todo lo demás de la pantalla — sin él,
los números siguen saliendo pero dejan de ser medición y pasan a ser proyección, y eso
no se nota mirando la tabla.

### 10.5 Detalle por vencimiento

Al abrir una fila o tarjeta:

- La **cadena de cálculo** completa en dos columnas (central y P90): exposición
  modelada → otros 19 por persistencia → suma → piso en cero → menos TIE → menos
  estimado provisionado → total a pagar. Cada eslabón visible y rastreable.
- Qué archivos y versiones exactos alimentaron el número.
- La **descomposición del ancho del intervalo** por fuente (liquidación / ventana
  candidata / días sin liquidar). Es lo más accionable de la pantalla: si el 71% del
  ancho viene de ventana candidata, conseguir los `PERIODO BASE` históricos vale más que
  cualquier refinamiento del modelo.

### 10.6 Al pie

Una línea con cobertura y ancho mediano contra el baseline, **separados por esquema**:
`cobertura 91% semanal / 88% mensual · ancho mediano $41M vs. baseline $96M`.

Percentil configurable desde la UI, con **P90 por defecto**. Sin gráficos en este spec:
con un solo componente modelado no hay serie que graficar.

---

## 11. Tests y Definition of Done

Fixtures recortados de archivos **reales**, no sintéticos.

| Test | Qué protege |
|---|---|
| **Idempotencia** | Cargar un mes, re-ejecutar, conteo de filas idéntico |
| **Anti-leakage** | Una medida con `disponible_desde` posterior a `fecha_calculo` **no** es usada por la réplica |
| **Rechazo por esquema** | Columna duplicada o desplazada → rechazado, no ingerido |
| **Identidad `BalCttos`** | Día que no cierra → marcado corrupto, no propagado |
| **Concepto sin tildes** | Un CSV con doble codificación matchea igual |
| **Monotonía del piso** | `max(0, P90(S)) == P90(max(0, S))` sobre datos reales |
| **Modelo vs DDL** | Extiende `tests/test_modelo_vs_ddl.py` a las cinco tablas nuevas |

El de anti-leakage es el más importante: es el único bug del proyecto que produce
resultados que **se ven bien y son falsos**.

### DoD

1. Cargar el histórico completo disponible y re-ejecutarlo sin que cambie el conteo de
   filas.
2. Un archivo corrupto queda registrado y rechazado, y la carga termina con error
   explícito listando todos los rechazados.
3. Tener, para UNGG y UNGC, el error de Exposición en Bolsa por vencimiento y período,
   con cobertura y ancho de intervalo, separado por procedencia de ventana.
4. El baseline de persistencia corrido sobre el mismo conjunto, para comparar.
5. Para la mensual: demostrar sobre los 8 meses verificados que el número sale **antes**
   de que XM publique, con la descomposición del ancho del intervalo por fuente.
6. La alerta de frescura dispara cuando el dato de generación más reciente supera 1 día.

---

## 12. Riesgos y decisiones pendientes

| # | Punto | Estado |
|---|---|---|
| 1 | Ruta FTP de CGM e Insumos Preliminares | Sin confirmar. Mientras tanto, carga masiva desde carpeta local. |
| 2 | Orden ordinal de versiones (`tx1 < tx2 < tx3 < txr < txf < txn`) | A confirmar contra los datos antes de fijarlo en código. |
| 3 | Percentil de servicio | P90 por defecto, configurable. Si tesorería define otro valor, es un parámetro, no un cambio de código. |
| 4 | Fecha de publicación derivada en el backfill | Toda la ventana histórica quedará con `origen_disponibilidad = derivado`. La cobertura reportada sobre ventana derivada es un piso, no una medición limpia. |
| 5 | Faltan días en `.tx2` en varios meses | Identificado en el análisis previo. La tab de cobertura lo expone antes de que contamine conclusiones. |
| 6 | `DemandaXAgenteSTR-Proy{MMYYYY}.xlsx` | Sin analizar. Revisar si alimenta el componente de Cargos Uso STN — fuera de este spec. |
| 7 | Agente CHVC | Única excepción a las identidades de la fórmula. No nos afecta, pero si algún día se generaliza el motor a otros agentes, hay que mirarlo. |
| 8 | Desfase 14/7 en garantía **mensual** | **Resuelto.** No aplica: la mensual tiene su propio objetivo, 30 días antes del mes garantizado, verificado 8/8 con margen mediano de 3 días. Ver §1. |
| 9 | Reconciliación del precio implícito | El precio implícito de la suma horaria debe coincidir con el *Precio de Bolsa Ponderado* de XM. Si no coincide de forma sistemática, la hipótesis de granularidad horaria de §7 está mal y hay que revisarla antes de leer cualquier métrica. |
| 10 | **Frescura de la ingesta diaria** | El margen mensual es de 0 días en el peor caso. Si `gen_sync` se cae, el margen desaparece **en silencio** — el número sigue saliendo, solo que con días proyectados en vez de medidos. La alerta de frescura no es un extra: es lo que hace confiable la anticipación mensual. |
| 11 | Migración Solenium → SolarView en curso | `_scheduled_generation_sync` está condicionado a `SOLENIUM_USER/PASS`, y `solarview_client.py` se declara "reemplazo de Solenium, Fase 1". Si esa migración corta el sync diario, se lleva puesto el margen mensual sin que nada falle visiblemente. Coordinar antes de tocarlo. |
| 12 | Dispersión entre ventanas candidatas | Si las ~12 ventanas posibles dan números muy distintos, el intervalo se vuelve tan ancho que no sirve. Es medible en el primer backtest y decide si vale la pena conseguir los `PERIODO BASE` históricos. |
| 13 | ~~Insumos sin `.tx2`~~ | **CERRADO (2026-08-26).** Llegaron los `.tx2` de `trsd`, `dspcttos` y finalmente `arrpas` (537 días). La intersección de los cuatro da 536 días. Importaba porque las pérdidas son 0,38% de la generación ideal pero **5,8% de la exposición neta** — un término trivial contra el bruto pesa contra el neto. Ya no hay leakage estructural en ningún término. |
| 14 | Rango de targets menor que el de insumos | CGM e Insumos cubren desde nov-2023, pero los targets solo van de **dic-2025 a ago-2026** (22 vencimientos del consolidado interno + los Excel de XM de may–ago 2026). El backtest está limitado por los targets, no por los insumos. Conseguir Excel de garantía anteriores a may-2026 amplía la muestra más que cualquier otra cosa. |
| 15 | `.tx2` incompleto por diseño | `BalCttos` trae 28–29 días por mes en `.tx2` contra 30–31 en `.txf` (~7% ausentes). No es error de descarga: es lo que publica XM. La tab de cobertura tiene que exponerlo antes de que contamine conclusiones. |
| 16 | Correlación entre semanas | Si la correlación es cercana a 1, el P90 del horizonte converge a la suma de P90 y la brecha se anula: juntar el pozo no libera capital. Es un resultado posible y se reporta como tal, no se esconde. Medible en el primer backtest. |
| 17 | Precio de bolsa desde fuentes inadecuadas | `precio_bolsa_mensual` es un valor por mes y `precios_bolsa_diario` es promedio simple de un proveedor externo (EVO). Ninguna sirve: el precio cambia semana a semana y debe ser ponderado y de XM. Se usa `PBNA` horario de `trsd`, con el portal público de XM para los huecos. Riesgo si alguien conecta por comodidad las tablas existentes. |
| 18 | `despacho_contrato_dia` no está versionada | Se llena con delete+insert por período. Usarla en la réplica auditable rompería el anti-leakage sin fallar visiblemente. Solo se usa en el estimador del día 14, a granularidad diaria. |
| 19 | Meses de salto de precio | La réplica de la metodología de XM tiene su mayor error justo cuando el precio salta, porque es cuando más difieren lo que XM proyectó y lo que ocurrió. El intervalo debe ensancharse en esos meses, no mantenerse. Detectable: el salto se conoce antes que el escalón en la proyección de XM. |

---

## 13. Glosario

| Término | Significado |
|---|---|
| **Agente** | Entidad registrada ante XM. UNERGY tiene dos: UNGG (generador) y UNGC (comercializador). |
| **Frontera** | Punto de medición comercial. Representamos ~54 de generación solar distribuida. |
| **Exposición en bolsa** | Energía neta comprada o vendida en el mercado spot. Negativa = vendedor neto. |
| **Liquidación** | Cálculo de XM de las transacciones de un día. Se publica en versiones sucesivas. |
| **TX1 / TX2 / TXR / TXF / TXN** | Versiones sucesivas de la liquidación. TXR **no** es un tipo de garantía: es una capa de corrección que recalcula transacciones ya liquidadas. |
| **Garantía semanal** | Vence los viernes. |
| **Garantía mensual** | Vence 16 días antes del mes garantizado. |
| **Garantía TIE** | Transacciones internacionales de electricidad. Proyecta hacia adelante. Fuera de este spec. |
| **Piso en cero** | `max(0, ·)` aplicado a la suma de componentes. Como vendedores netos operamos justo en esa frontera. |
| **CGM** | Insumos que XM efectivamente usó en cada cálculo, por vencimiento y período. Prefijos `ConGarMen`, `CarConGarMen`, `EneGarMen`. |
| **Período base** | Ventana de días cuyos datos alimentan un cálculo. |
| **Anti-leakage** | No usar información que no existía en la fecha de cálculo. |
