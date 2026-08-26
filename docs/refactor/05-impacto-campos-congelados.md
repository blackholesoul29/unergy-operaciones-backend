# 05 · Impacto sobre los campos congelados

**Qué es esto:** los **46 campos** que `plan-backend.md:28-69` declara contrato público, uno por uno: de
dónde salen hoy (tabla.columna o función, con archivo:línea), si el modelo nuevo los afecta, y cómo se
preserva la salida.
**Resultado:** **25 no se afectan**, **16 cambian de almacenamiento pero conservan la salida idéntica**,
**3 tienen riesgo real** y **2 de la lista ya no se sirven** (eliminados el 2026-08-19, antes de este refactor).
**Los riesgos reales son `ppa.id` y la pareja `operador_red` / `operador_red_id`.** Van en §2 y necesitan tu decisión.

---

## 1 · Antes de la tabla: cuatro campos del brief ya no se sirven

Dos están en la lista de campos congelados y dos los menciona el brief como consumidores de ellos.

Esto no lo causa el refactor. Verificado contra el código desplegado (`master` == `origin/master`):

| Campo de la lista | Estado real | Evidencia |
|---|---|---|
| `ppa.etapa_comercial` | **eliminado el 2026-08-19**, renombrado a `ppa.estado` | `app/services/comercial.py:1820-1837` (comentario explícito) · `docs/API_PPA_PIPELINE.md:65-71` |
| `ppa.estado_ppa` | **eliminado el 2026-08-19**; era función de `estado` + `id is None` | ídem |
| `estado_pipeline` (como campo de respuesta) | **nunca se sirve.** Existe como *query param* (`app/api/v1/comercial.py:523`) y como campo de `fila_operando()`, que es **código muerto**: solo lo referencian los tests | `app/services/comercial.py:567` |
| `oferta_vigente.estado` | **no se sirve.** Vive en el mismo código muerto; el equivalente vivo es `ppa.ofertas[].estado` | `:600` (muerto) vs `:1859` (vivo) |

La versión que la lista describe (`items[]`, `gen_promedio_mensual_mwh`, una fila por planta) se reemplazó
por el árbol `ppas[]` el **2026-08-18** (`docs/API_PPA_PIPELINE.md:15-18`: *«`items` ya no existe»*).
`docs/ENTREGA_API_PROYECTOS_OPERANDO.md` y su copia en `para-el-equipo/` documentan la versión vieja y
también están obsoletos.

Y dos reglas que la lista atribuye al backend **viven en el consumidor, no acá**:

- **`_resolve_municipio_id` no existe en este repositorio.** Única aparición en todo el workspace:
  `docs/plan-backend.md:67`. Es código de la otra plataforma.
- **El bloqueo por `potencia_instalada_kwp` no existe en este backend.** La columna es `nullable=True`
  (`app/models/proyectos.py:99`) y `Optional[float] = None` en los tres schemas
  (`app/schemas/proyectos.py:248,329,440`). `ProyectoDesdeCRMIn` endurece `nombre_comercial` y
  `operador_red_id`, **no la potencia** (`app/schemas/comercial.py:214-232`). El backend emite `null` sin objetar.

> **Lo que necesito de ti, y no bloquea el resto:** confirmar con la consumidora qué versión lee.
> Si lee `etapa_comercial` o `estado_ppa`, su integración lleva rota desde el 19 de agosto y eso es más
> urgente que este refactor. En el workspace no está nombrada: los docs usan el placeholder
> `<plataforma de tu compañera>` (`docs/ENTREGA_API_PROYECTOS_OPERANDO.md:3,45-46`).

---

## 2 · Los riesgos reales — necesito tu decisión

### 2.1 🛑 `ppa.id` — el valor cambia, aunque el nombre y el tipo no

