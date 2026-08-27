# 04 · Mapeo viejo → nuevo

**Qué es esto:** tabla por tabla y columna crítica por columna crítica, qué se conserva, qué se fusiona,
qué se mueve y qué se elimina — con las **filas reales** de `uso_real.json` al lado, porque «eliminar»
solo es barato cuando la tabla está en cero.
**El resumen en números:** se conservan 14 tablas, se crean 15, se fusionan 4 en 1, y **se eliminan 7
tablas y 41 columnas que están al 0 % de llenado**.
**Regla que no se rompe:** ninguna fila con dato se pierde. Donde hay historia, hay destino.
**Actualizado el 2026-08-26:** hay un **apéndice al final** que reconcilia este mapeo con el estado
real del repo, y que abre un 🛑: las tres tarifas de servicio no estaban contempladas.

---

## 1 · Vista de conjunto

| Acción | Tablas | Filas afectadas |
|---|---|---|
| **Se conservan intactas** | 14 | — |
| **Se conservan, cambian de columnas** | 5 | 194 + 122 + 6 478 + 39 + 47 |
| **Se crean** | 15 | pobladas por migración o vacías |
| **Se fusionan en `contratos`** | 2 (`contratos_servicio`, `ppa_contratos`) | 177 + 34 |
| **Se disuelven en `equipos`** | 3 (`proyecto_inversores`, `proyecto_info_tecnica`, `proyecto_inicio_operacion`) | 715 + 110 + 2 |
| **Se eliminan por estar en 0 filas** | 7 | 0 |
| **Quedan fuera de alcance, sin tocar** | ~90 | — |

---

## 2 · Proyecto

### 2.1 `proyectos` — se conserva la tabla, cambian las columnas

De 61 columnas a 27. **Nada se borra sin destino**, salvo lo que está al 0 %.

| Columnas de hoy | Destino | Llenado hoy |
|---|---|---|
| `nombre_comercial`, `clasificacion_regulatoria`, `tipo_tecnologia`, `tipo_proyecto`, `estado`, `municipio`, `departamento`, `direccion_vereda`, `latitud`, `longitud`, `tipo_conexion`, `operador_red_id`, `portafolio_id`, `es_comunidad_energetica`, `nombre_comunidad`, `produccion_especifica_kwh_kwp`, `fecha_entrada_operacion`, `fecha_inicio_comercializacion`, `fecha_comercializacion_editada_manual`, `fecha_estimada_energizacion`, `avance_obra_pct`, `created_at`, `updated_at`, `deleted_at` | **se quedan** | — |
| `potencia_instalada_kwp` | **se renombra a `potencia_dc_kwp`** ⚠️ el nombre viejo sigue expuesto en la API (ver `05`) | 33,5 % |
| `p50_mensual_kwh`, `p90_mensual_kwh`, `p99_mensual_kwh` | → **`proyecto_simulacion`** (36 filas por planta) | 20,1 % |
| `gen_mensual_promedio_mwh`, `gen_promedio_origen`, `gen_promedio_dias`, `gen_promedio_desde`, `gen_promedio_hasta`, `gen_promedio_actualizado_en` | → **`proyecto_generacion_promedio`** (1:1) | 24,7 % |
| `sub_project`, `topic_slug`, `topico_liquidaciones`, `project_id_solenium`, `sunfactory_project_id`, `origina_code`, `codigo_tsf` | → **`proyecto_identificacion_externa`** (una fila por sistema) | 28–64 % |
| `fase_construccion` varchar(40) | **se queda** (contrato congelado: alimenta `construccion.fase`) **y además** se normaliza en `proyectos.etapa` + `proyecto_estado_historial` | 86,1 % |
| `origen` varchar(20) | **se queda** (contrato congelado: alimenta `construccion.origen_registro`), ahora con CHECK `manual\|tsf_sync` | — |
| `operador_red` varchar(100) (texto legacy) | → se resuelve contra `operadores_red` y **se elimina**. ⚠️ El `null` de `operador_red_id` en el escalón legacy es señal para el consumidor: ver `05` | 32,5 % |
| `srv_operacion`, `srv_representacion`, `srv_cgm`, `srv_ppa`, `srv_promotor`, `srv_rec` | **se eliminan**: derivados de `contrato_proyectos` + `contratos.tipo`. La API los sigue exponiendo, calculados | NOT NULL, siempre poblados |
| `fecha_fin_representacion` | → `contratos.fecha_fin` del contrato de representación | — |
| `nombre_bitacora`, `nombre_clientes`, `nombre_comunidad`(*), `codigo_cnd`, `carpeta_drive_codigo`, `potencia_con_cen_mw`, `quoia_reporte_generacion_id`, `quoia_reporte_consumo_id`, `quoia_nodo_id`, `tipo_conexion`(*) | **se eliminan: 0 % de llenado** | **0 %** |

(*) `nombre_comunidad` y `tipo_conexion` se conservan aunque estén al 0 %: el primero es obligado por el
CHECK de comunidad energética, el segundo lo expone la ficha técnica de la API.
`oportunidad_id` (0 %) se conserva en la tabla pero **no aparece en el DDL del núcleo**: su FK apunta a
`oportunidades`, que es del dominio comercial y queda fuera de alcance.

