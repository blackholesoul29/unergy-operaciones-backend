# 00 · Inventario del estado actual

**Alcance:** las 8 áreas que toca el refactor (proyecto, equipos, frontera, red, clientes, propiedad,
contratos, fallas). No re-describo la BD completa: para eso ya están `ESQUEMA_BD_PRODUCCION.md` y
`ARQUITECTURA_MONITOREO.md`, y los cito en vez de rehacerlos.
**Novedad de este documento:** cruza el esquema con la **medición real de filas y de llenado**
(`uso_real.json`, 2026-08-23 18:20), que es lo que distingue "columna que existe" de "columna que se usa".
**Conclusión de una línea:** el esquema modela mucho más de lo que la operación llena, y las relaciones
que de verdad sostienen el negocio hoy son de texto, no de clave foránea.
**Actualizado el 2026-08-26:** hay un **apéndice al final** con lo que cambió en estos 3 días (86
commits; `fronteras` bajó de 101 a 40 columnas). El cuerpo se conserva como la foto del 2026-08-23.

---

## Fuentes y jerarquía

| Fuente | Qué aporta | Cuándo gana |
|---|---|---|
| `esquema-bd-produccion/esquema_produccion.sql` (10 912 líneas, `pg_dump --schema-only`) | DDL real | **Gana siempre** (`CLAUDE.md:38`) |
| `esquema-bd-produccion/uso_real.json` (2026-08-23 18:20) | filas por tabla, % de llenado por columna, 213 columnas 100 % vacías | Único con datos reales |
| `app/models/*.py` (40 archivos, 111 clases) | intención, comentarios, cascadas de Python | Cuando el DDL no explica el *por qué* |
| `esquema-bd-produccion/DEPURACION.md` | 14 hallazgos previos | Solo como pista: **F1 está obsoleta** (ver §11.J) |

Repo verificado: `master` == `origin/master` (0/0 tras `git fetch`), último commit `370b9cf` del 2026-08-23.

Totales: **125 tablas · 1 619 columnas · 148 FK · 52 ENUM · 7 CHECK · 0 vistas · 29 tablas en 0 filas.**

---

## 1 · Las cifras que enmarcan todo

`proyectos` tiene **194 filas**. Nada en el dominio central es un problema de volumen; el volumen está
en fallas y en tablas de series (`finanzas_mandatos` 1 194, `precios_bolsa_*`, `generacion_diaria`).

| Con historia real que preservar | Filas | | En 0 filas: rediseñables sin migrar | Filas |
|---|---:|---|---|---:|
| `fallas` | 6 478 | | `mantenimientos` | 0 |
| `falla_inversores` | 4 213 | | `mantenimiento_impacto` | 0 |
| `fallas_seguimientos` | 1 134 | | `polizas` | 0 |
| `proyecto_inversores` | 715 | | `servicio_operacion` | 0 |
| `proyectos` | 194 | | `servicio_representacion` | 0 |
| `contratos_servicio` | 177 | | `alarmas_monitoreo` | 0 |
| `oportunidad_ofertas` | 163 | | `fronteras_lecturas` | 0 |
| `fronteras` | 147 | | `alias_fuente_ingreso` | 0 |
| `clientes` | 122 | | | |
| `proyecto_inversionistas` | 115 | | **Casi vacías** | |
| `proyecto_info_tecnica` | 110 | | `proyecto_inicio_operacion` | **2** |
| `oportunidades` | 105 | | `registro_conexion` | 5 |
| `proyecto_area_contacto` | 47 | | `operadores_red` | 7 |
| `starlink_mapeo_sitio` | 45 | | `operadores_red_contactos` | 11 |
| `ppa_contrato_proyectos` | 42 | | `portafolios` | 24 |
| `contactos` | 39 | | `arr_proyectos` | 27 |
| `ppa_contratos` | 34 | | `mandatos` | 31 |

Dos lecturas inmediatas:

- **El modelo de equipos se puede construir nuevo.** El checklist JSONB de `proyecto_inicio_operacion`
  con 21 tipos de equipo tiene **2 filas**: no es historia, es un prototipo.
- **`polizas`, `mantenimientos` y `mantenimiento_impacto` están vacías**, así que "garantía por vencer"
  y "mantenimiento pendiente" —los dos requisitos derivados del brief— hoy **no tienen ni un dato**.

---

## 2 · Proyecto

**`proyectos`** — 61 columnas, 194 filas, PK `id` bigint (`app/models/proyectos.py:77`;
DDL `esquema_produccion.sql:4642-4728`). Es el hub del esquema: **39 FK apuntan a ella**.

No existe ninguna tabla satélite de simulación, ubicación, estado ni comercialización: los cinco
subsistemas están mezclados en la misma fila.

| Subsistema dentro de `proyectos` | Columnas | Llenado real |
|---|---|---|
| Identidad y nombres | `nombre_comercial` (NOT NULL), `nombre_bitacora`, `nombre_clientes`, `nombre_comunidad` | los 3 últimos **0 %** |
| Claves de integración externa | `sub_project` 49,5 % · `topic_slug` 28,4 % · `project_id_solenium` 29,4 % · `sunfactory_project_id` 63,9 % · `origina_code` 62,4 % · `codigo_tsf` · `topico_liquidaciones` · `quoia_reporte_generacion_id`/`_consumo_id`/`quoia_nodo_id` **0 %** · `codigo_cnd` **0 %** | 7 claves vivas para la misma planta |
| Clasificación | `clasificacion_regulatoria`, `tipo_tecnologia`, `tipo_proyecto`, `estado` (4 ENUM nativos) | — |
| Potencia | `potencia_instalada_kwp` **33,5 %** · `potencia_con_cen_mw` **0 %** · `produccion_especifica_kwh_kwp` | ver §11 y `05-impacto` |
| Ubicación | `departamento` / `municipio` 76,3 % · `direccion_vereda` · `latitud`/`longitud` 74,2 % · `tipo_conexion` **0 %** | strings libres, sin catálogo DIVIPOLA |
| Simulación | `p50_mensual_kwh`, `p90_mensual_kwh`, `p99_mensual_kwh` (JSONB, arrays de 12) | **20,1 %** (39 de 194) |
| Promedio de generación (caché) | `gen_mensual_promedio_mwh` 24,7 % + `gen_promedio_origen`/`_dias`/`_desde`/`_hasta`/`_actualizado_en` | caché declarada en `proyectos.py:115-134` |
| Pipeline de construcción / TSF | `fase_construccion` 86,1 % (varchar libre) · `fecha_estimada_energizacion` · `avance_obra_pct` · `origen` | las crea un **router en runtime**, ver §11.I |
| Flags de servicio | `srv_operacion`, `srv_representacion`, `srv_cgm`, `srv_ppa`, `srv_promotor`, `srv_rec` | derivados, ver §11.E |
| Red | `operador_red` varchar(100) **32,5 %** · `operador_red_id` FK **43,3 %** | conviven texto y FK |
| Fechas | `fecha_entrada_operacion` 38,1 % · `fecha_inicio_comercializacion` 43,8 % (+ flag `_editada_manual`) · `fecha_fin_representacion` | |
| Vida de la fila | `created_at`, `updated_at`, `deleted_at` (**0 %**: nunca se ha borrado un proyecto) | |

**Constraints:** 4 UNIQUE (`sub_project`, `topic_slug`, `project_id_solenium`, `sunfactory_project_id`),
**0 CHECK**, 11 índices. **Las 3 FK salientes no declaran `ON DELETE`.**
De las 39 FK entrantes, **25 no declaran `ON DELETE`** — entre ellas `fallas`, `fronteras`,
`contratos_servicio`, `proyecto_inversores`, `proyecto_inversionistas`.

### Satélites de la ficha

| Tabla | Cols | Filas | Cardinalidad | Nota |
|---|---:|---:|---|---|
| `proyecto_info_tecnica` | 33 | 110 | **1:1** (índice UNIQUE en `proyecto_id`) | 32 de 33 nullables; `potencia_panel_kwp` y `potencia_inversores_kwp` son **varchar(100)**; `tiene_internet` varchar(10) y `tipo_tracker` varchar(10) son booleanos disfrazados |
| `portafolios` | 6 | 24 | padre | `descripcion` 0 % |
| `proyecto_area_contacto` | 6 | 47 | 1:N | UNIQUE `(proyecto_id, tipo)` → un solo contacto por área y planta |
| `proyectos_pendientes_ignorados` | 5 | — | catálogo | UNIQUE `clave` varchar(120) |

---

## 3 · Equipos — el hallazgo central

**No existe la entidad «equipo».** Ya está documentado en `docs/ARQUITECTURA_MONITOREO.md` §4; lo que
agrega este inventario es la medición, y la medición es más grave que el diagnóstico.

### 3.1 `proyecto_inversores` — 715 filas, y ninguna identidad física

12 columnas (`app/models/proyectos.py:308`). Llenado real:

| Columna | Llenado | Lectura |
|---|---:|---|
| `nombre` | **100 %** | son casillas numeradas ("Inversor 1"…"Inversor 5") |
| `potencia_nominal_kw` | **100 %** | sembrada por `_run_inversores_minigranja_seed` (`app/main.py:3274`) |
| `tipo` | 98,6 % | ENUM `tipo_inversor_enum` |
| **`marca`** | **0 %** | |
| **`modelo`** | **0 %** | |
| **`numero_serie`** | **0 %** | |