| | |
|---|---|
| **Origen hoy** | `ppa_contratos.id`; `null` si es borrador — `app/services/comercial.py:1819` |
| **Uso declarado** | «dedup interno de filas y expuesto como `ppa_id`» |
| **Qué pasa con el modelo nuevo** | `ppa_contratos` se fusiona en `contratos` (decisión D-10). `contratos.id` es una secuencia nueva que unifica dos secuencias previas (`contratos_servicio.id` y `ppa_contratos.id`), así que **el id de un mismo contrato cambia de número** |

El brief dice: no renombrar, no cambiar tipo, no cambiar anidamiento, no eliminar. **Nada de eso se viola:
sigue siendo `ppa.id`, sigue siendo entero, sigue en el mismo nodo.** Pero un consumidor que **deduplica
por ese id** va a ver todas las filas como nuevas el día del cambio, y si lo guarda como clave externa,
sus referencias apuntan a otra cosa.

**Tres salidas, y la decisión es tuya:**

1. **Conservar el id de `ppa_contratos` en `contratos`** durante la fusión: los PPA entran con su id
   original y la secuencia arranca por encima del máximo. Los contratos de servicio son los que se
   remapean. Es la opción que **no toca el contrato en absoluto**, y es la que recomiendo.
2. Exponer `ppa.id` desde una columna `id_legado` que preserve el número viejo. Funciona, pero deja una
   columna de compatibilidad para siempre.
3. Cambiar el id y avisar al consumidor. Solo si él confirma que no lo persiste.

**No ejecuto la fusión de contratos sin tu respuesta a esto.**

### 2.2 🛑 `operador_red` — puede pasar a `null` en plantas donde hoy tiene valor


| | |
|---|---|
| **Origen hoy** | cascada de 4 escalones en `_operador_red()` — `app/services/comercial.py:1269-1295` |
| **Uso declarado** | **crítico**: bloquea vinculación si falta |

La cascada, en orden:

| # | Escalón | `operador_red_id` que devuelve | Llenado |
|---|---|---|---|
| 1 | `operadores_red.nombre_legal` vía `proyectos.operador_red_id` | el del proyecto | 43,3 % |
| 2 | `operadores_red.nombre_legal` vía `fronteras.operador_red_id` | el de la frontera | 94,6 % de 147 fronteras |
| 3 | nombre declarado en `oportunidad_ofertas.operador_red_id` | el de la oferta | **0 %** |
| 4 | **`proyectos.operador_red` (texto libre legacy)** | **`null`** | 32,5 % |

En `04-mapeo.md` propuse **eliminar el escalón 4**, porque es el antipatrón de texto libre que estamos
corrigiendo. **Ese borrado puede vaciar el campo crítico.** El riesgo es concreto: hay plantas cuyo único
operador conocido es ese texto, y el catálogo `operadores_red` tiene **solo 7 filas**, así que no hay
garantía de que todos los nombres del texto libre encuentren su fila.

**Condición que pongo:** `proyectos.operador_red` no se elimina hasta que un backfill medido demuestre que
todas las plantas con texto y sin `operador_red_id` quedaron resueltas contra el catálogo — y que los
nombres que no crucen se agregaron como operadores nuevos, no que se descartaron. **Mientras no se
demuestre, la columna se queda.** Va como paso verificable en `06-plan-migracion.md`.

### 2.3 Y una precisión sobre `operador_red_id`

Hoy devuelve **`null` justo cuando el nombre salió del escalón legacy** (`:1294`). Ese `null` no es un
hueco: **es la señal de que el nombre no está en el catálogo**, y la lista dice que el consumidor lo usa
para «el match de catálogo interno». Cualquier normalización tiene que **preservar ese `null` como señal**,
no rellenarlo con un id inventado. Queda dicho como invariante de la capa de salida.

---

## 3 · Los 46 campos, uno por uno

Leyenda: **=** sin cambios · **↷** cambia el almacenamiento, la salida queda idéntica · **🛑** riesgo (§2).