### 2.2 `proyecto_info_tecnica` (110 filas) — se disuelve

33 columnas, 32 nullables, y **la mitad son marcas de equipo en texto libre**. Destino columna por columna:

| Columnas de hoy | Destino |
|---|---|
| `capacidad_instalada_kwp`, `potencia_ac_kw` | → `proyectos.potencia_dc_kwp` / `.potencia_ac_kw` (unificando la duplicación de potencia) |
| `voltaje_red`, `cantidad_strings`, `tipo_conexion` | → `equipos.especificaciones` del equipo de conexión, o columna de `proyectos` |
| `marca_paneles`, `cantidad_total_paneles`, `potencia_panel_kwp` | → **una fila de `equipos`** tipo `panel` con `cantidad` y `equipo_modelo_id` |
| `marca_inversores`, `cantidad_inversores`, `potencia_inversores_kwp` | → ya existen como filas de `proyecto_inversores` → `equipos` tipo `inversor` |
| `tipo_tracker` varchar(10) | → `equipos` tipo `tracker`, `especificaciones.tipo` = 1P/2P |
| `marca_transformador`, `marca_reconectador_rele`, `marca_totalizador`, `marca_seguidor_solar`, `marca_medidores_frontera`, `marca_modem_reconectador`, `marca_modems_frontera` | → `equipos` + `equipo_modelos` + `fabricantes`. **Es la razón por la que existe el catálogo de fabricantes** |
| `ip_modem_reconectador` | → `equipos.especificaciones` del reconectador |
| `cctv_estado`, `marca_cctv` | → `equipos` tipo `camara` |
| `tiene_internet` varchar(10), `seguridad_fisica` | → `equipos` tipo `starlink` / booleano derivado |
| `tiene_almacenamiento`, `capacidad_almacenamiento_kwh`, `marca_almacenamiento`, `modelo_almacenamiento` | → `equipos` tipo nuevo `almacenamiento` (lo crea el usuario, sin migración). Las 3 últimas están al **0 %** |
| `url_ubicacion` | → **`proyectos.url_ubicacion`** (lo expone la API congelada) |
| `retie_url` | **se elimina: 0 %** |

⚠️ **Riesgo del que hay que ser consciente:** convertir «marca_paneles = Jinko» en una fila de `equipos`
con su `equipo_modelo_id` exige crear fabricantes y modelos que hoy no existen. La migración puede crear
el fabricante por nombre normalizado, pero **el modelo concreto no está en los datos**: quedará
`equipo_modelo_id` NULL y `especificaciones` con el texto original preservado. Ninguna información se
pierde; parte queda sin normalizar hasta que alguien la complete.

### 2.3 Satélites que se conservan y los que se crean

| Tabla | Filas | Acción |
|---|---|---|
| `portafolios` | 24 | **intacta** (solo `descripcion` está al 0 %, se conserva) |
| `proyecto_area_contacto` | 47 | **intacta** |
| `proyectos_pendientes_ignorados` | — | **intacta**, fuera del núcleo |
| `proyecto_identificacion_externa` | nueva | poblada desde las 7 columnas de id |
| `proyecto_simulacion` | nueva | poblada desde los 3 JSONB de las 39 plantas que los tienen |
| `proyecto_generacion_promedio` | nueva | poblada desde las 6 columnas `gen_promedio_*` de 48 plantas |
| `proyecto_estado_historial` | nueva | **arranca con una fila por planta**: estado actual, vigencia desde `created_at`, sin `hasta`. No se puede inventar el pasado que nunca se guardó, y queda dicho |

---

## 3 · Equipos

### 3.1 `proyecto_inversores` (715 filas) → `equipos`

Es la migración más limpia: cada fila se vuelve un `equipo` de tipo `inversor`.

| Columna de hoy | Destino | Nota |
|---|---|---|
| `nombre` (100 %) | `equipos.nombre` | |
| `potencia_nominal_kw` (100 %) | `equipos.especificaciones.potencia_nominal_kw` | |
| `tipo` (98,6 %) | `equipos.especificaciones.tipo` | el enum pasa al JSON Schema del tipo |
| `orden` | `equipos.nombre` conserva el orden en el texto | |
| `activo` | `equipos.estado` + `fecha_baja` | `activo = false` → `dado_de_baja` con motivo `otro` y fecha `updated_at` |
| `marca`, `modelo`, `numero_serie` | **nada que migrar: los tres al 0 %** | el hueco queda a la vista, que es el punto |

**Consecuencia honesta:** los 715 inversores llegan al modelo nuevo igual de anónimos que están hoy.
El modelo nuevo *permite* serial, garantía y mantenimiento por equipo; **no los inventa**. Llenarlos es
trabajo de operación, no de migración.

### 3.2 `proyecto_inicio_operacion` (2 filas) → se elimina