El "registro individual de inversores" que el brief da por bueno **existe como estructura y está vacío
como inventario**: 715 filas que solo dicen "esta planta tiene una casilla de 300 kW". Sin serial no hay
garantía, no hay reemplazo trazable y no hay mantenimiento por equipo.
**Sin UNIQUE:** nada impide dos inversores con el mismo `numero_serie` ni el mismo `nombre` en una planta.

### 3.2 El vínculo falla→inversor está roto en la práctica

`falla_inversores`, 4 213 filas (`app/models/fallas.py:283`):

| Columna | Llenado | Lectura |
|---|---:|---|
| **`proyecto_inversor_id`** (FK, nullable) | **0,3 % — 11 de 4 213** | la FK al inversor real casi nunca se escribe |
| `nombre` varchar(120) (copia) | **100 %** | **este es el vínculo real: un texto** |
| `potencia_kw` (copia) | 100 % | |
| `tipos` jsonb | 100 % | sin esquema |

Es el mismo antipatrón de §11.A pero en el corazón de la operación: 4 202 registros de falla de
inversor que no se pueden atribuir a un inversor. Sin UNIQUE `(falla_id, proyecto_inversor_id)`.

### 3.3 Las otras dos representaciones del mismo activo

- **`proyecto_inicio_operacion`** (11 cols, **2 filas**): 4 JSONB `NOT NULL DEFAULT` sin ningún esquema
  en BD — `checklist`, `pruebas`, `documentos`, `pendientes`. El docstring lo declara sin ambigüedad:
  *"el catálogo de ítems lo define el frontend, el backend solo persiste el estado"*
  (`app/models/inicio_operacion.py:12-14`). No hay catálogo, ni validación, ni historial de quién marcó qué.
- **`ESTRUCTURA_FALLAS`**, lista Python hardcodeada, cuarta representación (ver `ARQUITECTURA_MONITOREO.md` §4).

### 3.4 Mantenimiento, garantía y Starlink

| Tabla | Cols | Filas | Estado |
|---|---:|---:|---|
| `mantenimientos` | 10 | **0** | 2 ENUM, sin UNIQUE, sin CHECK, **sin historial de estado**, sin router propio (solo lo lee `monitoreo.py`) |
| `mantenimiento_impacto` | 14 | **0** | `maintenance_type` varchar(50) sin enum ni CHECK; columnas en inglés en un esquema en español; `created_by` es **FK sin índice**; `falla_id`→`fallas` **ON DELETE SET NULL** (`DEPURACION.md` afirma que no tiene FK y **está equivocado**) |
| `polizas` | 23 | **0** | **1:1 con proyecto** (UNIQUE `proyecto_id`) → estructuralmente **no puede guardar el histórico de pólizas** |
| `starlink_facturas` | 8 | 3 | `items_json` y `agrupado_json` son **text NOT NULL con JSON dentro**, no jsonb |
| `starlink_mapeo_sitio` | 7 | 45 | `patron` varchar(255) UNIQUE: tabla cuyo **propósito es cruzar por texto** contra la descripción de la factura |
| `starlink_factura_linea` | 10 | — | docstring: *"proyección normalizada de agrupado_json"* → tabla entera derivada |
| `garantia_snapshot` / `garantia_pagado` / `garantias_ajustes` | 17/5/18 | — | **3 tablas isla**, ninguna FK; son garantías financieras de XM, no de equipo |

**No hay ninguna tabla de garantía de equipo, fecha de compra, puesta en servicio ni intervalo de
mantenimiento.** Los cuatro campos comunes que pide el brief no existen en ninguna parte.

---

## 4 · Frontera

**`fronteras`** — **101 columnas**, 147 filas, 94 columnas nullables (`app/models/fronteras.py:32`;
DDL `esquema_produccion.sql:2315-2418`). `DB_REVIEW_TEAM.md` ya la clasificó como *God Table*.
Solo 5 columnas son NOT NULL de negocio: `nombre_frontera`, `tipo_frontera`, `estado`,
`es_agrupadora`, `es_principal_embebido`.

| Bloque | Columnas | Medición |
|---|---|---|
| Identidad | `codigo_frontera` UNIQUE 98,6 %, `codigo_propio`, `proyecto_id` **100 %** | toda frontera tiene planta |
| Jerarquía entre fronteras | `frontera_gemela_id`, `agrupada_bajo_id`, `embebida_bajo_id` (3 auto-FK) | **las 3 al 0 %** |
| Técnico | ~15 cols: tensión, capacidad de transporte, factores, clases CT/PT | `punto_conexion` 0 %, `subestacion` 0 % |
| Ubicación | 8 cols, duplicando las de `proyectos` | `nombre_predio` y `predio_id` 0 % |
| **Agentes en texto libre** | 13 cols: `registrada_por`, `nit`, `representante_frontera`, `operador_red`, `nombre_cgm`, `representante_ddv`, `nit_rf`, `nit_cgm`, `representante_anterior`, `agente_exportador`, `agente_importador`, `nombre_recurso_generacion` | `nit`, `nit_rf`, `nit_cgm`, `representante_ddv` al **0 %** |
| Códigos SIC | 6 cols | `codigo_sic_frontera_generacion` 63,9 %; `niu`, `codigo_sic_ddv`, `codigo_sic_submercado_usuario` **0 %** |
| **Medidor principal (13) + respaldo (12), espejados** | `nro_serie_med_ppal` 82,3 % / `_resp` 81,6 %; marca, modelo, clase, calibración, módem, password, puerto, canal | `ip_modem_*`, `puerto_modem_*`, `password_medidor_*`, `tipo_extraccion_*`, `canal_comunicacion_*` al **0 %** |
| Factores de agrupación/embebido | `factor_psf`, `factor_acordado`, `factor_ajuste`, `factor_perdidas_frontera_principal` | acompañan a la jerarquía muerta |

**29 de las 101 columnas están 100 % vacías.** Las 5 FK **no declaran `ON DELETE`**; UNIQUE solo en
`codigo_frontera`; **0 CHECK** — nada ata un bloque a su `tipo_frontera` ni a `es_agrupadora`.
9 índices, con dos pares redundantes (§11.H).

`tipo_frontera` (100 % lleno) tiene 5 valores: `generacion | consumo | generacion_consumo |
consumo_auxiliar | consumo_propio`. **Dato que la medición no puede dar:** cuántas fronteras tiene cada
proyecto. `uso_real.json` mide llenado, no distribución, así que **desde el código no se puede afirmar
si la relación proyecto↔frontera es 1:1 hoy.** Es la pregunta abierta de §12.

Satélites: `fronteras_lecturas` (13 cols, **0 filas**, UNIQUE `(frontera_id, fuente, fecha_hora)`) y
`fronteras_quoia_ignoradas` (5 cols, UNIQUE `frt_code`).

---

## 5 · Red

**`operadores_red`** — **5 columnas**, 7 filas (`app/models/operadores_red.py:9`):
`id`, `nombre_legal` NOT NULL UNIQUE, `nombre_comercial`, `created_at`, `updated_at`.
Eso es todo el catálogo: **no hay NIT, ni código, ni región, ni circuitos**. De los campos que pide el
brief (NIT, razón social, nombre comercial, correos y nombres de contacto, códigos de circuito,
fronteras propias) solo existen dos.

`operadores_red_contactos` — 6 cols, 11 filas, FK **ON DELETE CASCADE** (una de las pocas explícitas).
Sin UNIQUE en `(operador_red_id, email)`.

**Circuito, transformador y nodo no existen.** Búsqueda en el DDL completo: solo tres apariciones, todas
como atributo de texto o id externo — `fronteras.subestacion` varchar(255) (**0 %**),
`proyecto_info_tecnica.marca_transformador`, y `proyectos.quoia_nodo_id` integer sin FK (**0 %**).
No hay topología de red de ningún tipo. Consecuencia directa: **no hay dónde colgar la idea de que
5 proyectos comparten punto de conexión**, que es lo que haría falta para que un corte sea un solo incidente.

Adyacente: `registro_conexion` (15 cols, 5 filas, **1:1 con proyecto**, FK CASCADE) con satélites
`registro_etapa`, **`registro_transicion`** (el historial de estado más completo de la base:
`de_estado` + `a_estado` + `fecha` + `actor`), `registro_hito`, `registro_documento`, `registro_alerta`,
`registro_equipo_frontera`, `registro_parametros_93`. **Es el único subdominio que ya hace bien el
historial de estados** y sirve de patrón a imitar.

---

## 6 · Clientes y propiedad

### 6.1 `clientes` — 25 cols, 122 filas

Único NOT NULL de negocio: `razon_social_nombre`. **`nit_cedula` es nullable pero UNIQUE**, y está
lleno al **29,5 %** — o sea 86 clientes sin NIT (el UNIQUE sobre NULL no aplica en Postgres, así que no
hay conflicto, pero tampoco identidad). `tipo_persona` 21,3 %.
Bloque bancario **al 0 %** (`banco`, `tipo_cuenta`, `numero_cuenta`, `titular_cuenta`, `rut_url`): los
documentos que pide el brief (RUT, cámara de comercio, certificación bancaria) viven en
`cliente_documentos_comerciales` (14 cols), no acá.
`origen_tipo` varchar(30) **a propósito sin ENUM de BD** — decisión documentada en `clientes.py:56-60`:
la validación vive en Pydantic.