### 3.1 Nodo `ppa`

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `ppa.id` | `ppa_contratos.id` (null si borrador) | `services/comercial.py:1819` | **🛑** ver §2.1 |
| `ppa.etapa_comercial` | — | — | **ya no existe** (§1) |
| `ppa.estado_ppa` | — | — | **ya no existe** (§1) |
| `ppa.es_comunidad_energetica` | `ppa_contratos.es_comunidad_energetica` si no es NULL; si no, `oportunidad_ofertas.tipo == 'comunidad_energetica'`. Calculado por `_es_comunidad()` | `:1238-1242`, usado en `:1852` | **↷** la columna está al **0 %**, así que hoy **siempre** cae al tipo de la oferta. Al fusionar en `contratos` la columna no sobrevive y el cálculo pasa a depender solo de la oferta — **que es lo que ya hace en la práctica**. Salida idéntica |
| `ppa.planta_declarada` | `oportunidad_ofertas.planta_nombre` (texto libre, sin FK) | `:1848` | **=** el CRM está fuera de alcance. La columna no se toca |

### 3.2 `ppa.condiciones` — los 5 los calcula `duracion_contrato()`

Entradas: **si hay contrato** → `ppa_contratos.fecha_inicio`/`.fecha_fin`; **si es borrador** →
`oportunidad_ofertas.fecha_tentativa_inicio`/`.fecha_fin_tentativa`. Selector en `:1245-1266`.

| Campo | Cómo se calcula | archivo:línea | Impacto |
|---|---|---|---|
| `fecha_inicio` | columna directa del contrato o de la oferta | `:372`, selector `:1253`/`:1258` | **↷** pasa a `contratos.fecha_inicio`, mismo valor y tipo |
| `fecha_fin` | ídem | `:373` | **↷** ídem |
| `duracion_texto` | calculado: `"6 años y 11 meses"` desde `divmod(meses,12)` | `:351-357` | **=** función pura sobre las dos fechas |
| `meses_restantes` | calculado: si `inicio > hoy` → duración completa; si no, `meses_de_contrato(hoy, fin)` o 0 | `:360-365` | **=** función pura |
| `vigente` | calculado: `(inicio<=hoy) and (fin>=hoy)`; `null` si no hay fechas | `:366-369` | **=** función pura |

`hoy` = `col_now().date()` (UTC−5, `:93-102`). **Ninguno de los 5 se afecta más allá del remapeo de las
dos fechas de origen**, que conservan nombre, tipo y valor.

### 3.3 Cada proyecto

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `proyecto_id` | `proyectos.id` | `:1662` | **=** la PK no cambia |
| `nombre` | `proyectos.nombre_comercial` | `:1663` | **=** |
| `api_id_unergy` | `proyectos.sub_project`, vía `api_id_unergy()` que devuelve `(valor, "sub_project")` | `:1228-1235`, salida `:1664` | **↷ el más caro.** `sub_project` se mueve a `proyecto_identificacion_externa` (sistema `unergy_api`) — decisión D-13, marcada ⚠️. Requiere **vista de compatibilidad sin excepción**, porque la columna tiene UNIQUE y la lee medio backend. Si quieres bajar el riesgo, D-13 tiene una variante que deja `sub_project` en su sitio |

### 3.4 `proyecto.detalles` — generación promedio

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `energia_promedio_mensual_mwh` | cascada `_gen_promedio()`: (1) `proyectos.gen_mensual_promedio_mwh`; (2) media de `serie_mensual_kwh(p50_mensual_kwh)`/1000; (3) `oportunidad_ofertas.energia_promedio_kwh_mes`/1000 | `:382-419`, salida `:1698` | **↷** el escalón 1 pasa a `proyecto_generacion_promedio.energia_mwh_mes` y el 2 a `proyecto_simulacion`. Mismo redondeo, misma cascada |
| `energia_promedio_mensual_kwh` | calculado `round(mwh*1000, 3)` | `:1699` | **=** |
| `energia_promedio_origen` | calculado: `manual` / `medido` / `estimado` / `declarado` según el escalón | `:326-329`, `:396-417` | **↷** `proyectos.gen_promedio_origen` → `proyecto_generacion_promedio.origen`, con **CHECK que fija los 4 valores** (hoy es varchar(10) sin validar) |
| `energia_promedio_detalle.dias_con_datos` | `proyectos.gen_promedio_dias` | `:400` | **↷** → `proyecto_generacion_promedio.dias_con_datos` |
| `…ventana_desde` | `proyectos.gen_promedio_desde` | `:401` | **↷** → `.ventana_desde` |
| `…ventana_hasta` | `proyectos.gen_promedio_hasta` | `:402` | **↷** → `.ventana_hasta`, + CHECK `hasta >= desde` |
| `…actualizado_en` | `proyectos.gen_promedio_actualizado_en` | `:403` | **↷** → `.actualizado_en` |