Los 4 JSONB sin esquema (`checklist` con 21 tipos de equipo, `pruebas`, `documentos`, `pendientes`) tienen
**2 filas en total**. Se exportan a un archivo antes de borrar, por si acaso, pero no hay historia que
preservar: era un prototipo. El catálogo de 21 tipos de equipo del checklist se convierte en filas de
`equipo_tipos` — **eso sí se conserva, porque es la definición del dominio**, no el dato.

### 3.3 Las tablas de mantenimiento y garantía

| Tabla | Filas | Acción |
|---|---|---|
| `mantenimientos` | **0** | **se elimina** → `equipo_mantenimientos`, que además vincula el equipo |
| `mantenimiento_impacto` | **0** | **se elimina** → `falla_impactos` (que es lo mismo, por falla y proyecto) + `equipo_mantenimientos` |
| `polizas` | **0** | **se elimina** del núcleo. Era 1:1 con proyecto, así que no podía guardar histórico. Vuelve después como `proyecto_polizas` 1:N si el negocio la necesita, con las 23 columnas revisadas |
| `starlink_facturas`, `starlink_factura_linea`, `starlink_mapeo_sitio` | 3 / — / 45 | **fuera de alcance**: son facturación, no equipo. Lo que sí entra al núcleo es el **Starlink como equipo** con sus 4 componentes |
| `garantia_snapshot`, `garantia_pagado`, `garantias_ajustes` | — | **fuera de alcance**: son garantías financieras de XM, no de equipo. Nombre engañoso, se deja dicho |

---

## 4 · Red, clientes y propiedad

### 4.1 Red

| Hoy | Nuevo |
|---|---|
| `operadores_red` (5 cols, 7 filas) | **se conserva**, gana `nit` y `activo` |
| `operadores_red_contactos` (11 filas) | **se conserva**, gana `telefono` y `UNIQUE (operador_red_id, email)` |
| — | **`red_circuitos`** (nueva, vacía) |
| — | **`red_puntos_conexion`** (nueva, vacía) |
| `fronteras.subestacion` (0 %), `.punto_conexion` (0 %), `proyectos.quoia_nodo_id` (0 %) | nada que migrar: **la topología hay que cargarla** |

### 4.2 Clientes

| Hoy | Acción |
|---|---|
| `clientes` (122 filas) | **se conserva**; gana CHECK de rango en las 4 tasas |
| `banco`, `tipo_cuenta`, `numero_cuenta`, `titular_cuenta`, `rut_url`, `reteica_pct` | **se eliminan: 0 %**. Los documentos ya viven en `cliente_documentos_comerciales` |
| `correo_liquidacion`, `correo_monitoreo`, `correo_soporte` | **se eliminan**: columnas fantasma, 0 %, el ORM ya no las declara |
| `contactos` (39 filas) | **intacta** |
| `cliente_tasa_servicio` | fuera del núcleo, pero se señala: `proyecto_id` al 0 % anula su UNIQUE, y `servicio` es varchar sin enum |
| `cliente_servicios`, `cliente_documentos_comerciales` | fuera de alcance (comercial) |
| `mandato_inversionistas` (`correos` y `proyectos` en jsonb) | fuera de alcance. **Queda señalado como el segundo padrón de inversionistas**, incompatible con el primero |

### 4.3 Propiedad — `proyecto_inversionistas` (115 filas) → `proyecto_composiciones` + líneas

Es la migración más delicada del refactor, y no porque sea grande.

| Columna de hoy | Destino |
|---|---|
| `proyecto_id` | `proyecto_composiciones.proyecto_id` |
| `cliente_id` | `proyecto_composicion_lineas.cliente_id` |
| `porcentaje_participacion` (99,1 %) | `proyecto_composicion_lineas.porcentaje` |
| `es_patrimonio_autonomo` | `proyecto_composicion_lineas.es_patrimonio_autonomo` |
| `fecha_inicio` (**36,5 %**) / `fecha_fin` (**9,6 %**) | `proyecto_composiciones.vigencia` |
| `contrato_ref` (0 %) | `proyecto_composicion_lineas.contrato_id` — nada que migrar |

**Los tres problemas, dichos sin adornos:**

1. **73 de 115 filas no tienen `fecha_inicio`.** La migración tiene que elegir un inicio, y la única
   opción defendible es `proyectos.created_at` o una fecha mínima convencional. **Eso es una suposición,
   no un dato**, y hay que marcarla como tal en la fila (`motivo = 'migracion: inicio desconocido'`).
2. **Las filas de un mismo proyecto no necesariamente suman 100.** El trigger de suma 100 % rechazaría la
   carga. La migración tiene que **medir primero** qué proyectos no suman 100 y decidir uno por uno; no se
   puede automatizar sin arriesgar datos. Es trabajo de `06-plan-migracion.md`.
3. **Agrupar filas en composiciones exige decidir qué filas son «la misma composición».** Con vigencias
   incompletas, la agrupación por proyecto es lo único posible: **una composición por proyecto**, vigente
   desde el inicio elegido y sin fin. Se pierde la (poca) información de cambios pasados que hoy hay en
   las 42 filas con `fecha_inicio`. ⚠️ Alternativa: agrupar por fecha cuando exista. Va en el plan.

---

## 5 · Contratos — la fusión