**3 columnas fantasma:** `correo_liquidacion`, `correo_monitoreo`, `correo_soporte` existen en la BD
porque `init_db.py:add_columns()` las agrega, pero **el modelo `Cliente` ya no las declara**. Las tres
están al 0 %. Es el único drift ORM↔BD de la base (`esquema.json:analisis.drift`).

`contactos` — 9 cols, 39 filas, UNIQUE `(cliente_id, email, tipo)`, ENUM de 5 tipos
(`operacional|cgm|liquidacion|comercial|contable`). `telefono` al **2,6 %** (1 de 39).
**Los contactos cuelgan del cliente, no del proyecto**; el puente es `proyecto_area_contacto`, y si no
hay fila la API cae a los contactos de los inversionistas vigentes (`app/api/v1/proyectos.py:1094`).

### 6.2 El porcentaje de propiedad — `proyecto_inversionistas`, 115 filas

10 columnas (`app/models/proyectos.py:328`). Es el punto más frágil del inventario.

| Columna | Llenado | Problema |
|---|---|---|
| `porcentaje_participacion` numeric(10,7) **nullable** | 99,1 % | se puede registrar dueño sin porcentaje |
| `fecha_inicio` | **36,5 %** | |
| `fecha_fin` | **9,6 %** | |
| `contrato_ref` varchar(100) | **0 %** | el contrato de la participación, como texto |
| `es_patrimonio_autonomo` bool NOT NULL | — | |

Las columnas de vigencia **existen** y el código las usa para filtrar vigentes
(`app/api/v1/fallas.py:603-606`), pero con `fecha_inicio` al 36,5 % **hoy es imposible responder quién
era dueño de qué porcentaje en una fecha pasada**: en 73 de 115 filas no se sabe desde cuándo.

Y el porcentaje **se sobrescribe**: el PATCH hace `setattr` directo sobre la fila
(`app/api/v1/proyectos.py:1168-1178`) y el DELETE es **borrado físico** (`:1181-1187`). No hay tabla de
historial. Único CHECK: `ck_inversionista_pct_rango` (0 ≤ pct ≤ 100). **No hay constraint de que la suma
por proyecto sea 100**, ni de no solapamiento de vigencias, ni UNIQUE `(proyecto_id, cliente_id)` — esa
unicidad se valida solo en Python (409 en `proyectos.py:1154-1158`).

Consumidores del porcentaje: `panel_contable_linea.proyecto_inversionista_id` (**FK sin índice**) y
`liquidacion_facturas.proyecto_inversionista_id`. Es decir: **las liquidaciones ya dependen de un dato
que se sobrescribe sin dejar rastro.**

### 6.3 Segundo padrón de inversionistas, incompatible con el primero

`mandato_inversionistas` — 7 cols (`app/models/mandatos.py:25`): `nombre` varchar(255) NOT NULL,
**`correos` jsonb**, **`proyectos` jsonb**. Sin FK a `clientes` ni a `proyectos`: los proyectos son una
lista JSON de nombres. Es la segunda lista de inversionistas de la base y no cruza con la primera.

### 6.4 Tasas por servicio, duplicadas

`cliente_tasa_servicio` (10 cols): `servicio` **varchar(30) sin ENUM**; `iva_pct`, `reteica_pct`,
`reteiva_pct` y `proyecto_id` al **0 %**; UNIQUE `(cliente_id, servicio, proyecto_id)` que **no aplica**
porque `proyecto_id` es NULL en todas las filas; `proyecto_id` es **FK sin índice**.
Las mismas 4 tasas están también en `clientes` **sin ninguna regla de precedencia en la BD**.

---

## 7 · Contratos

No existen tablas llamadas `contratos`, `servicios` ni `arriendos`. Los nombres reales son otros y hay
**tres mecanismos distintos y no equivalentes** para unir cliente ↔ proyecto ↔ contrato.

### 7.1 `contratos_servicio` — 61 columnas, 177 filas

`app/models/contratos.py:56`; DDL `:1561-1647`. Solo 2 NOT NULL de negocio: `servicio_aplica` (ENUM de 8
valores) y `estado` (ENUM). **`proyecto_id` es nullable** (92,1 % lleno) y **la FK no declara `ON DELETE`**.

Discrimina por `servicio_aplica` y guarda **todos los bloques en la misma fila**, sin un solo CHECK que
ate un bloque a su tipo de servicio:

| Bloque | Cols | Llenado destacado |
|---|---|---|
| Partes, duplicadas en texto **y** en FK | `contratante_nombre` 55,4 % + `contratante_nit` + `contratante_id` FK **0 %**; ídem prestador (`prestador_id` **0 %**, `prestador_nit` **0 %**) | **la relación con el cliente es 100 % texto** |
| CGM | `cgm_codigo_sic`, `cgm_porcentaje_fncer` **0 %**, `cgm_tipo_asignacion` **0 %** | |
| Promotor | `promotor_tarifa` **0 %**, `promotor_condiciones` **0 %** | bloque muerto |
| REC | `rec_cantidad`, `rec_precio_unitario`, `rec_vintage` — **los 3 al 0 %** | bloque muerto |
| **Internet / Starlink** | 13 cols dentro del contrato: `plan_datos_gb`, `velocidad_mbps` **0 %**, `id_router`, `numero_kit`, `latencia_ms`, `wifi_seguridad`, **`wifi_password` 0 %**, `ubicacion_lat`, `ubicacion_lng`, `tarifa_mensual` | credenciales y telemetría de equipo dentro de la tabla de contratos |
| Comercial | `numero_contrato` **1,1 % (2 de 177)**, fechas, `tarifa_base`, `periodicidad_pago`, `indice_indexacion`, `estado_pago` varchar(20) sin ENUM | |
| **6 JSONB sin esquema** | `indexacion_anual`, `indexacion_mensual`, `facturas_solenium` (**0 %**), `facturas_inversionistas`, `indexacion_cgm`, `indexacion_representacion` | `contratos.py:106-119` |
| Denormalizaciones en texto | `nombre_proyecto_ref` 40,7 % (**con índice propio**), `inversionista_nombre` 62,1 %, `portafolio`, `codigo_sun_factory` | ver §11.A |

**UNIQUE: ninguno** (ni en `numero_contrato`). **CHECK: ninguno.**
Un contrato **no puede cubrir dos plantas**: `proyecto_id` es escalar.

### 7.2 `ppa_contratos` — 35 cols, 34 filas

`app/models/contratos.py:153`. **Todas las columnas de negocio nullables. Sin UNIQUE, sin CHECK.**
Partes duplicadas igual que arriba: `comprador_nombre` **100 %** vs `comprador_id` FK **20,6 %**;
`vendedor_id` 70,6 %. `responsable_id` 97,1 % (catálogo `ppa_responsables`).
Espejo GESCON completo (5 cols; `gescon_precio` y `gescon_cantidades_kwh` al **0 %**).
`tipo_contrato` varchar(20) DEFAULT `venta` **sin ENUM**. `es_comunidad_energetica` al **0 %** — por eso
`_es_comunidad()` siempre cae al tipo de la oferta (`app/services/comercial.py:1238-1242`).

**Es la única relación N:M contrato↔proyecto de la base**, vía `ppa_contrato_proyectos` (2 cols, PK
compuesta, ambas FK **ON DELETE CASCADE**, 42 filas).

### 7.3 Los cuatro caminos de un cliente hacia un proyecto

Un cliente puede llegar a un proyecto por **cuatro rutas independientes, sin ninguna tabla que las
reconcilie**: `proyecto_inversionistas` · `proyecto_area_contacto` · `contratos_servicio.contratante_id`
(0 % lleno) · `ppa_contratos.comprador_id` + `ppa_contrato_proyectos`.

### 7.4 Satélites y los dos dominios paralelos

| Tabla | Cols | Filas | Nota |
|---|---|---|---|
| `pagos_servicio` | 10 | — | FK CASCADE; UNIQUE `(contrato_id, mes, "año")`; CHECK mes |
| `ppa_tarifas` | 5 | — | FK CASCADE; UNIQUE `(contrato_id, "año", mes)`; CHECK mes |
| `ppa_compromisos_energia` | 7 | — | ídem + **`cantidad_proyectos` derivado guardado** |
| `cumplimiento_mensual` | 18 | — | caché de derivados; usa **`anio` sin ñ** mientras las otras usan `"año"` |
| `servicio_operacion` | 16 | **0** | 1:1; SLAs por severidad; `responsable_operacion` texto libre |
| `servicio_representacion` | 10 | **0** | 1:1; `nit_rf`, `nombre_rf` texto libre |
| `arr_proyectos` | 8 | 27 | **catálogo paralelo de proyectos, sin FK a `proyectos`** |
| `arr_arrendador` | 11 | 31 | FK a `contratos_servicio` CASCADE |
| `arr_documento` | 18 | 32 | apunta a la vez a `arr_proyecto_id`, `arr_arrendador_id` y `proyecto_id`, **los tres nullables**, y además guarda `codigo_contrato` texto NOT NULL; `pago_id` NOT NULL **sin FK** |
| `mandatos` | 18 | 31 | `proyecto` y `tercero` varchar(255) |
| `finanzas_mandatos` | 17 | **1 194** | **cero FK**; identidad = `UNIQUE(proyecto, tercero, periodo, tipo)` sobre texto libre, declarado en el docstring (`finanzas_mandatos.py:31-33`) |