Los 4 de `energia_promedio_detalle` salen **todos `null`** en los orígenes `estimado` y `declarado`
(`:393-394`). Ese comportamiento se conserva: son metadatos de la caché, y si el número no vino de la
caché no hay metadatos que dar.

### 3.5 `detalles.construccion`

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `fase` | `proyectos.fase_construccion` varchar(40), texto libre, 86,1 % | `:1536`, salida `:1711` | **=** **la columna se conserva por este contrato.** Iba a normalizarse a `proyectos.etapa`, pero mapear 40 caracteres de texto libre a un enum de 4 valores cambiaría el valor expuesto. Ahora convive: `etapa` es el eje normalizado nuevo, `fase_construccion` sigue alimentando este campo |
| `avance_obra_pct` | `proyectos.avance_obra_pct` numeric(5,2) | `:1537` | **=** solo gana `CHECK BETWEEN 0 AND 100` |
| `fecha_estimada_energizacion` | `proyectos.fecha_estimada_energizacion` | `:1539` | **=** |
| `origen_registro` | `proyectos.origen` (`manual` \| `tsf_sync`) — **nombre distinto en JSON y en BD** | `:1541` | **=** **la columna se conserva por este contrato**, y gana CHECK con los 2 valores |

> Estas dos columnas (`fase_construccion` y `origen`) las había eliminado del DDL por diseño y **las
> devolví al detectar que alimentan campos congelados**. Quedan con `COMMENT` que lo dice, para que nadie
> las borre sin leer esto.

### 3.6 `detalles.simulacion`

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `p50_mensual_kwh` | `proyectos.p50_mensual_kwh` JSONB, normalizado por `serie_mensual_kwh()` | `:1559-1561`; helper `app/utils/series_mensuales.py:16-40` | **↷** → 12 filas de `proyecto_simulacion`. La salida rearma el array de 12 |
| `p90_mensual_kwh` | `proyectos.p90_mensual_kwh` JSONB | `:1562` | **↷** ídem |
| `p99_mensual_kwh` | `proyectos.p99_mensual_kwh` JSONB | `:1563` | **↷** ídem |
| `p50_anual_kwh` | calculado `round(sum(p50),3)` **solo si `len(p50)==12`**, si no `null` | `:1566` | **↷** la regla pasa a `HAVING count(*) = 12`. Mismo resultado, incluido el `null` |

Nota a favor del cambio: el helper `serie_mensual_kwh()` existe porque **a veces el JSONB viene como texto
JSON** y rompió `/comercial` en producción. Con filas y CHECK de mes, ese modo de falla desaparece.
⚠️ **Condición:** la salida debe seguir devolviendo un array de 12 **aunque falten meses**, con la misma
forma que hoy produce el helper. Si una planta tiene 11 filas, el array sigue siendo de 11 y
`p50_anual_kwh` sigue siendo `null`, exactamente como hoy.

