# Vínculo Starlink (Servicios de Internet) ↔ Minigranja

**Fecha:** 2026-07-09
**Estado:** Diseño aprobado en dirección — pendiente revisión final del usuario
**Repos afectados:** `unergy-operaciones-backend`, `unergy-operaciones-frontend-master`

## Problema

En Finanzas → Costos → Servicios de Internet, cada factura Starlink se guarda por
**período (YYYY-MM)** en `starlink_facturas`, con los ítems serializados como JSON
(`items_json`, `agrupado_json`). **No existe ningún vínculo persistido** entre un
sitio de internet y la minigranja (proyecto) a la que corresponde.

Hoy el único punto donde sitio → minigranja se resuelve es **en memoria, al generar
el Excel consolidado** (`costosExcelExport.js`), mediante un mapeo de texto
hardcodeado (`STARLINK_TO_PANEL` + `resolvePk`). Nada de esa resolución se guarda.

**Objetivo:** que la información de internet del mes quede vinculada por minigranja
al panel contable del mes, de forma que el panel/consolidado la **lea** por relación
persistida (igual que hoy hace con O&M y Arriendos) en lugar de re-resolver un string
cada vez.

## Alcance

**Dentro:**
- Persistir el vínculo sitio Starlink → proyecto (minigranja) por período.
- Resolver ese vínculo una sola vez al guardar la factura (PUT), no en cada export.
- Permitir corregir el mapeo sin necesidad de deploy.
- Exponer los datos de internet ya resueltos por proyecto para consumo del panel/export.

**Fuera (explícitamente):**
- **NO** se escriben líneas dentro de `panel_contable_linea`. Internet sigue siendo
  una fuente independiente que el consolidado lee (decisión del usuario: modo
  "solo consulta/consolidado", como O&M y Arriendos).
- **NO** se agrega columna `project_pk` al modelo `proyectos`. El catálogo de
  `project_pk` permanece en el frontend (`MASTER_PKS`/`PROJECT_PK`).
- El puente `nombre_comercial → project_pk` de las 24 minigranjas nuevas sin entrada
  en `PROJECT_PK` es una dependencia preexistente, **no** se resuelve aquí (pero este
  diseño no lo empeora).
- No se toca el fix de IVA ya aplicado en `costosExcelExport.js`.

## Enfoque elegido (Opción A — consulta/consolidado)

Starlink se mantiene como fuente separada. Se añade una vista normalizada y vinculada
por FK a `proyectos`, que el consolidado lee por `proyecto_id`.

### Modelo de datos

**Tabla nueva `starlink_mapeo_sitio`** — catálogo persistido y editable del mapeo
sitio → proyecto (reemplaza el hardcode de `STARLINK_TO_PANEL`):

| columna | tipo | nota |
|---|---|---|
| `id` | BigInteger PK | |
| `patron` | String, unique | nombre del sitio tal como aparece en el PDF, normalizado (ej. `BARAYA`, `GANDALF Y CAÑAHUATE`) |
| `proyecto_id` | FK → `proyectos.id`, nullable | destino; NULL = sitio conocido pero sin asignar |
| `proyecto_id_secundario` | FK → `proyectos.id`, nullable | segundo destino para splits 50/50 |
| `porcentaje` | Numeric(5,4), default 1.0 | fracción al `proyecto_id` (0.5 en splits); el resto va al secundario |
| `activo` | Boolean, default true | |
| `created_at` / `updated_at` | DateTime | |

**Tabla nueva `starlink_factura_linea`** — una fila por sitio resuelto de una factura:

| columna | tipo | nota |
|---|---|---|
| `id` | BigInteger PK | |
| `factura_id` | FK → `starlink_facturas.id`, ON DELETE CASCADE | período al que pertenece |
| `proyecto_id` | FK → `proyectos.id`, nullable | el vínculo a la minigranja (NULL = sin asignar) |
| `descripcion` | String | nombre original del sitio en el PDF (trazabilidad) |
| `sin_iva` | Numeric(15,2) | valor sin IVA (el que consume el consolidado) |
| `iva` | Numeric(15,2) | |
| `monto_total` | Numeric(15,2) | |
| `created_at` / `updated_at` | DateTime | |

`starlink_facturas` (JSON por período) **se conserva** como fuente cruda. Las tablas
nuevas son la proyección normalizada. Los splits (`GANDALF Y CAÑAHUATE` → 50/50) se
representan como **dos filas** en `starlink_factura_linea`, una por `proyecto_id`.

### Resolución (dónde y cuándo)