---

## 8 · Fallas

**`fallas`** — 38 columnas, **6 478 filas** (`app/models/fallas.py:77`; DDL `:1978-2022`).
`codigo_interno` UNIQUE NOT NULL. **19 índices.** **0 CHECK.**
**Las 7 FK no declaran `ON DELETE`.** `proyecto_id` es **bigint NOT NULL escalar**.

### 8.1 Una falla no puede afectar a varios proyectos

Buscado en las 125 tablas: **no existe `falla_proyectos` ni equivalente**, y ningún schema de fallas
acepta `proyecto_ids`. El único punto donde una incidencia toca dos entidades es `mantenimiento_impacto`
(lleva `proyecto_id` y `falla_id` en la misma fila) y está en **0 filas**.
`alarmas_monitoreo` tampoco ayuda: identifica la planta por `proyecto_nombre` varchar(255) sin FK, y
está en **0 filas**.

### 8.2 Dos taxonomías vivas a la vez

| Vía | Columna | Llenado |
|---|---|---|
| Vieja | `tipo_id` FK → `fallas_cat_tipos` | **99,8 %** |
| Vieja, escape de texto | `tipo_libre` varchar(255) | 78,7 % |
| Nueva | `categoria_codigo` varchar(50) | 78,5 % |
| Nueva | `subtipo_codigo` varchar(80) | **13,5 %** |
| Nueva | `clasificacion` jsonb sin esquema | 78,5 % |

El comentario del modelo lo dice: *las fallas viejas dejan estos campos en NULL y siguen usando
`tipo_id`/`tipo_libre`* (`fallas.py:110-114`). Ninguna de las dos es completa.

### 8.3 Campos que el brief pide y que están vacíos

| Campo del brief | Columna | Llenado |
|---|---|---|
| Fecha de programación de solución | `fecha_programada` | **0,1 % (5 de 6 478)** |
| Energía perdida estimada | `kwh_perdidos_estimado` | **0 %** |
| (impacto económico) | `impacto_economico_cop` | **0 %** |
| Causa raíz | `causa_raiz` | 2,5 % |
| Resolución tipificada | `resolucion_id` | 15,5 % |
| Vínculo con alarma | `alarma_monitoreo_id` | **0 %**, y **sin FK** (`fallas.py:101`) |

En cambio sí se llenan: `fecha_resolucion` 95,7 %, `fotos_urls` 82,2 %, `sla_cumplido` 95,7 % (derivado).

### 8.4 Satélites

| Tabla | Cols | Filas | Nota |
|---|---|---|---|
| `fallas_seguimientos` | 6 | 1 134 | **es el historial de estado**, pero guarda solo `estado_nuevo_id`, **no el anterior** |
| `fallas_intervalos` | 6 | — | sin CHECK `fin > inicio`, sin exclusión de solapes |
| `falla_inversores` | 7 | 4 213 | ver §3.2 — la FK al inversor al **0,3 %** |
| `fallas_cat_*` (5 catálogos) | 3-7 | — | UNIQUE `codigo`; `fallas_cat_tipos.categoria_id` es **FK sin índice** |

**No hay tabla de adjuntos:** las fotos van en `fallas.fotos_urls` jsonb, y el modelo tiene que
defenderse en runtime de datos doblemente codificados (`fallas.py:198-218`).

---

## 9 · Comercial (borde del alcance)

`oportunidades` (16 cols, 105 filas) · `oportunidad_ofertas` (28 cols, 163 filas) ·
`oportunidad_oferta_proyectos` (N:M) · `oportunidad_estado_historial` (7 cols) · `oportunidad_gestiones`.

Lo que importa para el refactor:

- **La relación oferta↔proyecto está modelada dos veces a la vez**: `oportunidad_ofertas.proyecto_id`
  escalar **y** la N:M `oportunidad_oferta_proyectos`. Es coexistencia intencional y documentada
  (`app/models/comercial.py:179-183`), y `app/api/v1/comercial.py:174-181` advierte que si se
  desincronizan, el drawer y la API de integración muestran plantas distintas.
- **`oportunidad_ofertas.ppa_contrato_id` está al 0 %.** O sea que el camino `fuente_ppa == "oferta"`
  de la API congelada **nunca se ejecuta en producción**: todos los PPA se resuelven por el proyecto.
  `contrato_servicio_id` también al 0 %.
- `resultado` es **derivado de `estado`** (lo dice el comentario, `comercial.py:216-220`) y
  `seguimientos` es un **contador** de `oportunidad_gestiones` (`:237`).
- `oportunidad_estado_historial` guarda los estados como **varchar(20), no como el ENUM**.
- `oportunidades.estado_desde` + `oportunidad_ofertas.estado_desde` son lo más cercano a vigencia de estado.

---

## 10 · Rutas y dependencias del front

48 routers registrados en `app/api/v1/router.py:5-53`, prefijo global `/api/v1`, **494 decoradores de
ruta** y 466 con `Depends(get_current_user)`. `app/api/v1` son 28 448 líneas.

### 10.1 Routers del dominio central → tablas

| Router | Prefijo | Tablas que toca |
|---|---|---|
| `proyectos.py` (30 ep) | `/proyectos` | `proyectos`, `proyecto_info_tecnica`, `proyecto_inversores`, `proyecto_inversionistas`, `proyecto_area_contacto`, `proyectos_pendientes_ignorados`, `portafolios`, `clientes`, `fronteras` |
| `comercial.py` (24 ep) | `/comercial` | `oportunidades`, `oportunidad_ofertas`, `oportunidad_oferta_proyectos`, `oportunidad_estado_historial`, `oportunidad_gestiones`, `proyectos`, `proyecto_inversionistas`, `clientes`, `contactos`, `operadores_red`, `ppa_contratos`, `ppa_tarifas` |
| `fallas.py` (20 ep) | `/fallas` | `fallas`, `fallas_seguimientos`, `fallas_intervalos`, `falla_inversores`, los 5 `fallas_cat_*`, `proyectos`, `proyecto_inversionistas`, `usuarios` |
| `fronteras.py` (18 ep) | `/fronteras` | `fronteras`, `fronteras_lecturas`, `fronteras_quoia_ignoradas`, `operadores_red`, `proyectos`, `reporte_energia_generacion` |
| `clientes.py` (27 ep) | `/clientes` | `clientes`, `cliente_servicios`, `cliente_documentos_comerciales`, `cliente_tasa_servicio`, `contactos`, `proyecto_area_contacto` |
| `ppa.py` (18 ep) | `/ppa` | `ppa_contratos`, `ppa_contrato_proyectos`, `ppa_tarifas`, `ppa_compromisos_energia`, `ppa_responsables`, `ipp_mensual`, `proyectos`, `clientes`, `asic_solicitudes`, `cumplimiento_mensual` |
| `contratos_servicio.py` (12 ep) | `/contratos-servicio` | `contratos_servicio`, `pagos_servicio`, `clientes` |
| `operadores_red.py` (7 ep) | `/operadores-red` | `operadores_red`, `operadores_red_contactos`, `fronteras` |
| `inicio_operacion.py` (5 ep) | `/inicio-operacion` | `proyecto_inicio_operacion`, `proyectos`, `proyecto_inversores`, `fronteras` |
| `mantenimiento_impacto.py` (5 ep) | `/mantenimiento-impacto` | `mantenimiento_impacto`, `proyectos` |
| `portafolios.py` · `proximos_energizar.py` · `representacion.py` · `mapa.py` · `om.py` · `arriendos.py` | varios | `portafolios`, `proyectos`, `fronteras`, `contratos_servicio`, `arr_*`, `om_*` |

La periferia (`cumplimiento.py` 3 805 líneas, `liquidaciones.py`, `panel_contable.py`, `facturacion.py`,
`asic.py`, `reporte_energia.py`, `generacion_solar.py`, `registros_cnd.py`, `monitoreo.py`) lee del
dominio central sobre todo `proyectos`, `fronteras`, `ppa_*` y `contratos_servicio`.

**`mantenimientos` no tiene router.** Solo la lee `monitoreo.py`. Y `mantenimiento_impacto`, que sí
tiene router, **no se consume desde el frontend en absoluto**.

### 10.2 Cómo depende el front

> ⚠️ **Coordenadas revisadas el 2026-08-28.** El front migró a Nuxt y **cada vista vive hoy por
> duplicado**. Toda ruta `src/…` de este documento hay que leerla como `legacy/src/…`. Ver la nota
> «Los dos árboles del front» al final de §10.3.

Cliente único: `legacy/src/api/client.js:4-5` (axios, `baseURL = VITE_API_BASE_URL || '/api/v1'`);
en el árbol nuevo es `app/core/client.ts:28`, con el mismo fallback.
**No hay capa de servicios por dominio**: las vistas `.vue` llaman `api.get()` directo, así que
**cambiar la forma de una respuesta obliga a buscar archivo por archivo**, no en una capa.