### 3.7 `detalles.clasificacion`

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `clasificacion_regulatoria` | `proyectos.clasificacion_regulatoria` (ENUM nativo) | `:1363`, salida `:1707` | **=** mismo enum, mismos 6 valores |
| `tipo_tecnologia` | `proyectos.tipo_tecnologia` (ENUM) | `:1364` | **=** |
| `tipo_proyecto` | `proyectos.tipo_proyecto` (ENUM) | `:1365` | **=** |
| `nombre_comunidad` | `proyectos.nombre_comunidad` | `:1369` | **=** se conserva aunque esté al 0 %, y ahora un CHECK la obliga cuando `es_comunidad_energetica` |

Ojo con una trampa que ya existe y que **no toco**: `clasificacion.es_comunidad_energetica` (de la planta,
`proyectos`, NOT NULL) y `ppa.es_comunidad_energetica` (del contrato, nullable) son **dos campos distintos
con el mismo nombre en niveles distintos del mismo árbol**.

### 3.8 Potencia, red, estados y fechas

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `potencia_instalada_kwp` **crítico** | `proyectos.potencia_instalada_kwp` numeric(12,3) → float | `:1668` | **↷** la columna se renombra a `potencia_dc_kwp`; **el campo de salida conserva el nombre `potencia_instalada_kwp`**. Mapeo en la capa de salida, sin excepción. ⚠️ Aparte: está al **33,5 %** — 129 de 194 plantas sin potencia, y el consumidor la usa como bloqueante. Eso es un hueco de datos que el refactor no crea ni resuelve |
| `operador_red` **crítico** | cascada de 4 escalones | `:1269-1295`, salida `:1689` | **🛑** ver §2.2 |
| `operador_red_id` **crítico** | el id del escalón que ganó; **`null` en el escalón legacy** | `:1287-1294`, salida `:1692` | **🛑** ver §2.3: el `null` es señal y se preserva |
| `estado_proyecto` | `proyectos.estado` (ENUM `estado_proyecto_enum`) | `:1646`, salida `:1666` | **=** el enum se conserva con sus 4 valores. `etapa` es una **columna nueva aparte**, no lo reemplaza |
| `estado_proyecto_label` | calculado: `ESTADO_PROYECTO_LABELS.get(estado)` — dict en memoria, no BD | dict `app/models/proyectos.py:39-44` | **=** no toca la BD |
| `fecha_inicio_comercializacion` | `proyectos.fecha_inicio_comercializacion` | `:1694` | **=** gana CHECK de orden respecto a `fecha_entrada_operacion`. ⚠️ **Verificar antes**: si hay filas donde la comercialización es anterior a la operación, el CHECK las rechaza. Hay que medirlo en la migración |
| `fecha_entrada_operacion` | `proyectos.fecha_entrada_operacion` | `:1693` | **=** |

### 3.9 `detalles.ubicacion`

| Campo | Origen hoy | archivo:línea | Impacto |
|---|---|---|---|
| `municipio` **crítico** | cascada independiente: `proyectos.municipio` → `oportunidad_ofertas.municipio` | `:1625`, salida `:1673` | **=** **no se normaliza a catálogo** (decisión D-16, ⚠️). Sigue siendo string |
| `departamento` **crítico** | cascada independiente: `proyectos.departamento` → `oportunidad_ofertas.departamento` | `:1626-1627` | **=** ídem |
| `texto` | calculado `", ".join([municipio, departamento])`, `null` si vacío | `:1628`, `:1677` | **=** |
| `latitud` / `longitud` | `proyectos.latitud`/`.longitud` numeric(9,6) | `:1678-1679` | **=** ganan CHECK de rango |
| `direccion` | `proyectos.direccion_vereda` | `:1682` | **=** |
| `url_mapa` | **`proyecto_info_tecnica.url_ubicacion`** | `:1686-1687` | **↷** `proyecto_info_tecnica` se disuelve; la columna pasa a `proyectos.url_ubicacion`. Mismo valor |