`contratos_servicio` (177 filas, 61 cols) + `ppa_contratos` (34 filas, 35 cols) → **`contratos`** +
`contrato_partes` + `contrato_proyectos`.

### 5.1 Lo que se conserva

| Hoy | Nuevo |
|---|---|
| `contratos_servicio.servicio_aplica` (8 valores) | `contratos.tipo` (5 valores). **`operacion` y `rec` del enum viejo son letra muerta**; `mantenimiento`, `arriendo` e `internet` se mapean a `mantenimiento`, `arriendo` y … ver §5.3 |
| `estado`, `numero_contrato`, `fecha_inicio`, `fecha_fin`, `tarifa_base`, `periodicidad_pago`, `indice_indexacion`, `renovacion_automatica`, `fecha_firma_contrato`, `enlace_drive` | columnas homónimas de `contratos` |
| `proyecto_id` escalar (92,1 %) | una fila en `contrato_proyectos` |
| `ppa_contrato_proyectos` (42 filas) | filas en `contrato_proyectos` |
| `contratante_nombre`/`_nit`, `prestador_nombre`/`_nit` (55,4 % / 0 %) | `contrato_partes` con rol. **Hay que resolver el nombre contra `clientes`**, porque las FK están al 0 % |
| `comprador_nombre` (100 %) / `comprador_id` (20,6 %), `vendedor_*` | `contrato_partes` con rol `comprador` / `vendedor` |
| `ppa_tarifas`, `ppa_compromisos_energia`, `cumplimiento_mensual`, `clasificacion_energia_mensual` | **intactas**, solo re-apuntan su FK a `contratos.id` |
| `pagos_servicio` | **intacta**, re-apunta FK |

### 5.2 Lo que se elimina por estar vacío

De `contratos_servicio`: `rec_cantidad`, `rec_precio_unitario`, `rec_vintage` (bloque REC entero al 0 %),
`promotor_tarifa`, `promotor_condiciones` (bloque promotor entero al 0 %), `cgm_porcentaje_fncer`,
`cgm_tipo_asignacion`, `canones_otros`, `fecha_indexacion`, `facturas_solenium`, `velocidad_mbps`,
`wifi_password`, `renovacion_automatica`(0 % pero se conserva la columna en `contratos`).
De `ppa_contratos`: `cantidad_maxima_kwh_mes`, `condiciones_pago`, `gescon_precio`,
`gescon_cantidades_kwh`, `es_comunidad_energetica` — **los 5 al 0 %**.

Y las denormalizaciones: `inversionista_nombre` (62,1 %), `portafolio`, `codigo_sun_factory`,
`nombre_proyecto_ref` (40,7 %) — se resuelven contra las tablas reales y se eliminan.
⚠️ `nombre_proyecto_ref` **tiene índice dedicado**, o sea que algo lo usa para cruzar. Antes de borrarla
hay que encontrar qué.

### 5.3 Dos cosas que la fusión no resuelve sola

- **El bloque internet/Starlink (13 columnas) no es un contrato de servicio, es un equipo.**
  `plan_datos_gb`, `id_router`, `numero_kit`, `latencia_ms`, `wifi_seguridad`, `ubicacion_lat/lng` →
  `equipos.especificaciones` del Starlink. Lo que sí es contrato (`tarifa_mensual`, fechas) se queda.
  Por eso `internet` no aparece en `contrato_tipo_enum`: se representa como contrato de `mantenimiento`
  o `operacion` según el caso, y el equipo lleva la telemetría. ⚠️ Confírmame si preferís un tipo
  `internet` propio en el enum.
- **`cliente_tasa_servicio.servicio` y `contratos_servicio.servicio_aplica` no son el mismo vocabulario.**
  Hay que conciliarlos en la migración o las tasas dejan de encontrar su contrato.

### 5.4 Lo que la fusión condiciona en Liquidaciones (fuera de alcance)

El brief pide señalarlo. Tres decisiones de hoy que Liquidaciones va a heredar:

1. **La composición accionaria versionada es la que habilita liquidar un periodo pasado correctamente.**
   Hoy `panel_contable_linea.proyecto_inversionista_id` y `liquidacion_facturas.proyecto_inversionista_id`
   apuntan a una fila que se sobrescribe. Al migrar, esas FK tienen que apuntar a
   `proyecto_composicion_lineas`, y la línea correcta depende del periodo que se liquida.
   **Es el punto de acople más importante y hay que hacerlo antes de tocar Liquidaciones.**
2. **`contratos.id` unifica dos secuencias de id** (`contratos_servicio.id` y `ppa_contratos.id`). Todo lo
   que hoy guarde un id de contrato tiene que remapearse, no reinterpretarse.
3. **`contrato_partes` reemplaza `contratante_id`/`prestador_id`**, así que «a quién se le factura» pasa de
   ser una columna a ser una consulta por rol.

---

## 6 · Fallas