Medido el 2026-08-26, sobre el árbol único de entonces: 177 vistas y 3 módulos de servicio
(`garantiasProyecciones.js`, `liquidacionesApi.js`, `xm.js`). Recontado el 2026-08-28 sobre los dos
árboles: **124 archivos en `legacy/src` y 116 en `app/`** llaman `api.*` directo, y los módulos de
servicio pasaron de 3 a 9+ (`app/features/*/services/*.ts`). Las cifras cambiaron; **la conclusión no**:
sigue sin haber una capa por la que pase un cambio de forma.

Vistas más acopladas al dominio central:

| Vista | Endpoints |
|---|---|
| `Proyectos/ProyectoDetailView.vue` | `GET/PATCH /proyectos/{id}`, `PUT /{id}/info-tecnica`, CRUD `/{id}/inversionistas`, `PATCH /{id}/servicios`, `GET /contratos-servicio`, `/clientes`, `/operadores-red`, `/fronteras` |
| `Proyectos/ProyectosListView.vue` | `GET/POST/DELETE /proyectos`, `/proyectos/pendientes` + confirmar/ignorar, `POST /proyectos/inversores/backfill-minigranja` |
| `Fallas/*` (7 componentes) + `Operaciones/GestionFallasView.vue` + `mobile/*` (8) | todo `/fallas*`, `GET /proyectos`, `GET /proyectos/{id}/inversores`, `GET /mapa` |
| `MEM/FronterasView.vue` | CRUD `/fronteras`, `/fronteras/quoia/pendientes`, `GET /operadores-red` |
| `MEM/OperadoresRedView.vue` · `OperadorRedDetailView.vue` | CRUD `/operadores-red` + contactos |
| `Clientes/*` (3) + `ContactosPanel.vue` | `/clientes/vista-comercial`, `/clientes/{id}` + `/proyectos`, `/fronteras`, `/contratos-ppa`, `/servicios-contratos`, `/panel`, contactos, documentos |
| `Contratos/*` · `Servicios/*` (6 vistas) | `/ppa*`, `/contratos-servicio*`, `/representacion`, `GET /proyectos` |
| `Comercial/*` (7) | `/comercial/*`, `GET /operadores-red`, `PUT /proyectos/{id}/info-tecnica` |

### 10.3 La API congelada no la consume el frontend

`GET /comercial/proyectos-operando` **no tiene ni un consumidor en el front**: sus 5 apariciones son
texto de ayuda y comentarios. Reverificado el 2026-08-28 **en los dos árboles**, y sigue siendo cierto
en ambos:

| Árbol | Las 5 apariciones |
|---|---|
| legacy | `legacy/src/views/Comercial/`: `catalogos.js:18`, `OfertaDrawer.vue:258`, `ProyectoDesdeCRMDialog.vue:12,36`, `RegistrarOfertaWizard.vue:226` |
| nuevo | `app/features/comercial/components/`: `catalogos.js:18`, `OfertaDrawer.vue:163`, `ProyectoDesdeCRMDialog.vue:12,31`, `RegistrarOfertaWizard.vue:140` |

Es **superficie exclusivamente externa**, consumida por otra plataforma vía `X-API-Key`
(`app/api/v1/auth.py:24-43`, tabla `api_keys` con 7 filas). Detalle completo en `05-impacto-campos-congelados.md`.

#### Los dos árboles del front — nota del 2026-08-28

El repositorio `unergy-operaciones-frontend` se migró a **Nuxt sobre Cloudflare Workers**. La carpeta
vieja no se borró: quedó dentro del mismo repositorio, en `legacy/`. Y las vistas del legacy se
**copiaron** a `app/features/…` como «páginas puente» —cada copia lo declara en su cabecera:
*«MIGRACIÓN — Fase 1. La ruta la sirve Nuxt, la vista sigue siendo la del legacy sin tocar»*—, así que
**hoy cada vista existe dos veces**.

Cómo leer las rutas de estos documentos:

| Escrito así | Dónde está hoy |
|---|---|
| `src/api/client.js` | `legacy/src/api/client.js`, y su copia `app/core/client.ts` |
| `src/views/<Área>/<X>.vue` | `legacy/src/views/<Área>/<X>.vue`, y su copia `app/features/<área>/components/<X>.vue` |
| `src/router/index.js` | `legacy/src/router/index.js`; el árbol nuevo usa rutas por archivo en `app/pages/` |
| `src/utils/security.js` | `legacy/src/utils/security.js`, y su copia `app/core/security.ts` |

Dos avisos para quien use este inventario:

1. **Los números de línea de un `.vue` solo valen para el árbol legacy.** Las copias se reformatearon al
   migrar: `RepresentacionView.vue`, por ejemplo, pasó de 1825 a 1008 líneas.
2. **Un cambio en el front hay que buscarlo en los dos sitios** mientras dure la fase puente. Verificado
   el 2026-08-28: los comportamientos que este inventario documenta siguen siendo idénticos en ambos.

---

## 11 · Antipatrones, con nombre y ubicación

### A · Texto libre donde debería haber FK

Es el antipatrón dominante de la base. Los casos donde la medición demuestra que **el texto ganó**:

| Ubicación | Evidencia de que el texto es el vínculo real |
|---|---|
| `falla_inversores.nombre` vs `.proyecto_inversor_id` | 100 % vs **0,3 %** — 4 213 filas |
| `contratos_servicio.contratante_nombre` vs `.contratante_id` | 55,4 % vs **0 %** |
| `contratos_servicio.prestador_nombre` vs `.prestador_id` | 55,4 % vs **0 %** |
| `ppa_contratos.comprador_nombre` vs `.comprador_id` | **100 %** vs 20,6 % |
| `proyectos.operador_red` vs `.operador_red_id` | 32,5 % vs 43,3 % — ambos parciales, se resuelven en cascada |
| `finanzas_mandatos` | `UNIQUE(proyecto, tercero, periodo, tipo)` **sobre texto libre**, 1 194 filas, cero FK |
| `contratos_servicio.nombre_proyecto_ref` | 40,7 % y **con índice dedicado** `ix_contratos_servicio_nombre_ref` |

Otros, sin medición que los desmienta: `fronteras` 13 agentes en texto ·
`starlink_mapeo_sitio.patron` (UNIQUE, su propósito *es* el cruce por texto) · `arr_proyectos` (catálogo
paralelo de proyectos sin FK) · `arr_documento.codigo_contrato`/`nombre_arrendatario` ·
`alarmas_monitoreo.proyecto_nombre` · `informes_guardados.sub_project` + `proyecto_nombre` ·
`mandato_inversionistas.proyectos` jsonb · `proyecto_inversionistas.contrato_ref` ·
`oportunidad_ofertas.planta_nombre` · `gestion_registros.created_by` ·
`informes_guardados.{creado,editado,aprobado,enviado}_por_nombre` (nombre copiado **además** de las 4 FK) ·
`servicio_operacion.responsable_operacion` · `servicio_representacion.nit_rf`/`nombre_rf` ·
`garantia_snapshot.clave`.

### B · Tablas anchas con columnas nullables por tipo

| Tabla | Cols | Nullables | Vacías al 100 % |
|---|---|---|---|
| `fronteras` | **101** | 94 | **29** |
| `proyectos` | 61 | — | 12 |
| `contratos_servicio` | 61 | 59 | **16** |
| `ppa_contratos` | 35 | todas las de negocio | 7 |
| `proyecto_info_tecnica` | 33 | 32 | 4 |
| `asic_solicitudes` | 33 | — | — |
| `reporte_energia_generacion` | 39 | — | — |
| `fallas` | 38 | — | 5 |

Ninguna tiene un CHECK que ate un bloque de columnas a su discriminador.

### C · Estados mutables sin historial

| Estado | Columna | Historial |
|---|---|---|
| Proyecto | `proyectos.estado` | **no existe ninguna tabla de historial de estado de proyecto** |
| Fase de obra | `proyectos.fase_construccion` | no |
| Contrato | `contratos_servicio.estado` + `.estado_pago` | no |
| Frontera | `fronteras.estado` | no |
| Mantenimiento | `mantenimientos.estado` | no |
| **% de propiedad** | `proyecto_inversionistas.porcentaje_participacion` | **no** — `setattr` + delete físico |
| Póliza | `polizas` es 1:1 con proyecto | **imposible por diseño** |
| Alarma | `alarma_estado.estado` | no — upsert por `(proyecto_id, categoria)` |
| Mandato | `mandatos.estado`, `finanzas_mandatos.estado` | no |
| **Sí lo tienen** | `fallas`→`fallas_seguimientos` (solo el estado nuevo) · `oportunidad*`→`oportunidad_estado_historial` (en varchar) · `registro_etapa`→**`registro_transicion`** (completo) | |

### D · JSON sin esquema

**58 columnas jsonb + 2 columnas `text` con JSON dentro.** Las críticas:
`proyecto_inicio_operacion` (4, catálogo definido por el frontend) ·
`proyecto_informe_om` (**12 jsonb**) · `contratos_servicio` (6) · `fallas.fotos_urls` + `.clasificacion` ·
`falla_inversores.tipos` · `proyectos.p50/p90/p99_mensual_kwh` (arrays de 12 **sin CHECK de longitud**) ·
`oportunidad_ofertas.detalle` · `mandato_inversionistas.correos`/`.proyectos` ·
`garantias_ajustes.snapshot` · `registro_parametros_93.ajustes_protecciones`.
Peor caso: **`starlink_facturas.items_json` y `.agrupado_json` son `text NOT NULL`**, no jsonb.
Deuda ya visible en runtime: `Falla.fotos_lista` maneja lista, string JSON y **doble codificación
histórica** (`fallas.py:198-218`).