- La resolución sitio → `proyecto_id` corre **en el backend, al hacer
  `PUT /starlink/factura/{periodo}`**: por cada ítem del `agrupado` se busca su
  `patron` en `starlink_mapeo_sitio`, se aplica el split según `porcentaje`, y se
  (re)generan las filas de `starlink_factura_linea` para esa factura.
- El emparejamiento `starlink_mapeo_sitio.patron` se hace sobre el nombre normalizado
  (mayúsculas, sin acentos/espacios extra), reutilizando la lógica de normalización
  ya existente en el parser.
- Sitios sin `patron` en el catálogo, o con `proyecto_id = NULL` → la línea se crea con
  `proyecto_id = NULL` y se marca como "sin asignar" para revisión (hoy se pierden en
  silencio en el export).

### Endpoints (backend, repo `unergy-operaciones-backend`)

- `PUT /starlink/factura/{periodo}` — extender: además de guardar el JSON, resolver y
  regenerar `starlink_factura_linea`.
- `GET /starlink/factura/{periodo}` — extender: devolver también `lineas` (agrupado ya
  resuelto con `proyecto_id`, `nombre_comercial` y `sin_iva`).
- `GET /starlink/mapeo` — listar el catálogo `starlink_mapeo_sitio`.
- `PUT /starlink/mapeo/{id}` (o upsert por `patron`) — crear/editar un mapeo. Al
  cambiar un mapeo se puede reprocesar el período afectado.
- Espejo del patrón ya existente `POST /panel-contable/mapeo-celda` (mapeo persistente
  editable) para mantener consistencia.

### Frontend (repo `unergy-operaciones-frontend-master`)

- `costosExcelExport.js`: en `pubByPk`, en lugar de `resolvePk(starlinkPanel(desc))`
  sobre el string crudo, consumir las `lineas` resueltas (`proyecto_id` +
  `nombre_comercial`) que ahora entrega `GET /starlink/factura/{periodo}`. La
  conversión `nombre_comercial → project_pk` sigue usando `PROJECT_PK` (sin cambios en
  ese catálogo). Se mantiene el uso de `sin_iva` (fix ya aplicado).
- `StarlinkPDF.vue`: columna con la minigranja resuelta; UI para asignar/corregir los
  sitios "sin asignar" contra `starlink_mapeo_sitio`.

### Migración y backfill (Alembic)

1. Migración que crea `starlink_mapeo_sitio` y `starlink_factura_linea`.
2. **Data migration** que:
   - Siembra `starlink_mapeo_sitio` con las entradas actuales de `STARLINK_TO_PANEL`
     y los `SPLITS` del parser, resolviendo cada `patron` a `proyecto_id` por
     `nombre_comercial`.
   - Reprocesa los `starlink_facturas` existentes generando sus `starlink_factura_linea`.
   Respeta la regla de no tocar BD directamente: todo vía Alembic desplegado por
   Railway (ver memoria `feedback_no_direct_db`).

## Riesgos / consideraciones

- **Doble fuente de verdad del mapeo:** al mover el mapeo al backend, `STARLINK_TO_PANEL`
  en el front queda obsoleto. Debe eliminarse en el mismo cambio para no divergir.
- **Nombres que no matchean `nombre_comercial`:** el seed puede dejar filas con
  `proyecto_id = NULL` (ej. `NESTLE`, `OFICINA UNERGY`, que no son minigranjas). Es
  aceptable: quedan visibles como "sin asignar".
- **Reproceso al editar mapeo:** definir si editar un `patron` reprocesa solo el período
  abierto o todos los períodos guardados. Propuesta: reprocesar todos (son pocos) para
  mantener consistencia histórica.
- **Splits con porcentaje ≠ 50/50:** el modelo soporta `porcentaje` arbitrario, pero
  la UI inicial puede limitarse a 50/50 (YAGNI) y ampliarse si aparece el caso.

## Criterios de aceptación

1. Tras guardar una factura, existe una fila en `starlink_factura_linea` por cada sitio,
   con `proyecto_id` resuelto (o NULL si no mapea), y los splits divididos correctamente.
2. `GET /starlink/factura/{periodo}` devuelve las líneas resueltas con `nombre_comercial`.
3. El Excel consolidado produce, para `public_services`, los mismos valores por
   minigranja que hoy pero derivados del `proyecto_id` persistido (no del string).
4. Un sitio sin mapeo aparece como "sin asignar" en la UI y puede corregirse; tras
   corregirlo, el valor se refleja en el consolidado.
5. El backfill genera las líneas de los períodos históricos sin pérdida de montos
   (suma por período = `suma_items` original, salvo redondeos ya existentes).