| Hoy | Filas | Nuevo |
|---|---|---|
| `fallas` | 6 478 | **se conserva**; pierde `proyecto_id`, `sla_cumplido`, `fotos_urls`, `kwh_perdidos_estimado`, `impacto_economico_cop`, `clasificacion`; gana `origen` y `punto_conexion_id` |
| `fallas.proyecto_id` (NOT NULL, escalar) | 6 478 | → **una fila en `falla_proyectos`** por cada falla. Migración mecánica, sin pérdida |
| `falla_inversores` | 4 213 | → **`falla_equipos`**. ⚠️ **Solo 11 filas tienen `proyecto_inversor_id`.** Las otras 4 202 hay que resolverlas por `nombre` + `proyecto_id`, y lo que no cruce **no se puede migrar a una FK**: va a `falla_equipos.detalle` con el texto original preservado. **Esto hay que medirlo antes, no después** |
| `fallas_seguimientos` | 1 134 | → **`falla_estado_historial`**. `estado_nuevo_id` se conserva; `estado_anterior_id` queda NULL en las 1 134 filas históricas, porque nunca se guardó |
| `fallas.fotos_urls` jsonb | 82,2 % de 6 478 | → **`falla_adjuntos`**, una fila por URL. Hay que manejar los tres formatos legados (lista, string JSON, doble codificación) |
| `fallas_intervalos` | — | **se conserva**, gana CHECK `fin > inicio` |
| `fallas_cat_*` (5) | — | **intactas**; solo se agrega índice a `fallas_cat_tipos.categoria_id` |
| `fallas.tipo_id` (99,8 %) + `tipo_libre` (78,7 %) + `categoria_codigo` (78,5 %) + `subtipo_codigo` (13,5 %) | | ⚠️ **No se unifican en esta fase.** Dos taxonomías vivas, ninguna completa: unificarlas es una decisión de dominio que necesita a Laura, no un mapeo. Se conservan las cuatro y se deja señalado |
| `fallas.alarma_monitoreo_id` (0 %, sin FK) | 0 | **se elimina** junto con `alarmas_monitoreo` (0 filas) |
| `mantenimiento_impacto` | **0** | → `falla_impactos` (nombres en español, y por proyecto) |

---

## 7 · Resumen de eliminaciones

**7 tablas, todas en 0 filas:** `mantenimientos`, `mantenimiento_impacto`, `polizas`, `servicio_operacion`,
`servicio_representacion`, `alarmas_monitoreo`, `fronteras_lecturas`.
Más `proyecto_inicio_operacion` (2 filas, exportadas antes de borrar).

**41 columnas al 0 % de llenado** en las tablas del núcleo: 10 de `proyectos`, 4 de `proyecto_info_tecnica`,
3 de `proyecto_inversores`, 1 de `proyecto_inversionistas`, 9 de `clientes`, 9 de `contratos_servicio`,
5 de `ppa_contratos`.

**Ninguna eliminación de tabla con filas.** Las 4 tablas con datos que desaparecen como tal
(`proyecto_inversores`, `proyecto_info_tecnica`, `contratos_servicio`, `ppa_contratos`) tienen destino
fila por fila en las secciones de arriba.

### 7.1 ⚠️ Verificación obligatoria antes de cualquier `DROP` o `CREATE`

El hallazgo F3 de `DEPURACION.md` dice que puede haber **14 tablas vivas en producción que el código no
conoce**, y entre ellas hubo una tabla `equipos` y una `proyecto_grupos_panel`, creadas y borradas por
migraciones que no se sabe si se aplicaron. **`equipos` es justo el nombre que elige el DDL nuevo.**

Lo que la medición **sí** permite afirmar: `medir_uso_real.py` intersecta el esquema conocido con las
tablas reales de la BD (`set(esperado) & reales`, línea 76) y midió **125 de 125**, así que las 125 tablas
del esquema existen en producción. Ninguno de los 22 nombres nuevos del DDL está entre ellas.

Lo que **no** permite afirmar: si producción tiene tablas **de más**. La medición solo mira la
intersección, no enumera lo que sobra. Así que sigue pendiente correr
`python comparar_con_prod.py "<DATABASE_URL>"`, que es justamente lo que lista lo que hay en prod y no
está en el esquema. **Si aparece una tabla `equipos`, hay que decidir entre borrarla (si está en 0 filas)
o renombrar la del modelo nuevo.** No se ejecuta ni un `CREATE TABLE equipos` antes de esa respuesta.

---
---

# Apéndice · 2026-08-26 · Reconciliación con el estado real

**Qué es esto:** qué filas del mapeo de arriba dejaron de aplicar tras los 86 commits del 23 al 26
de agosto, y **un hueco propio que hay que tapar antes de la Fase 6**.
**Lo más importante:** las tres tarifas de servicio no estaban contempladas en ninguna parte del
mapeo, y se perderían en la fusión de contratos.
**Método:** comparación local `Base.metadata` vs. `esquema.json` (snapshot 2026-08-20). No se tocó la
base de datos. Ver `00-inventario-actual.md` §A del apéndice para lo que esa comparación no puede ver.

## A · 🛑 Las tres tarifas de servicio — hueco del mapeo

Juan preguntó si `tarifa_administracion`, `tarifa_cgm` y `tarifa_representacion` quedan cubiertas en
`proyecto_composicion` o se pierden. La respuesta corta: **no estaban contempladas en ningún lado**.