### E · Datos derivados guardados como columna

| Columna | Derivada de | Fuente |
|---|---|---|
| `proyectos.gen_mensual_promedio_mwh` + 5 `gen_promedio_*` | serie de generación | caché **con razón documentada** (`proyectos.py:115-134`) |
| `proyectos.fecha_inicio_comercializacion` | primer día con generación | `proyectos.py:106-110` |
| `proyectos.srv_*` (6) | `contratos_servicio`, `servicio_*`, `ppa_contrato_proyectos` | `proyectos.py:165-171` |
| `oportunidad_ofertas.resultado` | `estado` — *"DERIVADO"* dice el comentario | `comercial.py:216-220` |
| `oportunidad_ofertas.seguimientos` | `COUNT(*)` de `oportunidad_gestiones` | `comercial.py:237` |
| `ppa_compromisos_energia.cantidad_proyectos` | `COUNT(*)` de `ppa_contrato_proyectos` | DDL `:4058` |
| `fallas.sla_cumplido` (95,7 %) | fechas vs `sla_limite_horas`; la duración ya es `@property` | `fallas.py:96,160-195` |
| `mantenimiento_impacto.lost_energy_kwh`, `.financial_impact_cop` | `expected − actual` × tarifa | tabla en 0 filas |
| `starlink_facturas.suma_items`, `starlink_factura_linea` (tabla entera) | `agrupado_json` | `starlink.py:47-49` |
| `cumplimiento_mensual` (10 cols) | generación × compromiso × precio de bolsa | caché deliberada |
| `polizas.generacion_anual_p90_kwh` | ya vive en `proyectos.p90_mensual_kwh` | tabla en 0 filas |

### F · Datos duplicados entre tablas

- **Operador de red en 3 lugares**, y el ORM resuelve el conflicto en Python: `Proyecto.operador_red_legal`
  cae a *"la primera frontera VIVA que sí lo tenga"* (`proyectos.py:234-247`).
- **Nombre del proyecto en 8 columnas**: `nombre_comercial`, `nombre_bitacora`, `nombre_clientes`,
  `nombre_comunidad`, `contratos_servicio.nombre_proyecto_ref`, `oportunidad_ofertas.planta_nombre`,
  `informes_guardados.proyecto_nombre`, `alarmas_monitoreo.proyecto_nombre`.
- **Claves de integración de la misma planta en 10 columnas** (`sub_project`, `topic_slug`,
  `topico_liquidaciones`, `project_id_solenium`, `sunfactory_project_id`, `origina_code`, `codigo_tsf`,
  3 `quoia_*`). El comentario documenta un caso real de desalineación (`proyectos.py:87-93`).
- **Potencia instalada en 4 columnas de 2 tablas**; **ubicación en 4 tablas**; **tasas fiscales en 2**;
  **`tipo_tecnologia` ENUM en `proyectos` y varchar(100) en `fronteras`**; **`nivel_tension` dos veces en
  `fronteras`** (`nivel_tension_kv` numeric y `nivel_tension` integer).
- **Mandatos modelados dos veces** (`mandatos` / `finanzas_mandatos`, la segunda declara ser independiente).
- **Proyectos de arriendo modelados dos veces** (`proyectos` / `arr_proyectos`).
- **Relación oferta↔proyecto modelada dos veces** (escalar + N:M), coexistencia intencional.

### G · FK faltantes e integridad

- **80 de 148 FK no declaran `ON DELETE`** (54 %), incluidas **25 de las 39 que apuntan a `proyectos`** y
  las **7 de `fallas`**. Sin `ON DELETE`, Postgres aplica NO ACTION y el borrado del padre falla con
  error de integridad que la API devuelve como 500. Varias cascadas viven **solo en el ORM**
  (`Cliente.contactos` en `clientes.py:70`, `Proyecto.area_contactos` en `proyectos.py:218`).
- **Solo 7 CHECK en 1 619 columnas**, y **6 son `mes BETWEEN 1 AND 12`**. El séptimo es
  `ck_inversionista_pct_rango`. **Ni un CHECK de coherencia entre columnas** (`fin > inicio`, bloque vs
  `servicio_aplica`, suma de porcentajes).
- **`*_id` sin FK:** `alarma_estado.proyecto_id` (NOT NULL), `fallas.alarma_monitoreo_id` (con **dos**
  índices y ninguna integridad), `arr_documento.pago_id` (NOT NULL y dentro del UNIQUE),
  `audit_log.usuario_id`, `panel_soporte.created_by_id`.
- **27 tablas isla** sin FK entrante ni saliente. Las de clima y mercado son legítimas (se cruzan por
  fecha); `finanzas_mandatos`, `garantia_*` y `alarma*` no.
- **Enums de dominio como varchar sin CHECK:** `contratos_servicio.estado_pago`,
  `ppa_contratos.tipo_contrato`, `cliente_tasa_servicio.servicio`,
  `mantenimiento_impacto.maintenance_type`, `proyectos.fase_construccion`, `.origen`,
  `.gen_promedio_origen`, `oportunidad_estado_historial.estado_nuevo`, `registro_etapa.estado_actual`,
  `alarma_estado.estado`, y dos booleanos disfrazados de texto: `proyecto_info_tecnica.tiene_internet`
  varchar(10) y `.tipo_tracker` varchar(10).

### H · Índices

**18 FK sin índice en su primera columna** — las que importan al dominio central:
`cliente_tasa_servicio.proyecto_id`, `fallas_cat_tipos.categoria_id`, `mantenimiento_impacto.created_by`,
`oportunidades.creado_por_usuario_id`, `oportunidad_estado_historial.usuario_id`,
`oportunidad_gestiones.usuario_id`, `panel_contable_linea.proyecto_inversionista_id`,
`clasificacion_energia_mensual.contrato_ppa_id`.
**46 pares de índices redundantes** sobre las mismas columnas, p. ej. `fronteras(proyecto_id)` =
`ix_fronteras_proyecto` + `ix_fronteras_proyecto_id`; `fallas(codigo_legado)`;
`falla_inversores(falla_id)` y `(proyecto_inversor_id)`; `oportunidad_ofertas` con 3 pares.

### I · Definición del esquema repartida en cuatro sitios

| Mecanismo | Qué hace | Riesgo |
|---|---|---|
| `Base.metadata.create_all()` en `init_db.py:123` | crea las tablas de los modelos | corre **primero** |
| `init_db.py:add_columns()` (~45 `ALTER`) | columnas nuevas, 4 `ALTER TYPE`, y un `UPDATE` de backfill | falla en silencio (`WARN column migration skipped`) |
| **`_PENDING_DDLS` en `app/main.py:12-1444`** — 1 434 líneas, el 40 % del archivo | 56 `CREATE TABLE`, 304 `ALTER`, 116 `CREATE INDEX`, 25 `ALTER TYPE ADD VALUE` y **47 `UPDATE`/`INSERT` de datos** en cada arranque | falla en silencio (`[startup ddl skipped]`) |
| `alembic upgrade head` en `start.sh:7` | 78 revisiones, **un solo head: 074** | corre **último**, y `start.sh` solo imprime `WARNING` si falla |

Consecuencias medibles: **16 tablas con dos definiciones divergentes** (modelo ORM + `CREATE TABLE` en
`_PENDING_DDLS` con menos columnas) · **12 tablas sin modelo ORM** (`alarma_estado`,
`alarmas_monitoreo`, **`api_keys`**, **`audit_log`**, 4 de clima, `email_envios`, `gmail_credenciales`,
2 de precios de bolsa) — un refactor que lea `app/models/` **no las ve** · **2 módulos de modelos fuera
de `app/models/__init__.py`** (`garantias_ajustes`, `informes`) · y **6 columnas de `proyectos` creadas
por un router en runtime** (`app/api/v1/proximos_energizar.py:40-49`).

### J · Corrección a `DEPURACION.md`: el hallazgo F1 está obsoleto

F1 afirma que Alembic no puede correr porque el historial está partido en 3 cadenas y una cuelga de la
revisión `5650ccf73b5c`, *cuyo archivo ya no existe*. **Hoy ese archivo existe**:
`alembic/versions/5650ccf73b5c_add_starlink_facturas.py:13-14`. Verificado: **un solo head (074)** y
todos los `down_revision` resuelven. Hay commits recientes de migraciones reales (`ce47639` arregla la 071).

También quedaron desactualizados `CLAUDE.md:28` ("Migraciones sin Alembic") y `backend.md:70`
("no usa Alembic en la práctica"). **El problema real no es que Alembic esté roto, es que corre último**,
después de que `create_all` y `_PENDING_DDLS` ya crearon objetos — y por eso existe
`alembic_idempotencia.py`, cuyo docstring explica que un `Duplicate*Error` hace rollback de **toda** la
cadena de migraciones (`alembic_idempotencia.py:11-27`).

Otros dos ajustes menores: `mantenimiento_impacto.falla_id` **sí tiene FK** (ON DELETE SET NULL), y
`backend.md:154` lista 6 roles cuando `RolEnum` tiene **9** (`app/models/usuarios.py:9-18`).

---

## 12 · Lo que no se puede determinar desde el código

Cinco cosas que no voy a suponer:

1. **¿Cuántas fronteras tiene cada proyecto hoy?** `uso_real.json` mide llenado, no distribución.
   `fronteras.proyecto_id` está al 100 % y hay 147 fronteras para 194 proyectos, pero eso no dice si
   alguna planta tiene dos. Bloquea la decisión de cardinalidad de `02`/`03` (queda pendiente por
   indicación tuya). Se resuelve con un `SELECT proyecto_id, count(*) FROM fronteras GROUP BY 1 HAVING count(*) > 1`.
2. **¿Qué versión de la API lee la consumidora externa?** No está nombrada en ningún archivo del
   workspace (los docs usan el placeholder). Ver `05-impacto-campos-congelados.md`.
3. **¿`potencia_instalada_kwp` al 33,5 % es un hueco de datos o de proceso?** 129 de 194 plantas sin
   potencia, y el consumidor externo la usa como campo bloqueante.
4. **¿Las 14 tablas que `DEPURACION.md` F3 reporta como posiblemente vivas siguen en producción?**
   Entre ellas hubo una tabla `equipos` y `proyecto_grupos_panel`, creadas y borradas por migraciones.
   Se resuelve con `comparar_con_prod.py`.
5. **¿`arr_proyectos` (27 filas) y `finanzas_mandatos` (1 194 filas) se pueden cruzar con `proyectos`
   por nombre sin ambigüedad?** Determina si esas relaciones se pueden normalizar sin pérdida.

---
---

# Apéndice · 2026-08-26 · Qué cambió desde que se escribió este inventario

**Lo de arriba es una foto del 2026-08-23 sobre `370b9cf`.** No se reescribe: se conserva como el
estado que motivó el diseño. Este apéndice dice qué dejó de ser cierto y por qué.
**Causa:** 86 commits entre el 23 y el 26 de agosto. La mayoría son la auditoría de integridad de
`fronteras` de Sara y la migración del Panel Contable a la API de Liquidaciones.
**Impacto de una línea:** `fronteras` dejó de ser la God Table del §4, y el §11.A perdió a varios de
sus casos porque ya se corrigieron.

## A · Cómo se midió esta actualización

⚠️ **No se pudo correr `comparar_con_prod.py`**: exige una `DATABASE_URL` de producción, y la
instrucción de esta sesión es no tocar la base ni para leer. La salida de la corrida que hizo Juan
tampoco quedó guardada en el repo (solo está el script, en `esquema-bd-produccion/`).

En su lugar se hizo una **comparación local, solo lectura**: `Base.metadata` de los modelos de hoy
contra `esquema-bd-produccion/esquema.json` (el snapshot del 2026-08-20).

**Lo que esa comparación sí ve:** la deriva entre modelos y snapshot, o sea qué cambió en el esquema
desde que se escribió el inventario.
**Lo que NO ve, y sigue pendiente:** tablas que existan en producción y el código no conozca — que
es justamente para lo que sirve `comparar_con_prod.py`. Las 14 tablas del hallazgo F3 siguen sin
confirmar.

## B · Tablas: +3 nuevas, −3 eliminadas

| Nueva | Modelo | Qué es |
|---|---|---|
| `contrato_frontera` | `app/models/contrato_frontera.py` | M2M `ContratoServicio` ↔ `Frontera` (migración 085). **Relevante al refactor:** es la primera vez que un contrato puede apuntar a un punto de medida y no a la planta entera |
| `balcttos_neto` | `app/models/garantias_proyecciones.py` | Neto real de compras en bolsa de XM por periodo. Fuera del núcleo |
| `alertas` | `app/models/alerta.py` | Alertas proactivas de vencimiento de PPA. Fuera del núcleo |

| Eliminada | Migración | Efecto en este inventario |
|---|---|---|
| `fronteras_lecturas` | 079 | Estaba en la lista de «7 tablas en 0 filas» del §7 de `04-mapeo.md`. **Ya la borraron**: un ítem menos en mi Fase 7 |
| `liquidacion_xm_datos` | 098 | No estaba en mi alcance. Borrada por muerta: 0 filas y el Panel Contable la superó |
| `gmail_credenciales` | **100 (mía)** | El hallazgo F2. Cerrado en la Fase 0 de este refactor |

Las **11 tablas sin modelo ORM** del §11.I siguen igual (`alarma_estado`, `alarmas_monitoreo`,
`api_keys`, `audit_log`, las 4 de clima, `email_envios`, las 2 de precios de bolsa). Eran 12 en el
inventario: la que salió es `gmail_credenciales`.

## C · `fronteras`: de 101 a 40 columnas — el §4 quedó obsoleto

Veinte commits entre el 24 y el 25 de agosto. **−61 columnas** respecto del snapshot. Por categoría:

| Categoría | Columnas | Migración |
|---|---|---|
| **Consolidadas en `Proyecto`** (eran duplicado real, con backfill previo) | `municipio`, `departamento`, `latitud`, `longitud`, `altitud_msnm`, `direccion`, `tipo_tecnologia`, `capacidad_transporte_mw`, `capacidad_efectiva_mw`, `potencia_maxima_declarada` | 090-095 |
| **Maquinaria de agrupación** — nunca usada | `agrupada_bajo_id`, `embebida_bajo_id`, `frontera_gemela_id` (0/145), `es_agrupadora`, `es_principal_embebido` (**145/145 en False**), y los 5 factores | 080, 097 |
| **Ficha de medidor/módem sin uso** | `ip_modem_*`, `puerto_modem_*`, `password_medidor_*`, `tipo_extraccion_*`, `canal_comunicacion_*`, `relacion_transformacion_*` | 081 |
| **Campos GESCON sin dato** | 12 columnas | 082 |
| **Códigos y clasificaciones sin consumidor** | `codigo_ciiu`, `clasificacion_industrial_*`, `clasificacion_recurso`, `codigo_sic_frontera_generacion`, `codigo_sic_frontera_usuario`, `codigo_sic_submercado_usuario`, `niu`, `codigo_propio` | 087, 089, 097 |
| **Agentes en texto libre** | `nit`, `nit_rf`, `nit_cgm`, `representante_frontera`, `representante_ddv`, `representante_anterior`, `registrada_por`, `nombre_cgm`, `nombre_recurso_generacion`, `operador_red`, `operador_red_zona` | 076, 095, 097 |
| **Ubicación redundante** | `centro_poblado`, `nombre_predio`, `predio_id`, `subestacion`, `punto_conexion` | 089, 095 |
| **Fusionadas** | `fecha_primer_registro_asic` → `fecha_registro_asic` | 088 |
| **Texto → Enum real** | `clase_ct`, `clase_pt`, `clase_medidor` | 096 |

**Qué de mi §11 dejó de aplicar:**

- «`fronteras` — 101 columnas, 94 nullables» → **40 columnas**. Sigue siendo la más ancha del núcleo
  después de `contratos_servicio`, pero ya no es un caso de God Table.
- «13 agentes en texto libre» → quedan **2** (`agente_exportador`, `agente_importador`).
- «medidor principal y de respaldo espejados en 13+12 columnas» → **9+8**, y sin credenciales.
- «`tipo_tecnologia` ENUM en `proyectos` y varchar(100) en `fronteras`» → **resuelto**: la de
  `fronteras` se eliminó.
- «`nivel_tension` dos veces» → **sigue**: `nivel_tension_kv` numeric y `nivel_tension` integer.
- «ubicación duplicada en 4 tablas» → **resuelto del lado de `fronteras`**.
- «29 columnas 100 % vacías» → la mayoría se eliminó; el conteo del §1 ya no vale.

⚠️ **Una consecuencia para el modelo objetivo:** la migración 089 eliminó `fronteras.punto_conexion`
(texto, 0 % lleno). En `02-modelo.md` propuse `red_puntos_conexion` como pieza central de D-07. Esa
propuesta **no se contradice** —la columna borrada era texto libre vacío, no una tabla— pero ahora
la topología de red no tiene ni el rastro textual del que partir. Sigue habiendo que cargarla de cero.

## D · `proyectos`: +2 / −1

| Cambio | Detalle |
|---|---|
| **+ `altitud_msnm`** | Vino de `Frontera` al consolidarse la geolocalización. Causó un **500 en toda consulta a `proyectos`** porque el modelo la declaró y el DDL de arranque se quedó atrás (commits `8c9551b`, `042bca5`) |
| **+ `project_id_solarview`** | Id en la API nueva de SolarView. **No coincide** con `project_id_solenium`. Mismo modo de falla que el anterior |
| **− `operador_red`** | El texto libre legacy. Ver §E |

**Esto valida el diagnóstico del §11.I con un incidente real de producción.** El mecanismo de
esquema repartido en cuatro sitios rompió `/proyectos` y `/ppa` el 2026-08-25, exactamente por la
razón documentada: Alembic corre último y `start.sh` se traga su fallo, así que una columna que solo
existe en una migración deja la app pidiendo algo que la base no tiene. Sara agregó
`tests/test_modelo_vs_ddl.py` como guardián. **La Fase 0 de este refactor va en esa misma dirección
y ahora tiene precedente empírico.**

## E · `proyectos.operador_red`: la condición dura de `05` §2.2 se cumplió

Yo puse como condición que esa columna **no se borrara** hasta que un backfill medido demostrara que
ninguna planta perdía su operador. Sara la borró en la migración 076 **con esa verificación hecha**:

> *"Verificado en vivo antes de este cambio: 0 filas dependían del texto libre sin también tener
> `operador_red_id` (63/63 proyectos, 100/100 fronteras con texto también tenían el FK), y
> `operador_red_zona` tenía 0 filas pobladas — no hay pérdida de datos real."*

La cascada de `_operador_red()` pasó de 4 escalones a 3, y el escalón que devolvía `null` como señal
(«el nombre no está en el catálogo») desapareció junto con su fuente. Ver el apéndice de
`05-impacto-campos-congelados.md` para el impacto en el campo expuesto.

## F · Antipatrones del §11 que se corrigieron solos

| §11 | Estado |
|---|---|
| A · texto libre donde va FK | `proyectos.operador_red` y `fronteras.operador_red` **eliminados** (076). Los demás casos siguen |
| B · tablas anchas | `fronteras` 101 → 40. `contratos_servicio` (61) y `proyectos` (62) **siguen** |
| G · FK sin `ON DELETE` | Corregido en las 4 tablas de historial de frontera (083), con criterio explícito: `RESTRICT` donde hay historial regulatorio, `CASCADE` solo en tablas de vínculo puro. **Es el criterio que mi Fase 1 paso 1.4 propone, ya aplicado en una parte** |
| G · solo 7 CHECK en 1 619 columnas | Mejorado: la 084 agregó CHECK numéricos a `fronteras` y hay un `ck_proyectos_altitud_msnm_rango` |
| I · esquema en cuatro sitios | **Sin cambio de fondo, y con dos roturas de producción para demostrarlo.** Es lo que ataca la Fase 0 |

## G · Lo que este apéndice NO revisó

Para no dar por verificado lo que no lo está:

- **Las filas.** `uso_real.json` es del 2026-08-23 y no se volvió a medir. Todos los conteos del §1
  y los porcentajes de llenado son de esa fecha. Las tablas que entonces estaban en 0 filas pueden
  no estarlo (`alertas` y `balcttos_neto` son nuevas y no se midieron nunca).
- **Las 14 tablas del hallazgo F3.** Siguen sin confirmar; hace falta `comparar_con_prod.py`.
- **El dominio de Liquidaciones / Panel Contable**, que recibió ~15 commits en estos días. Está
  fuera del alcance del refactor, pero su acople con la composición accionaria (`04-mapeo.md` §5.4)
  se decidió sobre un código que ya cambió. ⚠️ Hay que revisarlo antes de la Fase 6.

---

# Apéndice II · 2026-08-27 · El arranque escribe con la API ya sirviendo

## Antipatrón K · `_deferred_init` expone estados intermedios por la API

`_deferred_init` corre en un **hilo de fondo que arranca después de que el servidor está
atendiendo** (`app/main.py`). Sus 22 tareas se ejecutan **en secuencia**, y varias escriben sobre
las mismas tablas. Mientras esa secuencia avanza, **la API responde con lo que haya en la base en
ese instante**.

La consecuencia general, y es la que importa más allá del caso que la destapó:

> **Cualquier tarea de arranque que deje datos inconsistentes a mitad de camino los publica por la
> API.** No hay barrera, ni bandera de «arranque en curso», ni endpoint que diga «todavía no».
> Y como el hilo corre después de que el health check pasa, el balanceador ya está mandando
> tráfico.

Eso convierte una tarea lenta en una ventana de datos malos, y una pareja de tareas que se
contradicen en una ventana de datos malos **en cada deploy**.

### El caso que lo destapó

`fallas.tipo_id`, encontrado el 2026-08-27 al rotular la auditoría por tarea:

| | |
|---|---|
| Tareas en conflicto | `tipo_migration` (9ª) y `fallas_tipo_backfill` (22ª, la última) |
| Filas | **5.086** fallas |
| Frecuencia | **23 arranques en 16 horas** |
| Ventana de dato equivocado | las **13 tareas** que había entre las dos |

`tipo_migration` daba por «legacy» a todo código que no fuera numérico (`^\d+\.\d+$`), y los
**31 códigos** de la taxonomía estructurada (`red.baja_tension`) tampoco lo son: se comía el
catálogo nuevo entero y re-apuntaba las fallas a un tipo numérico de respaldo. El backfill, trece
tareas después, las devolvía. Durante la ventana, `GET /fallas?tipo_codigo=` devolvía el conjunto
equivocado y la UI mostraba el título equivocado.

⚠️ **Y solo se veía la mitad de la pelea.** `tipo_migration` escribe con
`.update(synchronize_session=False)`, un UPDATE masivo que **no pasa por los hooks del ORM y por lo
tanto no deja rastro en `audit_log`**. Es la única de las 22 tareas que escribe así. La auditoría
registró a la víctima 23 veces y nunca al culpable.

### Qué se revisó de las otras 21 tareas

Se mapeó qué columna escribe cada tarea, incluyendo las funciones a las que delegan. **Nueve
columnas tienen más de un escritor de arranque**, y ocho son inofensivas porque tocan filas
disjuntas:

| Columna | Tareas | Veredicto |
|---|---|---|
| `tipo_id` | `tipo_migration`, `fallas_tipo_backfill` | 🛑 **la pelea real** |
| `activa`, `categoria_id`, `color_hex`, `etiqueta`, `icono`, `orden` | `catalog_seed`, `estructura_fallas_seed` | Filas disjuntas: `catalog_seed` toca los códigos numéricos, y la desactivación de `estructura_fallas_seed` filtra por `codigo LIKE 'inversores.%'` |
| `estado` | `cgm_seed`, `repr_inversionista_sync` | `cgm_seed` solo lo escribe al **insertar** una fila nueva; `repr_inversionista_sync` solo lo **lee** |
| `fecha_firma_contrato` | `om_seed`, `arr_seed` | Tablas distintas: `contratos_servicio` (mantenimiento) y `arr_proyecto` |
| `proyecto_id` | `comercial_dedup`, `cgm_seed`, `arr_arrendador_id_backfill` | Tablas distintas, y las dos últimas solo rellenan cuando está en `NULL` |

### Los dos puntos ciegos que quedan

Este análisis **no puede cerrar** el caso general, y conviene no creer que sí:

1. **Las escrituras masivas no dejan rastro.** Hoy solo `tipo_migration` usa `.update()` en bloque,
   pero la próxima que lo haga volverá a ser invisible para la auditoría.
2. **Solo 10 tablas están auditadas.** `arr_*`, `oportunidades`, `panel_contable` y los catálogos
   **no lo están**, y cinco tareas de arranque escriben sobre todo ahí (`arr_seed`,
   `arr_backfill_contratos`, `arr_arrendador_backfill`, `arr_arrendador_id_backfill`,
   `arr_documento_proyecto_id_backfill`). Si alguna reescribe en cada arranque, nada lo mostraría.

### Lo que haría falta para cerrarlo de verdad

Fuera del alcance del refactor, anotado para que exista:

- Que las tareas de arranque que dejan un estado intermedio corran **dentro de una transacción**, o
  que el estado intermedio no sea observable.
- O que el health check no pase hasta que `_deferred_init` termine — tiene el costo de retrasar el
  arranque, que es justo lo que se evitó al moverlo a un hilo.
- Como mínimo: que **ninguna columna tenga dos escritores de arranque**. Es la regla más barata de
  verificar, y el mapa de arriba es reproducible.

### Tareas que salieron de este apéndice y quedaron sin hacer

**`tsf_sync`: `stats["actualizados"]` no distingue lo que cambió de lo que no.**
`app/services/tsf_sync.py:415` declara `"sin_cambios": 0` en el diccionario de estadísticas **y no
lo incrementa nunca**. Cada fila que el sync toca cuenta como `actualizados`, haya cambiado algo o
no — y como el `UPDATE` es `COALESCE(campo, :nuevo)`, la mayoría de las veces no cambia nada. Su
propio informe exagera lo que hizo, y el contador que iba a distinguirlo se declaró y se olvidó.

Arreglarlo es agregar `IS DISTINCT FROM` al `WHERE` y leer el `rowcount`, o comparar antes de
escribir. **No es urgente:** `tsf_sync` no corre en el arranque —no está en `_deferred_init` ni en
ninguno de los 12 jobs del scheduler—, se dispara a mano desde `monitoreo.py:547`. Así que no puede
estar reescribiendo en cada deploy; sólo miente sobre cuánto trabajó.

⚠️ Mientras tanto, para saber cuándo corrió y cuánto tocó **sí sirve `updated_at`**, porque su SQL
lo escribe explícitamente:

```sql
SELECT date_trunc('minute', updated_at) AS minuto, count(*) AS filas
  FROM proyectos
 WHERE updated_at > now() - interval '30 days'
 GROUP BY 1 ORDER BY 1 DESC LIMIT 40;
```

🛑 **Y una advertencia general que salió de acá:** `updated_at` **no es una auditoría de repuesto**.
Sólo se actualiza cuando el ORM hace flush (el `onupdate` de los modelos es del lado de Python) o
cuando el SQL lo escribe a mano. La base **no tiene ni un trigger**, así que las 32 escrituras de
SQL crudo modifican filas sin dejar rastro ni en `audit_log` ni en `updated_at`. `cgm_seed` es el
ejemplo: repara `contratos_servicio.proyecto_id` y no toca ninguna de las dos cosas.