**Por qué D-16 protege este campo:** el municipio y el departamento se resuelven por **cascadas
independientes**, y el comentario del código explica el motivo: *hay filas con el departamento cargado y
el municipio en blanco, y colapsarlos en un solo campo perdería el que sí está* (`:1622-1627`). Un
`municipio_id` único no puede representar «departamento sí, municipio no». Por eso siguen siendo dos
strings, resueltos por separado, y `fuentes.municipio`/`fuentes.departamento` siguen diciendo si el valor
vino del proyecto o de la oferta. Es exactamente lo que necesita el `_resolve_municipio_id` del consumidor
para desambiguar homónimos, y `ubicacion.texto` **no sirve** para eso: es presentación.

---

## 4 · Resumen del impacto

46 campos en la lista del brief. El desglose suma exacto:

| Veredicto | N.º | Campos |
|---|---|---|
| **=** sin cambios | **25** | `planta_declarada` · `duracion_texto`, `meses_restantes`, `vigente` · `proyecto_id`, `nombre` · `energia_promedio_mensual_kwh` · los 4 de `construccion` · los 4 de `clasificacion` · `estado_proyecto`, `estado_proyecto_label` · `fecha_entrada_operacion`, `fecha_inicio_comercializacion` · `municipio`, `departamento`, `texto`, `latitud`, `longitud`, `direccion` |
| **↷** cambia el almacenamiento, salida idéntica | **16** | `es_comunidad_energetica` · `condiciones.fecha_inicio`, `condiciones.fecha_fin` · `api_id_unergy` · `energia_promedio_mensual_mwh`, `energia_promedio_origen` y los 4 de `energia_promedio_detalle` · los 4 de `simulacion` · `potencia_instalada_kwp` · `url_mapa` |
| **🛑** riesgo real, requiere tu decisión | **3** | `ppa.id` (§2.1) · `operador_red` (§2.2) · `operador_red_id` (§2.3) |
| **Ya no se sirven** | **2** | `etapa_comercial`, `estado_ppa` |

Fuera de esos 46, el brief menciona dos campos más que tampoco se sirven hoy y que no dependen de este
refactor: `estado_pipeline` (como campo de respuesta) y `oferta_vigente.estado`, ambos en código muerto (§1).

### Tres invariantes que la capa de salida debe cumplir, y que hay que probar con tests

1. **Nombres de salida congelados aunque la columna se llame distinto.** `potencia_instalada_kwp` sale con
   ese nombre aunque la columna sea `potencia_dc_kwp`; `api_id_unergy` sale de la tabla satélite;
   `construccion.origen_registro` sigue viniendo de `origen`.
2. **`operador_red_id = null` es información**, no un hueco a rellenar.
3. **Los arrays de simulación conservan su longitud real** y `p50_anual_kwh` sigue siendo `null` cuando no
   hay 12 meses.

### Un dato que juega a favor

**`GET /comercial/proyectos-operando` no lo consume el frontend propio.** Sus 5 apariciones en `src/` son
texto de ayuda y comentarios (`views/Comercial/catalogos.js:18`, `OfertaDrawer.vue:162`,
`ProyectoDesdeCRMDialog.vue:12,31`, `RegistrarOfertaWizard.vue:137`). Es superficie **exclusivamente
externa**: el riesgo está concentrado en un solo consumidor, con el que se puede hablar.

Contra eso juegan dos cosas que hay que tener presentes: **no hay staging** (auto-deploy de `master` a
Railway) y **los scopes de las API keys no se aplican** — una key marcada `["read"]` puede escribir y
borrar; el único límite real es el rol del usuario de servicio.

### Lo que el productor de esta API tiene a favor

Todo el árbol lo arma `app/services/comercial.py` (`_nodo_ppa` en `:1808`, `_nodo_proyecto` en `:1570`,
`_condiciones` en `:1849`) y **el dominio comercial está fuera del alcance del refactor**. O sea que la
capa que produce el contrato **no se reescribe**: solo cambian las fuentes de las que lee. Eso es
precisamente la separación entre almacenamiento y contrato de salida que pide el brief, y acá ya existe
por accidente arquitectónico. Conviene aprovecharla en vez de tocarla.