**Precisión de ubicación primero.** No están en `proyecto_inversionistas` — esa tabla tiene 10
columnas y ninguna es de tarifa, verificado en el modelo de hoy y en el DDL de producción del
2026-08-20. Viven en **`contratos_servicio`** (`app/models/contratos.py:115-117`):

| Columna | Tipo |
|---|---|
| `tarifa_admin` | `Numeric(8,4)` |
| `tarifa_cgm` | `Numeric(10,6)` |
| `tarifa_representacion` | `Numeric(10,6)` |

**Y el hueco:** la tabla `contratos` de `03-esquema.sql` tiene **solo `tarifa_base`**. El §5.1 de este
documento lista lo que se conserva de `contratos_servicio` y **las tres tarifas no aparecen**; el §5.2
lista lo que se elimina por vacío y **tampoco aparecen ahí**. Quedaron fuera de las dos listas, que es
la peor forma de perder una columna: sin decisión.

**No están vacías ni muertas.** El 2026-08-25 se insertaron contratos de representación usando las
tres — Cedillanos al 5 % de administración sin representación ni CGM, Sabana de Torres al 3,8 % con
6 y 6 — y hay lógica de negocio leyéndolas (`4024c1c Costos del panel: elegir el contrato de
representacion por regla, no por id`).

✅ **RESUELTO el 2026-08-26 (D-24).** Van a `contrato_tarifas`, y **versionada**: la investigación
mostró que las tarifas no solo pueden cambiar, cambian todos los años por indexación. El detalle del
mapeo está en el **§F** de este mismo documento, y la decisión con su evidencia en `01-decisiones.md`
D-24. **La Fase 6 sigue esperando implementación**, pero ya no por falta de decisión.

### Y una pregunta que esto abre

`cliente_tasa_servicio` tiene sus propias 4 tasas (`iva_pct`, `retencion_pct`, `reteica_pct`,
`reteiva_pct`), y `clientes` las tiene otra vez. Ya estaba señalado en el §4.2 y en el §5.3 que hay
que conciliar vocabularios. Con las tres tarifas de `contratos_servicio` sobre la mesa, el mapa
completo de «cuánto se cobra» está repartido en **tres tablas** y ninguna manda. ⚠️ Eso es una
decisión de dominio, no de mapeo.

## B · Filas del mapeo que ya no aplican

### §2.1 · `proyectos`

| Lo que decía | Estado real |
|---|---|
| `operador_red` varchar(100) → «se resuelve contra el catálogo y **se elimina**» | **Ya se eliminó** (migración 076), y con la verificación que yo exigía. Ver `05` apéndice |
| — | **Dos columnas nuevas** que el mapeo no contempla: `altitud_msnm` y `project_id_solarview`. La segunda es una **11.ª clave de integración externa**: entra en el alcance de D-13 |

### §2.2 · `proyecto_info_tecnica`

Sigue existiendo con sus 33 columnas y el mapeo sigue siendo válido, **con una salvedad**: varias
columnas `marca_*` que iban a convertirse en equipos apuntaban a fronteras que ya no existen
(`marca_medidores_frontera`, `marca_modems_frontera`). El destino no cambia —siguen siendo equipos—
pero el dato de contexto que las acompañaba en `fronteras` se fue.

### §3 y §7 · Tablas a eliminar

| Tabla | Lo que decía el mapeo | Estado real |
|---|---|---|
| `fronteras_lecturas` | eliminar por 0 filas (Fase 7) | **ya eliminada** (079). Un ítem menos |
| `alarmas_monitoreo` | eliminar por 0 filas (Fase 7) | 🛑 **NO se puede eliminar. El mapeo estaba equivocado.** Ver §E |
| `mantenimientos`, `mantenimiento_impacto`, `polizas`, `servicio_operacion`, `servicio_representacion` | eliminar por 0 filas | **siguen existiendo**. El mapeo sigue válido |
| `proyecto_inicio_operacion` | eliminar (2 filas), exportando antes | **sigue existiendo**. Válido |
| `liquidacion_xm_datos` | fuera de alcance, no mencionada | **eliminada** (098). No afecta al mapeo |

### §5 · La fusión de contratos

Dos cambios que el mapeo tiene que absorber:

1. **`contrato_frontera` es nueva** (migración 085): M2M `ContratoServicio` ↔ `Frontera`. El §5.1
   mapea `contratos_servicio.proyecto_id` → una fila en `contrato_proyectos`, pero **ahora hay un
   segundo vínculo**, más fino: contrato → punto de medida. ⚠️ El modelo objetivo no tiene
   equivalente. Habría que agregar `contrato_frontera` al DDL — pero eso depende de D-06, que sigue
   sin decidirse, porque la tabla apunta a `fronteras`.
2. **`liquidacion_xm_datos` sale de la lista de satélites** a re-apuntar en el paso 6.5: ya no existe.

## C · Lo que el mapeo acertó y ya se confirmó en producción

Vale registrarlo, porque son decisiones que otra sesión tomó igual por su cuenta:

| Propuesta del mapeo | Qué pasó |
|---|---|
| Consolidar la ubicación duplicada entre `fronteras` y `proyectos` | Hecho, migraciones 091-095, con backfill previo en cada una |
| Eliminar `operador_red` texto libre dejando solo el FK | Hecho, migración 076 |
| Eliminar las columnas 100 % vacías de `fronteras` | Hecho, migraciones 081, 082, 089, 097 |
| Unificar la potencia duplicada en 4 columnas de 2 tablas | Hecho en la parte de `fronteras` (090): `Proyecto.potencia_instalada_kwp` queda como fuente única |
| `ON DELETE` explícito con criterio por tipo de hijo | Hecho en las 4 tablas de historial de frontera (083), con el mismo criterio que propone la Fase 1 paso 1.4 |
| Texto libre de enums → Enum real | Hecho en `clase_ct`, `clase_pt`, `clase_medidor` (096) |

Esto es señal de que el mapeo apunta donde el equipo ya está apuntando. También significa que
**cada día que pasa, más de la Fase 7 ya está hecha por otra vía** — y que el mapeo hay que releerlo
antes de ejecutarlo, no después.

## D · Corrección de conteos del §7

| Lo que decía | Valor correcto al 2026-08-26 |
|---|---|
| «7 tablas en 0 filas a eliminar» | **5**: `fronteras_lecturas` y `alarmas_monitoreo` ya no están |
| «41 columnas al 0 % en el núcleo» | Sin recontar. Las de `fronteras` se eliminaron; las de `proyectos`, `clientes`, `contratos_servicio` y `ppa_contratos` siguen. ⚠️ Habría que volver a correr `medir_uso_real.py` para dar un número, y eso exige la base |

## E · 🛑 Corrección: `alarmas_monitoreo` NO se puede eliminar

El §7 la listaba entre las «7 tablas en 0 filas» a eliminar en la Fase 7, apoyándose en que
`uso_real.json` le midió **0 filas** el 2026-08-23. **Ese razonamiento era incorrecto**, y verificarlo
hoy lo dejó claro:

| Evidencia | Dónde |
|---|---|
| El scheduler le hace **INSERT** | `app/services/mgs/scheduler.py:111` |
| El dashboard la **lee** en cada carga | `app/api/v1/dashboard.py:77` y `:82` |
| No tiene modelo ORM, solo `CREATE TABLE` en `_PENDING_DDLS` | por eso no aparece en la comparación de modelos |

**Por qué me equivoqué:** confundí «0 filas ahora» con «tabla muerta». Es una tabla de **estado
transitorio** — el detector de desconexión crea alarmas cada 15 minutos y se resuelven; que esté
vacía en el instante de la medición es lo normal cuando no hay ninguna alarma activa, no evidencia de
abandono. La lección aplica a toda la lista del §7: **0 filas es condición necesaria, no suficiente.**
Antes de cualquier `DROP` hay que comprobar que nadie escriba, y para las 11 tablas sin modelo ORM eso
no se puede ver leyendo `app/models/`.

**Qué hay que revisar en las otras 4 candidatas** (`mantenimientos`, `mantenimiento_impacto`,
`polizas`, `servicio_operacion`, `servicio_representacion`): las cinco sí tienen modelo ORM, así que
son visibles a un grep, pero **la Fase 7 debe verificar escrituras con la misma pregunta**, no solo el
conteo de filas.

⚠️ Y queda un pendiente heredado del diagnóstico de agosto: el detector sigue creando alarmas y **ya no
hay UI web para resolverlas** (la vista `/alertas/monitoreo` se retiró). Eso no lo decide este refactor,
pero explica por qué la tabla puede acumular filas que nadie cierra.

---

## F · 2026-08-26 · `contrato_tarifas`: el hueco del §A, cerrado

El §A dejó las tres tarifas de servicio como 🛑 sin destino. **Ya lo tienen**: la tabla
`contrato_tarifas` del `03-esquema.sql`. Y la investigación que pidió Juan cambió el diseño — no es una
tabla de tres columnas, es una tabla **versionada**.

### Qué se migra, y de dónde

| Origen en `contratos_servicio` | Destino | Concepto | Unidad |
|---|---|---|---|
| `tarifa_admin` (`Numeric(8,4)`) | `contrato_tarifas` | `administracion` | **`porcentaje`** |
| `tarifa_cgm` (`Numeric(10,6)`) | ídem | `cgm` | `cop_kwh` |
| `tarifa_representacion` (`Numeric(10,6)`) | ídem | `representacion` | `cop_kwh` |
| `tarifa_base`, `tarifa_mensual` | ídem | `canon` | `cop_mes` |
| **`indexacion_cgm`** (JSONB) | **una fila por año** | `cgm` | `cop_kwh` |
| **`indexacion_representacion`** (JSONB) | ídem | `representacion` | `cop_kwh` |
| **`indexacion_anual`** / **`indexacion_mensual`** (JSONB) | ídem | `canon` | `cop_mes` |
| `ppa_tarifas` (tabla, `(contrato_id, año, mes) → tarifa`) | ídem | `energia` | `cop_kwh` |
| `indice_indexacion`, `fecha_indexacion` | `contrato_tarifas.indice` + la `vigencia` de cada fila | | |

