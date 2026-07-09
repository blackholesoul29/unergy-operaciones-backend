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
sitio → proyecto (reemplaza el hardcode de `STARLINK_TO_PANEL`). El mapeo es **1:1**:
los splits (ej. "GANDALF Y CAÑAHUATE" → 50/50) ya los resuelve el parser en
`_construir_agrupado` **antes** de agrupar, así que el `agrupado` guardado ya trae una
entrada por sitio individual ("Gandalf", "Cañahuate"):

| columna | tipo | nota |
|---|---|---|
| `id` | BigInteger PK | |
| `patron` | String, unique | nombre del sitio normalizado tal como queda en `agrupado.descripcion` (ej. `BARAYA`, `GANDALF`, `CANAHUATE`) |
| `proyecto_id` | FK → `proyectos.id`, nullable | destino; NULL = sitio conocido pero sin asignar |
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
nuevas son la proyección normalizada. Como los splits ya vienen resueltos en el
`agrupado`, cada entrada del `agrupado` produce **exactamente una fila** en
`starlink_factura_linea`.

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

### Migración y backfill (`_PENDING_DDLS` + seed en startup)

**Importante:** en este proyecto Alembic NO es el camino de deploy (ver comentario en
`app/main.py`: *"Alembic roto: la columna se provisiona aquí, no vía alembic upgrade"*).
El mecanismo real es DDL idempotente en `_PENDING_DDLS` (que corre en cada arranque) +
funciones de seed en el startup (patrón `_run_catalog_seed`).

1. **DDL** en `_PENDING_DDLS` de `app/main.py`: `CREATE TABLE IF NOT EXISTS` para
   `starlink_mapeo_sitio` y `starlink_factura_linea`, más sus índices/FK.
2. **Seed + backfill** en una función de startup `_run_starlink_mapeo_seed()`:
   - Siembra `starlink_mapeo_sitio` con las entradas actuales de `STARLINK_TO_PANEL`
     y los `SPLITS` del parser, resolviendo cada `patron` a `proyecto_id` por
     `nombre_comercial`. **Idempotente:** solo inserta patrones faltantes; NO pisa un
     `proyecto_id` ya editado por el usuario (ver memoria `feedback_seed_no_sobreescribe_datos`).
   - Reprocesa los `starlink_facturas` existentes generando sus `starlink_factura_linea`.
   Todo se despliega vía Git → Railway; nada de conexión directa a BD (memoria
   `feedback_no_direct_db`).

## Riesgos / consideraciones

- **Doble fuente de verdad del mapeo:** al mover el mapeo al backend, `STARLINK_TO_PANEL`
  en el front queda obsoleto. Debe eliminarse en el mismo cambio para no divergir.
- **Nombres que no matchean `nombre_comercial`:** el seed puede dejar filas con
  `proyecto_id = NULL` (ej. `NESTLE`, `OFICINA UNERGY`, que no son minigranjas). Es
  aceptable: quedan visibles como "sin asignar".
- **Reproceso al editar mapeo:** definir si editar un `patron` reprocesa solo el período
  abierto o todos los períodos guardados. Propuesta: reprocesar todos (son pocos) para
  mantener consistencia histórica.
- **Splits nuevos:** si aparece un sitio combinado que el parser aún no divide, se
  agrega al dict `SPLITS` del parser (patrón existente), no al mapeo. El mapeo se
  mantiene 1:1 (YAGNI).

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
