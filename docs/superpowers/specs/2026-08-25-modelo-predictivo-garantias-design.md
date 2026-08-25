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

> **Alcance de esta regla.** El timeline está verificado sobre un vencimiento
> **semanal**. La garantía **mensual** vence 16 días antes del mes garantizado — otra
> cadencia — y no hay evidencia de que le aplique el mismo desfase de 14/7. Para
> `esquema = mensual` la ventana se toma de las fuentes observadas (`PERIODO BASE`,
> nombre CGM, calendario) y **no** de esta regla; la derivación por regla general queda
> restringida a `semanal`. Verificarlo es tarea del primer backtest.

### Sistema de dos velocidades

| Momento | Salida | Mecanismo |
|---|---|---|
| 14 días antes | Rango: valor central + cuantil superior | Reconstrucción con insumos propios + residual calibrado |
| 7 días antes | Número firme | Réplica determinística con el TX2 publicado |

La estimación temprana se reemplaza por la firme cuando XM publica. El valor del
sistema es la semana de anticipación que gana entre ambos momentos.

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
- Backtesting con cobertura y ancho de intervalo, contra los 149 vencimientos CGM.
- Tab con cobertura de datos, tabla de backtest y detalle por vencimiento.
- **UNGG y UNGC**, ambos. Es el mismo camino de código con otra entidad.

### Fuera

| Qué | Por qué |
|---|---|
| Garantía TIE | Proyecta hacia adelante mientras la nacional ajusta hacia atrás. Se reparte por participación en compras en bolsa y usa TRM del día. Lógica aparte, spec aparte. |
| Los otros 19 componentes en detalle | Entran como agregado por persistencia. Se refinan cuando el backtest muestre que su error es material. |
| Cualquier modelo de ML | Fase 3 del brief, contingente a que la vía determinística + residual deje error material. |
| Cron automático de descarga FTP | Se deja el enganche y las variables de entorno documentadas; en este spec la carga es manual. |
| Saldo de cuenta custodia / "efectivo a conseguir" | Retirado del alcance por la adenda corregida del 2026-08-25. |

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

**Regla para este módulo:** cada tabla y cada columna se declara en una migración
Alembic **y** en `_PENDING_DDLS` con `IF NOT EXISTS`. Se extiende
`tests/test_modelo_vs_ddl.py` a las cinco tablas nuevas.

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
| `tipo` | varchar | `balcttos`, `trsd`, `tgrl`, `grip`, `dspcttos`, `arrpas`, `cxcsb`, `cgm_con`, `cgm_car`, `cgm_ene`, `insumos_prelim`, `calendario`, `garantia_excel` |
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

**El período va en la clave a propósito.** De los 149 vencimientos, 93 cubren dos
períodos y 56 uno solo. Ejemplo real de julio 2026:

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

Esto importa porque aplicando una ventana uniforme de 30 días a todos los vencimientos,
solo **13 de 127** quedaron dentro de ±3%. Sin separar "ventana observada" de "ventana
derivada", el backtest no puede distinguir el error del modelo del error de la ventana.

### 5.4 `gar_componente_real` — el target

| Campo | Nota |
|---|---|
| `calculo_id` | FK → `gar_calculo` |
| `componente` | uno de los 20, o `agregado_administrativos` |
| `valor` | numeric |

`UNIQUE (calculo_id, componente)`. Se parsea de la hoja `PERIODOS A GARANTIZAR` de los
`GARANTIA_TXR_*.xlsx`.

### 5.5 `gar_componente_pred` — la predicción

| Campo | Nota |
|---|---|
| `calculo_id` | FK → `gar_calculo` |
| `componente` | |
| `horizonte_dias` | `14` \| `7` |
| `cuantil` | `0.5` \| `0.9` (configurable) |
| `valor` | numeric |
| `modelo_version` | qué versión del código lo produjo |
| `insumos` | jsonb: qué archivo y qué versión alimentó cada término |
| `calculado_en` | timestamptz |

```sql
UNIQUE (calculo_id, componente, horizonte_dias, cuantil, modelo_version)
```

`horizonte_dias` guardado explícitamente permite medir exactamente lo que la adenda
quiere saber: cuánto se gana adelantándose una semana. `insumos` es lo que permite
auditar por qué cambió un número entre corridas.

---

## 6. Ingesta y validación

### 6.1 Origen de los archivos

| Familia | Cómo llega |
|---|---|
| 7 tipos FTP | `app/services/xm/` ya los descarga. Falta persistir credenciales. |
| CGM (725 CSV) e Insumos Preliminares (212 xlsx) | Carga masiva desde una carpeta local que provee el usuario |
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
| Contratos de venta | `dspcttos` | XM declara: *"No se incluyen datos de despacho de contratos dado que esta información es conocida el día de cálculo"* |
| Pérdidas asignadas | `arrpas` | FTP público |
| Precio | `PBNA` diario ponderado por energía horaria | FTP público |

Es literalmente la identidad de `BalCttos` reconstruida sin `BalCttos`.

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

### Validación temporal

`train_test_split` con `shuffle` está **prohibido**. Toda evaluación es train pasado /
test futuro.

---

## 10. Interfaz

Tercera tab, sin gráficos: con un componente modelado no hay dashboard que valga. Tres
bloques, `DataTable` de PrimeVue.

1. **Cobertura de datos** — qué rango hay por tipo y por versión, y qué archivos fueron
   rechazados por `validar_esquema()`. El primer problema real va a ser "faltan días en
   `.tx2`", y conviene verlo antes de sacar conclusiones del error.
2. **Backtest** — una fila por (agente, vencimiento, período): esquema, período,
   predicho día 14 (central y P90), predicho día 7, real, dentro-del-intervalo, ancho.
   La **procedencia de la ventana** como chip filtrable.
3. **Detalle** — al abrir una fila: desglose diario, y qué archivos y versiones exactos
   alimentaron el número.

Percentil configurable desde la UI, con **P90 por defecto**.

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
| 8 | Desfase 14/7 en garantía **mensual** | Verificado solo para semanal. Para mensual la ventana se toma de fuentes observadas y la regla general no se aplica. Lo confirma o lo desmiente el primer backtest. |
| 9 | Reconciliación del precio implícito | El precio implícito de la suma horaria debe coincidir con el *Precio de Bolsa Ponderado* de XM. Si no coincide de forma sistemática, la hipótesis de granularidad horaria de §7 está mal y hay que revisarla antes de leer cualquier métrica. |

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