**Las columnas escalares desaparecen.** Hoy `tarifa_cgm` guarda el valor **base** y el JSONB guarda la
serie indexada — se comprueba en el seed: `tarifa_cgm=5.0` junto a una serie cuyo primer elemento es
`{"año": 2024, "valor": 5.0, "esBase": true}`. En el modelo nuevo la base es simplemente la fila con
`es_base = TRUE`, y no hay dos sitios que puedan discrepar.

### Cómo se migra cada JSONB

Cada elemento `{"año": Y, "ipc": P, "valor": V, "esBase": B}` se vuelve una fila:

```
vigencia   = [Y-01-01, (Y+1)-01-01)   -- acotada por fecha_inicio/fecha_fin del contrato
valor      = V
es_base    = B
indice     = 'IPC'  (o el de indice_indexacion)
indice_pct = P
```

### El orden real de la migración, tras confirmarse la hipótesis B (2026-08-26)

Ya no es «copiar el escalar y desplegar el JSONB». Son **tres pasos, en este orden**:

⚠️ **Corregido el 2026-08-27:** este cuadro tenía un paso 1 que extraía de `audit_log` los cambios de
tarifa desde el 2026-05-19. **Se corrió la consulta contra producción y no hay nada que extraer**
(D-24 § e): 25 filas, todas de un solo día, 22 de ellas diffs fantasma y las 3 restantes primeros
llenados. El paso se borró y la numeración se corrió.

| # | Paso | Fuente | Resultado |
|---|---|---|---|
| 1 | **Desplegar los JSONB** `indexacion_*` | las 4 columnas | filas con vigencia anual, `origen = 'indexacion'` |
| 2 | **Desplegar `ppa_tarifas`** | la tabla | filas mensuales, `concepto = 'energia'` |
| 3 | **Rellenar el hueco inicial** con el escalar de hoy | `tarifa_*` | **una fila `origen = 'migracion'`** con `nota` obligatoria |

El paso 3 solo cubre lo que los pasos 1-2 no alcanzaron: el tramo entre el inicio del contrato y el
primer cambio conocido. Como no hay ningún cambio recuperable, en la práctica **queda abierta hasta hoy**
en todos los contratos que no tengan serie de indexación.

⚠️ **Y no se migra ningún `0.0`.** Un cero en `tarifa_admin`, `tarifa_cgm` o `tarifa_representacion` es un
relleno pendiente, no un precio (D-24 § e). Esas filas se omiten. Regla completa en
`06-plan-migracion.md` Fase 6.

**El inicio de la fila migrada**, en cascada: `fecha_inicio` (18,6 %) → `fecha_firma_contrato` (73,4 %)
→ y si no hay ninguna, `daterange(NULL, ...)` abierta hacia atrás. Unos **47 de 177 contratos** caen en el
tercer caso. La apertura hacia atrás no es un problema **porque está etiquetada**: `origen = 'migracion'`
tiene índice parcial propio y una liquidación puede detectar que su tarifa no tiene fecha confirmada.

⚠️ **Tres cosas que la migración tiene que medir antes, no después:**

1. **Series con años solapados o repetidos** — el `EXCLUDE` las rechaza. Hay que listarlas primero.
2. **Series que empiezan antes de `fecha_inicio` del contrato**, o que siguen después de `fecha_fin`.
   La vigencia se acota al contrato, y si eso deja una fila vacía es un dato a revisar, no a descartar.
3. **Contratos con escalar pero sin serie** (Cedillanos y Sabana de Torres, cargados el 2026-08-25):
   se migran como una única fila con `es_base = TRUE` y `vigencia` abierta.

### Lo que NO se migra acá

`om_ipc_tasas`, `arr_ipc_tasas` e `ipp_mensual` son **catálogos de tasas** —el IPC de cada año, el IPP de
cada mes—, no tarifas de un contrato. Se quedan donde están, fuera del núcleo. `contrato_tarifas.indice`
apunta a cuál se usó; el valor del índice se busca en ellos.

### ✅ `tarifa_admin`: resuelto el 2026-08-26 — se renegocia

`tarifa_admin` era la única sin serie de indexación, y eso abría dos hipótesis. **Juan confirmó con el
negocio: todas las tarifas se renegocian, incluida administración.** No se indexa por IPC — se acuerda
entre las partes — pero cambia, y ese histórico **se está perdiendo hoy** cada vez que alguien edita el
campo.

Consecuencia para este mapeo: `tarifa_admin` migra **igual que las demás**, con `origen =
'renegociacion'` en vez de `'indexacion'`. Lo que la diferencia es que **no tiene JSONB del que sacar
historia**: su único pasado recuperable está en `audit_log`, desde el 2026-05-19.

**Lo anterior a esa fecha es irrecuperable** salvo abriendo a mano las actas de `enlace_drive` (70,1 % de
los contratos lo tienen). El detalle completo de qué se recupera y qué no está en `01-decisiones.md`
D-24 § c.
