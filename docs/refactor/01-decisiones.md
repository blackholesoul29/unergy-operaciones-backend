# 01 · Decisiones de diseño

**Qué es esto:** cada decisión del modelo objetivo con las opciones que consideré, la que elegí y el
trade-off que acepté. Las marcadas **⚠️** son las que no tengo cerradas o donde el trade-off es discutible.
**Criterio general:** lo que ya funciona no se toca. Cuatro decisiones grandes cambian respecto del plan
inicial, y una queda **abierta a tu confirmación** (D-06, frontera).
**Cómo leerlo:** las ⚠️ primero — son D-01, D-03, D-04, D-06, D-09, D-11, D-13, D-16.
**Actualizado el 2026-08-26:** hay **dos apéndices al final**. El primero cierra D-06 (frontera) y
corrige un hueco de D-10 (las tres tarifas de servicio). El segundo trae **D-21 a D-23**: la caché
sincronizada de `estado`/`etapa`, los documentos como entidad con arco exclusivo, y la coherencia
entre `operador_red_id` y `punto_conexion_id`. Lo de abajo se conserva tal como se escribió el
2026-08-23.

---

## Índice de decisiones

| # | Decisión | ⚠️ |
|---|---|---|
| D-01 | Especificaciones heterogéneas de equipo: JSONB con esquema declarado por tipo | ⚠️ |
| D-02 | Registro individual vs. por cantidad: una tabla con `cantidad` y granularidad impuesta por el tipo | |
| D-03 | Equipos compuestos: autorreferencia `parent_equipo_id` | ⚠️ |
| D-04 | Garantía y mantenimiento: columna generada para garantía, vista para mantenimiento | ⚠️ |
| D-05 | Reemplazo de equipo: se conserva el que sale | |
| D-06 | **Frontera: PENDIENTE de tu confirmación** | ⚠️ |
| D-07 | Red como jerarquía operador → circuito → punto de conexión | |
| D-08 | Propiedad: cabecera de composición versionada + líneas | |
| D-09 | Suma 100 %: constraint trigger diferido | ⚠️ |
| D-10 | Contratos: una tabla + `contrato_parte` + `contrato_proyecto` | |
| D-11 | Fallas: **no se renombra a `incidente`**, se amplía | ⚠️ |
| D-12 | Generación promedio: caché 1:1 fuera de `proyectos` |  |
| D-13 | Claves de integración externa a tabla satélite | ⚠️ |
| D-14 | Simulación P50/P90/P99: de 3 JSONB a filas | |
| D-15 | Enums nativos de Postgres, catálogos como tabla | |
| D-16 | Ubicación: NO se normaliza a catálogo DIVIPOLA | ⚠️ |
| D-17 | RLS: descartada | |
| D-18 | Se conservan intactos los catálogos de fallas y `registro_*` | |
| D-19 | Alcance del DDL: núcleo ejecutable, periferia solo referenciada | |
| D-20 | «Si tiene tracker» y «tipo de subestación» NO son columnas de proyecto | ⚠️ |

---

## Equipos

### D-01 ⚠️ · Especificaciones heterogéneas sin tabla ancha ni EAV

Un panel tiene referencia y potencia; un inversor tiene serial y tipo de string; un tracker tiene 1P/2P.
Tres formas de resolverlo:

| Opción | Por qué no / sí |
|---|---|
| Tabla ancha con todas las columnas de todos los tipos | Es exactamente `fronteras` (101 columnas, 29 vacías) y `contratos_servicio` (61, 16 vacías). Descartada por evidencia propia. |
| EAV (`equipo_atributo(equipo_id, clave, valor)`) | Prohibida por el brief, y con razón: pierde tipos, no se puede indexar ni validar. |
| **Elegida: JSONB `especificaciones` + JSON Schema declarado en `equipo_tipo`** | Cada tipo de equipo trae su propio contrato de forma en `equipo_tipo.esquema_especificaciones`, y el borde de la API valida contra él. |

**El punto fino:** el brief prohíbe «JSON sin esquema». Esto **no es JSON sin esquema** — es JSON con el
esquema guardado en la fila del tipo, que es lo que permite que el usuario cree tipos nuevos sin migración.
Es la única opción de las tres que cumple las dos exigencias a la vez.

**Trade-off aceptado:** Postgres no valida el JSON Schema; lo valida la aplicación. Se mitiga con un
CHECK de que `especificaciones` sea un objeto y con la validación obligatoria en el schema Pydantic.
⚠️ **Por qué la marco:** si mañana alguien escribe directo en la BD (un `*_seed`, un script), el esquema
no lo detiene. Si prefieres garantía en base, la alternativa es una tabla por tipo base y JSONB solo para
los tipos que cree el usuario — más seguro, pero rompe la uniformidad de las consultas.

### D-02 · Registro individual vs. por cantidad

Los inversores y las cámaras van uno por uno; los paneles van por cantidad.

**Elegida:** una sola tabla `equipo` con `cantidad integer NOT NULL DEFAULT 1`, y
`equipo_tipo.granularidad` (`individual` | `cantidad`) que dice cuál se permite. Dos CHECK lo imponen:
`cantidad >= 1`, y `numero_serie` solo puede existir si `cantidad = 1`.

Descartada la alternativa de dos tablas paralelas (`equipo` / `equipo_lote`): duplica cada consulta,
cada FK y cada join con fallas, para ahorrar una columna.

**Trade-off:** una fila de paneles con `cantidad = 480` no permite dar de baja un panel suelto. Es
deliberado: ya decidiste que los paneles no se registran unidad por unidad. Si algún día hace falta,
se parte la fila sin cambiar el esquema.

### D-03 ⚠️ · Equipos compuestos (Starlink, subestación)

Un Starlink tiene antena, fuente, módem y cableado, **y cada componente puede fallar por separado**.

**Elegida:** `equipo.parent_equipo_id` autorreferencial. El componente **es** un equipo, así que hereda
gratis todo lo demás: puede tener su propio serial, su propia garantía y su propia falla. Los componentes
se derivan del catálogo al instanciar, vía `equipo_modelo_componente(modelo_padre_id, equipo_tipo_id, cantidad)`.

**Trade-off:** una jerarquía arbitrariamente profunda es más de lo que el negocio necesita hoy.
⚠️ **Por qué la marco:** no puse límite de profundidad ni CHECK contra ciclos (Postgres no lo puede
expresar sin trigger). Hoy la profundidad real es 2. Si quieres el cinturón, se agrega un trigger.

### D-04 ⚠️ · «Qué garantías vencen» y «qué mantenimientos están pendientes»

Los dos son datos derivados, y el brief prohíbe guardarlos como columna. Pero son distintos entre sí:

- **Garantía**: `fecha_puesta_servicio + garantia_dias` es una función inmutable de dos columnas de la
  misma fila. Va como **columna generada** (`GENERATED ALWAYS AS ... STORED`) con índice.
  Es derivada, sí, pero Postgres garantiza que nunca se desincroniza, y sin índice la consulta
  «garantías por vencer en 30 días» es un scan completo. Excepción de rendimiento explícita y documentada,
  como pide el propio brief.
- **Mantenimiento**: el próximo depende del **último ejecutado**, que está en otra tabla. No se puede
  generar. Va como **vista** `v_equipo_mantenimiento_pendiente` sobre `equipo_mantenimiento`.

⚠️ **Por qué la marco:** es la única concesión de dato derivado almacenado en todo el modelo. Si prefieres
cero excepciones, la garantía también puede ser vista, a costa de que ese filtro no use índice.

### D-05 · Reemplazo de equipo: se conserva el que sale

Era la decisión pendiente de `ARQUITECTURA_MONITOREO.md` §7. **Se conserva historia**, no se sobrescribe:
el equipo que sale recibe `fecha_baja` + `baja_motivo` y **el que entra apunta al que salió** con
`reemplaza_a_equipo_id`. Ninguna falla histórica pierde su referencia porque la fila del equipo viejo
nunca se borra.

Trade-off: toda consulta de inventario debe filtrar `fecha_baja IS NULL`. Se mitiga con un índice parcial
y con la vista de inventario vigente. Es el mismo patrón `deleted_at` que ya usan 9 tablas de la base.

---

## Frontera y red

### D-06 ⚠️ · Frontera — DECISIÓN PENDIENTE, no implementada

**Por indicación tuya (2026-08-23) esta decisión queda abierta y NO está en `02-modelo.md` ni en
`03-esquema.sql`.** Dejo acá el análisis y mi propuesta para cuando la confirmes.

Pides una relación **1:1** impuesta en base. El modelo actual dice otra cosa, y la medición dice una tercera:

| Evidencia | Qué implica |
|---|---|
| `fronteras.tipo_frontera` tiene 5 valores y está al 100 % | el modelo actual **espera** varias fronteras por planta (generación + consumo) |
| `frontera_gemela_id`, `agrupada_bajo_id`, `embebida_bajo_id` | maquinaria explícita de agrupación y embebido |
| **las 3 auto-FK están al 0 %** | esa maquinaria **nunca se ha usado**: 147 filas, cero agrupaciones |
| 147 fronteras para 194 proyectos, `proyecto_id` al 100 % | compatible con 1:1, pero **no lo demuestra** |
| Los campos que enumeras (FRT generación, FRT consumo, SIC generación, SIC consumo) | sugieren que para ti «la frontera» es **un registro que contiene los 4 códigos**, no 4 filas |

**Lo que falta para decidir**, y no se puede sacar del código:
`SELECT proyecto_id, count(*) FROM fronteras GROUP BY 1 HAVING count(*) > 1;`
Si devuelve 0 filas, tu 1:1 ya es cierto en los datos y solo hay que imponerlo. Si devuelve filas, hay que
decidir qué pasa con ellas antes de poner el UNIQUE.

**Mi propuesta cuando confirmes:** tabla aparte, no columnas en `proyectos` — por las tres razones que tú
mismo das (va a crecer mucho en campos, puede no existir cuando se crea el proyecto, y los códigos FRT/SIC
cambian durante el trámite). Y las tres justifican además una cuarta pieza: **historial de códigos**
(`frontera_codigo_historial`), porque si el código cambia en el trámite, sobrescribirlo pierde con qué
código se reportó el mes pasado. El 1:1 lo impondría sobre la **frontera principal de generación**
(`UNIQUE (proyecto_id) WHERE tipo_frontera = 'generacion'`), que preserva el 1:1 que quieres sin ilegalizar
una frontera de consumo. Pero no lo escribo hasta que me digas.

### D-07 · Red como jerarquía, no lista plana

`operadores_red` son hoy **5 columnas y 7 filas**, sin NIT y sin circuitos. No hay ninguna tabla de
topología en las 125.

**Elegida:** `operadores_red` → `red_circuito` → `red_punto_conexion` → `proyectos.punto_conexion_id`.

El argumento no es de pureza, es funcional: **es la única forma de que un daño de red sea un solo
incidente.** Sin punto de conexión no hay nada que responda «qué otras plantas están colgadas de acá»,
y por eso hoy un corte que afecta 5 plantas son 5 fallas sueltas. El nivel de transformador queda como
columna de `red_punto_conexion` en vez de tabla propia: no conozco ningún caso del negocio que necesite
distinguir dos transformadores en el mismo punto, y una tabla más sin datos es una tabla más que llenar.

**Trade-off:** hay que cargar circuitos y puntos de conexión, que hoy no existen en ninguna parte
(`fronteras.punto_conexion` y `.subestacion` están al 0 %). Hasta que se carguen, `punto_conexion_id`
queda NULL y la agrupación de fallas de red no funciona. Es carga de datos, no de esquema.

---

## Clientes y propiedad

### D-08 · Propiedad como composición versionada

Hoy `proyecto_inversionistas` tiene `fecha_inicio` al 36,5 % y `fecha_fin` al 9,6 %, y el porcentaje se
sobrescribe con `setattr`. Es decir: **hoy no se puede responder quién era dueño en una fecha pasada**, y
las liquidaciones ya dependen de ese dato (`panel_contable_linea`, `liquidacion_facturas`).

| Opción | Por qué no / sí |
|---|---|
| Filas por cliente con `desde`/`hasta` (lo de hoy, pero obligatorio) | El invariante «suma 100 %» **no es chequeable**: hay que sumar filas de distintos rangos que se solapan parcialmente. |
| Tabla de auditoría aparte | Conserva el pasado pero no lo hace consultable: sigue habiendo un estado «actual» sobrescribible. |
| **Elegida: cabecera `proyecto_composicion` con vigencia + líneas `proyecto_composicion_linea`** | Cada cambio de propiedad es **una composición nueva**. La suma se valida por composición, que es un conjunto cerrado. «Dueños del proyecto X a fecha Y» es un solo predicado de rango. |

Sin solapes: `EXCLUDE USING gist (proyecto_id WITH =, vigencia WITH &&)`. Consulta a fecha: índice GiST
sobre el `daterange`, `WHERE proyecto_id = $1 AND vigencia @> $2::date`.

**Trade-off:** cambiar el 1 % de un solo dueño obliga a crear una composición nueva con **todas** las
líneas. Es más escritura, y a cambio el histórico es exacto por construcción y no por disciplina.

### D-09 ⚠️ · Cómo se garantiza que los porcentajes sumen 100 %

Un `CHECK` no puede sumar filas de otra tabla. Tres caminos:

| Opción | Veredicto |
|---|---|
| Validar solo en la aplicación | Es lo de hoy, y por eso hay 115 filas sin garantía de nada. |
| `porcentaje_total` en la cabecera con `CHECK = 100`, mantenido por trigger | Guarda un derivado y el trigger igual hace falta. Lo peor de ambos. |
| **Elegida: `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED`** | Verifica `SUM(porcentaje) = 100` por composición **al COMMIT**, así que se pueden insertar las líneas de a una dentro de la transacción. Es garantía de base de datos real. |

⚠️ **Por qué la marco:** un trigger es lógica en la BD, y este repo no tiene ni uno hoy — es un patrón
nuevo para el equipo, invisible desde `app/models/`. Lo dejo con un comentario `COMMENT ON` para que
quien vea el error sepa de dónde sale. La alternativa sin triggers es aceptar que el invariante viva en
la aplicación, que es exactamente el problema que estamos arreglando.
Nota: la composición tolera **una** excepción legítima — un proyecto sin composición registrada. El
trigger solo actúa cuando hay al menos una línea.

---

## Contratos

### D-10 · Una tabla de contratos, roles en tabla puente

Hoy hay dos tablas de contrato (`contratos_servicio` 61 cols, `ppa_contratos` 35 cols), dos mecanismos
distintos de relación con el proyecto (escalar nullable vs. N:M) y **cuatro caminos** por los que un
cliente llega a un proyecto. Y las FK al cliente están al **0 %**: la relación real es texto.

**Elegida:** `contratos` (con `tipo` enum de 5 valores) + `contrato_parte(contrato_id, cliente_id, rol)`
+ `contrato_proyecto(contrato_id, proyecto_id)`.

Esto responde las dos exigencias del brief a la vez: **sin tabla por tipo de contrato** (el tipo es un
enum) y **sin duplicar la relación cliente–proyecto** (el cliente llega al proyecto por el contrato o por
la composición de propiedad, y cada una dice algo distinto: una es un acuerdo, la otra es propiedad).
Los roles (`propietario`, `arrendador`, `arrendatario`, `comprador`, `vendedor`, `operador`, `mantenedor`,
`representante`) son un enum en la tabla puente, así que un contrato de arriendo cuyo arrendatario no es
el dueño se expresa sin ninguna columna nueva.

**Trade-off:** es la fusión de mayor riesgo del refactor, porque Cumplimiento y Liquidaciones —que están
**fuera de alcance**— leen `ppa_contratos` por FK desde `ppa_tarifas`, `ppa_compromisos_energia`,
`cumplimiento_mensual` y `clasificacion_energia_mensual`. Esos satélites no se rediseñan: se les
re-apunta la FK a `contratos.id`. Cómo, va en `06-plan-migracion.md`.

---

## Fallas

### D-11 ⚠️ · `fallas` no se renombra — cambio respecto del plan inicial

En el plan propuse una entidad nueva `incidente`. **Me retracto, y el motivo es que el brief ya está
cumplido en ese punto:** pide «una sola tabla de eventos, no una tabla por tipo de falla», y `fallas`
**ya es** una sola tabla de eventos. Renombrarla costaría 6 478 filas, 20 endpoints, 15 vistas del
frontend y la app móvil, para ganar un nombre.

Lo que sí falta, y es lo que se agrega:

| Falta | Pieza nueva |
|---|---|
| Una falla afecta N proyectos | `falla_proyecto` (N:M) — hoy `proyecto_id` es escalar NOT NULL |
| Falla contra el equipo, no contra un texto | `falla_equipo` — generaliza `falla_inversores`, cuya FK está al **0,3 %** |
| Historial de estado completo | `falla_estado_historial` con **estado anterior y nuevo** — hoy `fallas_seguimientos` solo guarda el nuevo |
| Adjuntos como entidad | `falla_adjunto` — hoy es `fotos_urls` jsonb con doble codificación histórica |
| Impacto por proyecto | `falla_impacto` — porque si el incidente afecta N plantas, la energía perdida es por planta |
| Causa externa | `fallas.origen` enum + `punto_conexion_id` para las fallas de red |

**Trade-off ⚠️:** quedan dos formas de decir a qué proyecto pertenece una falla (la columna escalar y el
puente) durante toda la transición. Es el mismo antipatrón que hoy tiene `oportunidad_ofertas`
(§9 del inventario), y ahí ya causó que el drawer y la API mostraran plantas distintas. El plan de
migración tiene que cerrar esa ventana rápido, no dejarla abierta como pasó con las ofertas.

### D-12 · Generación promedio: caché declarada, fuera de `proyectos`

La generación de los últimos 30 días **no es una columna**: es una consulta sobre la serie de tiempo, que
vive en la API de Unergy y en `generacion_diaria`. Pero el contrato congelado expone
`energia_promedio_mensual_mwh` y todo `energia_promedio_detalle`, y hoy eso es una caché con razón
documentada en el propio modelo (`app/models/proyectos.py:115-134`): las vistas de contratos no pueden
llamar a la API en cada consulta.

**Elegida:** se mantiene la caché, pero **sale de `proyectos`** a `proyecto_generacion_promedio` (1:1).
Con eso `proyectos` pierde 6 columnas, la caché queda visiblemente separada del dato maestro, y el
contrato de salida no cambia una coma: la capa de salida arma el mismo nodo desde la tabla nueva.
Las 5 columnas de procedencia (`origen`, `dias_con_datos`, `ventana_desde/hasta`, `actualizado_en`) son
**metadatos de la caché**, no derivados: dicen de dónde salió el número. Se conservan tal cual.

---

## Transversales

### D-13 ⚠️ · Las 10 claves de integración externa salen a una tabla satélite

Hoy la misma planta tiene 10 columnas de identidad externa en `proyectos` (`sub_project` 49,5 %,
`topic_slug` 28,4 %, `project_id_solenium` 29,4 %, `sunfactory_project_id` 63,9 %, `origina_code` 62,4 %,
`codigo_tsf`, `topico_liquidaciones`, y 3 `quoia_*` al 0 %), y el propio modelo documenta un caso real de
desalineación (`proyectos.py:87-93`).

**Elegida:** `proyecto_identificacion_externa(proyecto_id, sistema, clave)` con UNIQUE `(sistema, clave)`.
Agregar un sistema nuevo deja de ser una migración.

⚠️ **Por qué la marco: es el cambio más caro del modelo.** `sub_project` tiene UNIQUE y lo lee medio
backend (`api_id_unergy()` del contrato congelado sale de ahí), y `topic_slug` también tiene UNIQUE y da
409 en el PATCH de proyectos. Requiere vista de compatibilidad sin excepción. Si quieres bajar el riesgo,
la variante es dejar `sub_project` y `topic_slug` en `proyectos` y mover solo las otras 8.

### D-14 · Simulación: de 3 JSONB a filas

`p50/p90/p99_mensual_kwh` son arrays de 12 en JSONB, **sin CHECK de longitud**, al 20,1 %, y la API tiene
que normalizarlos con un helper (`app/utils/series_mensuales.py`) porque a veces vienen como texto JSON
(bug ya documentado en la memoria del proyecto).

**Elegida:** `proyecto_simulacion(proyecto_id, escenario, mes, energia_kwh)` con `CHECK (mes BETWEEN 1 AND 12)`
y UNIQUE `(proyecto_id, escenario, mes)`. La BD deja de aceptar un array de 11 meses o un string.
La capa de salida rearma los tres arrays de 12 y el `p50_anual_kwh`, idénticos.

### D-15 · Enums nativos, catálogos como tabla

La casa ya usa **52 tipos ENUM nativos** de Postgres sobre clases `str, Enum` (`SAEnum(..., name="...")`).
Se sigue ese patrón, no se inventa otro. Lo que el usuario puede extender va como tabla: `equipo_tipo`,
`fabricante`, `operadores_red`, los 5 `fallas_cat_*`.

**Trade-off conocido:** agregar un valor a un enum nativo exige `ALTER TYPE ... ADD VALUE`, que no corre
en transacción — por eso hay 25 de esos en `_PENDING_DDLS` y 4 en `init_db.py`. Y hay un precedente malo
documentado: un `RENAME VALUE` que se revertía en cada deploy. **Regla derivada: los enums nuevos se
agregan con `ADD VALUE`, nunca se renombran valores.** Si un valor deja de servir, se deja de usar.

### D-16 ⚠️ · La ubicación NO se normaliza a catálogo de municipios

Lo correcto en un modelo limpio sería `municipio_id` → catálogo DIVIPOLA. **No lo hago**, y la razón es
el contrato congelado: `ubicacion.municipio` y `ubicacion.departamento` se resuelven **por cascadas
independientes** (el municipio puede venir de la oferta y el departamento del proyecto), y el comentario
del código explica por qué: *hay filas con el departamento cargado y el municipio en blanco, y colapsarlos
en un solo campo perdería el que sí está* (`app/services/comercial.py:1622-1627`). Un `municipio_id` único
no puede representar «departamento sí, municipio no».

⚠️ **Por qué la marco:** es una deuda que dejo abierta a sabiendas. Cuando el consumidor externo confirme
que puede vivir con IDs, entra el catálogo. Hasta entonces siguen siendo dos strings, y queda dicho.

### D-17 · RLS descartada

0 políticas en el DDL, un solo usuario de BD (`app/core/database.py:5-13`), ninguna dimensión de tenancy:
todos los usuarios son de Unergy y ven la misma flota. Postgres nunca sabe qué usuario de la app está
detrás de un query, así que una política no tendría de dónde leer el sujeto. Activarla exigiría propagar
identidad a la sesión (`SET LOCAL`) y repensar el pool. La autorización sigue donde está: `get_current_user`
+ chequeo de rol por endpoint. Queda dicho que hoy **466 de 494 endpoints solo exigen estar autenticado**
y que el rol se chequea ad-hoc en 13 sitios — eso es una tarea de seguridad, no de modelo de datos.

### D-18 · Lo que se conserva intacto, y por qué

El brief pide decirlo explícitamente:

| Se conserva | Por qué |
|---|---|
| Los 5 catálogos `fallas_cat_*` | Funcionan, tienen UNIQUE en `codigo`, y el usuario ya los administra. Solo se les agrega índice a `fallas_cat_tipos.categoria_id` |
| `registro_conexion` + `registro_transicion` y satélites | **Es el único subdominio que ya hace bien el historial de estados.** Es el patrón que copio, no lo que corrijo |
| `portafolios`, `contactos`, `proyecto_area_contacto` | Modelan bien lo suyo, con los UNIQUE correctos |
| `ppa_tarifas`, `ppa_compromisos_energia`, `cumplimiento_mensual` | Fuera de alcance. Solo cambian de FK padre |
| `generacion_diaria`, `precios_bolsa_*`, tablas de clima | Series de tiempo, correctamente modeladas |
| El mecanismo de auth y `api_keys` | Fuera de alcance del modelo de datos |

### D-19 · Alcance del DDL

`03-esquema.sql` trae **el núcleo, ejecutable de arriba a abajo sobre una base vacía**. Las tablas fuera
de alcance (liquidaciones, Cumplimiento/MEM, comercial, arriendos, O&M) **no se redefinen**; las que hacen
falta para que el script corra (`usuarios`, los catálogos de fallas) van en un bloque inicial marcado como
preexistente. Queda una lista explícita de qué quedó fuera.

### D-20 ⚠️ · «Si tiene tracker» y «tipo de subestación» no van como columnas de proyecto

El brief los pide como campos técnicos del proyecto. **Aplico tu propio principio**: «nada de datos
derivados guardados como columna». Si el tracker y la subestación son equipos —y lo son, los listas como
tipos de equipo en la misma página—, entonces `tiene_tracker` es `EXISTS (SELECT 1 FROM equipo WHERE
proyecto_id = ... AND tipo = 'tracker')` y el tipo de subestación es la especificación de ese equipo.
Guardarlos además como columna crea dos verdades que se van a desincronizar, que es el patrón que
`proyectos.srv_*` ya tiene hoy.

⚠️ **Por qué la marco:** contradice tu lista de campos. Si los quieres como columna por rendimiento de
un filtro concreto, dime cuál es el filtro y lo dejo como vista o columna generada, no como dato editable.
Lo que sí quedan como columnas del proyecto son `potencia_ac_kw`, `potencia_dc_kwp` y `altitud_msnm`:
esos no se derivan de ningún equipo.

---
---

# Apéndice · 2026-08-26

Todo lo de arriba se escribió el 2026-08-23 contra el estado del repo en `370b9cf`.
Entre esa fecha y hoy entraron **86 commits**, y una parte grande demolió y reconstruyó
`fronteras`. Este apéndice **no reescribe** ninguna decisión anterior: las cierra, las corrige
o las marca como superadas, con la fecha y el motivo.

## D-06 (cierre) · Frontera — la pregunta cambió de forma

**Estado: la pregunta original quedó SIN SENTIDO. Hay una nueva, más pequeña, y sí está abierta.**

### Lo que se cayó de mi propio análisis

El 23 de agosto argumenté que tu 1:1 chocaba con el modelo porque existía maquinaria explícita de
agrupación y embebido (`frontera_gemela_id`, `agrupada_bajo_id`, `embebida_bajo_id`,
`es_agrupadora`, `es_principal_embebido`, y cinco factores de reparto). **Ese argumento ya no
existe, y era peor de lo que yo creía.** La migración 080 borró las tres auto-FK con esta
verificación: *"los 3 son 0/145 en producción, no tienen `relationship()` en el modelo, y ningún
query/servicio del backend los usa (confirmado con auditoría de 2 agentes)"*. Y la 097 borró los
dos booleanos con un dato aún más contundente: *"145/145 en False siempre — nunca tuvieron un
valor real distinto del default"*.

O sea: **mi principal objeción a tu 1:1 se apoyaba en estructura que nunca se usó en ninguna
fila.** Queda retirada.

### Pero la respuesta sigue siendo que no es 1:1 — y ahora está documentada

Dos evidencias nuevas, ninguna mía:

1. **La migración 085**, que crea el M2M `contrato_frontera`, lo declara como hecho del dominio:
   *"una planta puede tener varias Fronteras (generación, consumo, distintos medidores)"*.
2. **`app/api/v1/reporte_cgm.py:98-124`** construye, por proyecto, un diccionario con **dos
   ranuras**: `frt_gen` y `frt_con`. Un proyecto tiene rutinariamente dos fronteras, una de
   generación y una de consumo. El comentario del código nombra un caso real: *"consumo_auxiliar /
   consumo_propio son el autoconsumo de la misma planta de generación (ej. Sol&Cielo 7 Los Bongos)"*.

Y el modelo lo sostiene: `Proyecto.fronteras` sigue siendo `Mapped[list[...]]` con `uselist=True`
(`app/models/proyectos.py:236`). El repo **sabe** expresar 1:1 cuando lo quiere —
`servicio_operacion` y `servicio_representacion` usan `uselist=False` en las líneas 247-248 del
mismo archivo.

### Por qué tu 1:1 no era un error, sino otro nivel de la misma realidad

En el brief describiste la frontera con cuatro campos: *«código FRT de generación, FRT de consumo,
código SIC de generación, código SIC de consumo»*. **Eso es exactamente la forma del diccionario que
`reporte_cgm` arma al vuelo por proyecto.** Los cuatro códigos en un registro.

Tú describes la vista **a nivel de proyecto**; la base guarda la vista **a nivel de frontera**. Las
dos son ciertas, y el código ya traduce de una a la otra. Por eso la pregunta «¿1:1 o 1:N?» estaba
mal planteada: **la pregunta real era en qué nivel se almacena**, y la respuesta la dieron los
hechos — se almacena por frontera, y la vista por proyecto es una proyección.

### Lo que además cambió, y encarece tu opción

Dos de los cuatro códigos que pediste **ya no existen**. La migración 097 los eliminó:

| Campo del brief | Estado hoy |
|---|---|
| código FRT de generación | vive como `codigo_frontera` de la fila cuyo `tipo_frontera = 'generacion'` |
| FRT de consumo | ídem, en la fila de tipo consumo |
| **código SIC de generación** | **eliminado** (`codigo_sic_frontera_generacion`, tenía 92-94/145 filas con dato, *"sin consumidor"*) |
| **código SIC de consumo** | **eliminado** (`codigo_sic_frontera_usuario`, ídem). Queda `codigo_sic_submercado_consumo`, que es otra cosa |

Si los quieres de vuelta, es una decisión de re-agregarlos, no de rediseñar la cardinalidad. Y ya
no hay 101 columnas que fusionar: `fronteras` bajó a **40**, y perdió toda su ubicación (consolidada
en `Proyecto`), su capacidad y sus factores.

### ⚠️ Lo que sigue abierto, y es mucho más chico

Ya no hace falta decidir la cardinalidad general. Lo único que queda por resolver es si se impone
**unicidad de la frontera de generación por proyecto**:

```sql
SELECT proyecto_id, count(*)
  FROM fronteras
 WHERE tipo_frontera = 'generacion' AND deleted_at IS NULL
 GROUP BY 1 HAVING count(*) > 1;
```

Tres piezas de evidencia apuntan a que devuelve **0 filas**:

- La migración 090 midió que la capacidad de la frontera coincidía con
  `Proyecto.potencia_instalada_kwp` en **52 de 53** fronteras con dato. Con dos fronteras de
  generación por planta, cada una llevaría una fracción, no el total.
- La migración 097 dice que `potencia_maxima_declarada` coincide **1:1, con 0 discrepancias en las
  94 filas pobladas**, con su equivalente en `Proyecto`.
- El dict de `reporte_cgm` tiene **una sola** ranura `frt_gen` por proyecto.

**Mi recomendación:** correr esa consulta y, si da 0 filas, imponerlo con un índice único parcial —

```sql
CREATE UNIQUE INDEX uq_frontera_generacion_por_proyecto
    ON fronteras (proyecto_id)
 WHERE tipo_frontera = 'generacion' AND deleted_at IS NULL;
```

Eso te da el 1:1 que querías **donde de verdad aplica**, sin ilegalizar la frontera de consumo que
el negocio sí usa, sin fusionar dos filas en una, y sin tocar `reporte_energia_generacion` /
`reporte_energia_consumo`, que cuelgan de `frontera_id` y quedaron en `ON DELETE RESTRICT` por ser
historial regulatorio (migración 083).

**Y un bug latente que encontré de paso, independiente de la decisión:** en
`app/api/v1/reporte_cgm.py:110-115`, `datos["frt_gen"] = f.codigo_frontera` **sobrescribe en
silencio** si un proyecto tuviera dos fronteras de generación. O eso no puede pasar —y entonces el
índice único solo formaliza lo que ya es cierto— o el reporte CGM está perdiendo códigos hoy sin
que nadie lo note. La misma consulta responde las dos cosas. Vale correrla aunque decidas no tocar
el modelo.

### Qué NO cambia del diseño

Que la frontera vaya en **tabla aparte** y no como columnas de `proyectos` sigue siendo correcto, y
por las tres razones que tú diste: va a crecer en campos, puede no existir cuando se crea el
proyecto, y los códigos cambian durante el trámite. Los 86 commits refuerzan la tercera: hubo
`fecha_primer_registro_asic` fusionada en `fecha_registro_asic` (migración 088) y códigos SIC
eliminados, todo movimiento de identidad regulatoria. **El historial de códigos
(`frontera_codigo_historial`) sigue siendo la pieza que falta** y sigue justificado.

## ⚠️ D-10 (corrección) · Las tres tarifas de servicio no estaban contempladas

Juan preguntó el 2026-08-26 si `tarifa_administracion`, `tarifa_cgm` y `tarifa_representacion`
quedan cubiertas en `proyecto_composicion` o se pierden en la migración. **Dos cosas.**

Primero, una precisión de ubicación: **esas columnas no están en `proyecto_inversionistas`.**
Verificado en el modelo de hoy (`app/models/proyectos.py`, la clase `ProyectoInversionista` tiene
10 columnas y ninguna es de tarifa) y en el DDL de producción del 2026-08-20. Viven en
**`contratos_servicio`**: `tarifa_admin`, `tarifa_cgm`, `tarifa_representacion`
(`app/models/contratos.py:115-117`).

Segundo, y esto **sí es un hueco real de mi diseño**: mi tabla `contratos` de `03-esquema.sql` tiene
**solo `tarifa_base`**, y `04-mapeo.md` **no las menciona en ninguna parte**. Tal como está escrito
el Entregable 1, **las tres se perderían en silencio en la fusión de contratos**.

No es un detalle menor: están vivas y en uso activo. El 2026-08-25 se insertaron contratos de
representación usando las tres (Cedillanos al 5 % de administración sin representación ni CGM;
Sabana de Torres al 3,8 % con 6 y 6), y hay lógica de negocio colgando —
`4024c1c Costos del panel: elegir el contrato de representacion por regla, no por id`.

**No lo resuelvo por mi cuenta**, según tu regla. Lo que hay que decidir, y lo dejo planteado:

| Opción | Qué implica |
|---|---|
| **A · Tres columnas en `contratos`** | Lo más directo y lo que menos rompe. Pero son tarifas específicas de un tipo de contrato viviendo en la tabla genérica: el mismo antipatrón de bloques por tipo que `04-mapeo.md` §5 critica en `contratos_servicio` |
| **B · Tabla `contrato_tarifa(contrato_id, concepto, valor)`** | Consistente con el resto del modelo, extensible sin migración, y deja `tarifa_base` para el precio principal. Cuesta reescribir los lectores |
| **C · Dejarlas donde están** | `contratos_servicio` no se fusiona en esta fase y se aplaza. Contradice D-10 |

Me inclino por **B**, pero la decisión es tuya y afecta el DDL, el mapeo y la Fase 6 del plan.
Mientras no se decida, `04-mapeo.md` queda con la advertencia y **la Fase 6 no se puede ejecutar**.

---

# Apéndice II · 2026-08-26 · Tres decisiones nuevas (D-21 a D-23)

**Origen:** la validación de separación de entidades que pidió Juan destapó tres cosas — `estado`/`etapa`
como caché sin sincronizar, documentos sin entidad propia, y `operador_red_id`/`punto_conexion_id`
capaces de contradecirse. Las tres quedan decididas acá.
**Estado: SOLO DISEÑO.** `02-modelo.md` y `03-esquema.sql` **no se modificaron**, igual que con D-06.
El DDL de abajo es la propuesta, no el esquema.
**Contexto que pesa en las tres:** producción **no tiene ni un trigger ni una función** hoy, y **cero FK
compuestas**. `03-esquema.sql` ya introduce el primer trigger (la suma 100 % de D-09). Cada mecanismo
procedimental nuevo es un patrón que el equipo no tiene, y eso cuenta como costo.

## D-21 · `estado` y `etapa`: caché con sincronización garantizada

**Decisión de Juan (2026-08-26):** se quedan en `proyectos`, pero con trigger que las sincronice desde
`proyecto_estado_historial` y `COMMENT` explicando la razón. *«Caché sin sincronización garantizada no
es opción.»*

**La fuente de verdad pasa a ser `proyecto_estado_historial`.** `proyectos.estado` y `proyectos.etapa`
son una proyección de la fila cuya `vigencia` contiene la fecha de hoy.

### El agujero que un trigger solo NO tapa

Un trigger reacciona a escrituras. Pero la caché también se puede desincronizar **sin que nadie
escriba**: si un periodo termina el 1 de septiembre y el siguiente arranca ese día, la fila vigente
cambia **por el paso del tiempo**. A las 00:00 del 1 de septiembre la caché queda mal y ningún trigger
se enteró.

Y no se puede tapar con un `CHECK`: cualquier expresión con `CURRENT_DATE` es `STABLE`, no `IMMUTABLE`,
y Postgres la rechaza en un constraint. Es el mismo muro que ya encontramos con
`fecha_resolucion::date` en `fallas` (ver el BLOQUE 9 del DDL).

**Por eso la sincronización garantizada son tres piezas, no una:**

| Pieza | Qué cubre |
|---|---|
| 1 · Trigger sobre `proyecto_estado_historial` | El 99 % de los casos: alguien registra un cambio de estado |
| 2 · Tarea diaria de reconciliación | El paso del tiempo. Son 194 filas: recalcular todas cuesta milisegundos |
| 3 · Trigger de bloqueo sobre `proyectos` | Que nadie escriba `estado` por fuera del historial |

### El diseño

```sql
-- 1 · Recalcula la caché de UN proyecto desde su historial.
CREATE OR REPLACE FUNCTION fn_sync_estado_proyecto(p_proyecto_id BIGINT) RETURNS VOID AS $$
DECLARE
    v_estado estado_proyecto_enum;
    v_etapa  proyecto_etapa_enum;
    v_hay    BOOLEAN := FALSE;
BEGIN
    SELECT h.estado, h.etapa, TRUE
      INTO v_estado, v_etapa, v_hay
      FROM proyecto_estado_historial h
     WHERE h.proyecto_id = p_proyecto_id
       AND h.vigencia @> CURRENT_DATE
     LIMIT 1;

    -- DECISION EXPLICITA (D-21, cerrada por Juan el 2026-08-26): si el historial
    -- tiene un HUECO -- ningun periodo cubre hoy -- la cache NO se toca. Se
    -- conserva el ultimo estado conocido, que es mas util que un NULL y ademas
    -- respeta el NOT NULL de proyectos.estado. El hueco no queda escondido: el
    -- proyecto aparece en v_proyecto_estado_desincronizado, que es donde se ve.
    -- Esto NO es el comportamiento por defecto de un UPDATE ... FROM vacio: es
    -- una salida temprana escrita a proposito.
    IF NOT v_hay THEN
        RETURN;
    END IF;

    -- El flag de sesión le dice al trigger de bloqueo que este UPDATE es legítimo.
    PERFORM set_config('app.sync_estado', 'on', TRUE);
    UPDATE proyectos
       SET estado = v_estado,
           etapa  = v_etapa
     WHERE id = p_proyecto_id;
    PERFORM set_config('app.sync_estado', 'off', TRUE);
END;
$$ LANGUAGE plpgsql;

-- 2 · Se dispara con cada escritura del historial.
CREATE OR REPLACE FUNCTION fn_trg_sync_estado() RETURNS TRIGGER AS $$
BEGIN
    PERFORM fn_sync_estado_proyecto(COALESCE(NEW.proyecto_id, OLD.proyecto_id));
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tg_sync_estado
    AFTER INSERT OR UPDATE OR DELETE ON proyecto_estado_historial
    FOR EACH ROW EXECUTE FUNCTION fn_trg_sync_estado();

-- 3 · Bloquea la escritura directa: el estado se cambia registrando un periodo.
CREATE OR REPLACE FUNCTION fn_bloquear_estado_directo() RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('app.sync_estado', TRUE) IS DISTINCT FROM 'on'
       AND (NEW.estado IS DISTINCT FROM OLD.estado
            OR NEW.etapa IS DISTINCT FROM OLD.etapa) THEN
        RAISE EXCEPTION
            'proyectos.estado/etapa son una cache de proyecto_estado_historial. '
            'Registra un periodo nuevo en esa tabla; no los escribas directo.'
            USING ERRCODE = 'raise_exception';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tg_bloquear_estado_directo
    BEFORE UPDATE ON proyectos
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_estado_directo();
```

#### El `COMMENT` y la vista de deriva

Más el `COMMENT` que pidió Juan, y una vista para **detectar** la deriva en vez de suponer que no existe:

```sql
COMMENT ON COLUMN proyectos.estado IS
    'CACHE de proyecto_estado_historial (la fila cuya vigencia contiene hoy). NO se escribe '
    'directo: tg_bloquear_estado_directo lo impide. Se sincroniza con tg_sync_estado en cada '
    'escritura del historial y con la tarea diaria _run_sync_estados, que cubre el cambio de '
    'periodo por paso del tiempo. Existe como columna por rendimiento: la lista de proyectos y '
    'los filtros por estado son la consulta mas frecuente de la plataforma. Ver D-21.';

CREATE VIEW v_proyecto_estado_desincronizado AS
SELECT p.id AS proyecto_id, p.nombre_comercial,
       p.estado AS estado_cache, h.estado AS estado_historial,
       p.etapa  AS etapa_cache,  h.etapa  AS etapa_historial
  FROM proyectos p
  LEFT JOIN proyecto_estado_historial h
         ON h.proyecto_id = p.id AND h.vigencia @> CURRENT_DATE
 WHERE p.deleted_at IS NULL
   AND (p.estado IS DISTINCT FROM h.estado OR p.etapa IS DISTINCT FROM h.etapa);
```

La tarea diaria (`_run_sync_estados` en el scheduler) recorre esa vista y llama a
`fn_sync_estado_proyecto` por cada fila. Si la vista devuelve algo **después** de correrla, hay un bug,
no deriva esperada.

**El hueco en el historial, resuelto explícitamente** *(cerrado por Juan el 2026-08-26: «que sea
explícita, no accidental»)*. Si ningún periodo cubre la fecha de hoy, la función **sale temprano y no
toca la caché**: se conserva el último estado conocido. Tres razones para elegir eso y no NULL:

1. `proyectos.estado` es `NOT NULL`, así que un NULL ni siquiera es representable.
2. El último estado conocido es más útil que un hueco para quien lee la lista de proyectos.
3. **El hueco no queda escondido:** ese proyecto aparece en `v_proyecto_estado_desincronizado`, porque
   su `LEFT JOIN` deja `h.estado` en NULL y `IS DISTINCT FROM` dispara.

La diferencia con la versión anterior de este DDL es que antes ese comportamiento era el **efecto
colateral** de un `UPDATE ... FROM` sin filas; ahora es un `IF NOT v_hay THEN RETURN` con su comentario.
Mismo resultado, pero decidido en vez de heredado.

**Trade-offs aceptados:**

- ⚠️ **Tres triggers y tres funciones nuevas en una base que hoy tiene cero.** Es el costo real de
  «caché con sincronización garantizada». La alternativa —quitar las columnas y exponer una vista— no
  tiene triggers pero cambia el plan de la consulta más frecuente de la plataforma.
- ⚠️ **El flag de sesión `app.sync_estado` es frágil ante una excepción**: si algo revienta entre el
  `set_config('on')` y el `set_config('off')`, queda encendido hasta el fin de la transacción. Se usa
  `is_local = TRUE`, así que muere con la transacción y no contamina la conexión del pool. Aceptado.
- El estado **futuro programado** no se refleja hasta que llega su fecha, que es lo correcto: la caché
  dice qué es hoy, no qué será.

## D-22 · Documentos como entidad, con arco exclusivo

**Decisión de Juan (2026-08-26):** una tabla `documentos` con arco exclusivo, que absorba las columnas
`*_url` sueltas y contemple los documentos de cliente del brief.

Hoy los documentos están en seis sitios y ninguno es una entidad:

| Dónde vive hoy | En el esquema objetivo |
|---|---|
| `proyectos.url_ubicacion` | L334 |
| `equipo_modelos.datasheet_url` | L461 |
| `equipos.documentacion_url` | L499 |
| `proyecto_composiciones.documento_url` | L563 |
| `contratos.documento_url` | L604 |
| `planos_url` dentro del JSON Schema de `subestacion` | L955 |
| `falla_adjuntos` (tabla) | L710 |

Y los del brief —RUT, cámara de comercio, certificación bancaria— **no tienen dónde vivir** en el núcleo.

### El diseño

```sql
CREATE TYPE documento_tipo_enum AS ENUM (
    'datasheet', 'planos', 'ficha_tecnica', 'manual',          -- equipo
    'rut', 'camara_comercio', 'certificacion_bancaria',        -- cliente (los del brief)
    'contrato_firmado', 'acta', 'poliza',                      -- contrato / propiedad
    'evidencia_falla', 'fotografia',                           -- falla
    'mapa_ubicacion',                                          -- proyecto
    'otro'
);

CREATE TABLE documentos (
    id              BIGSERIAL PRIMARY KEY,
    tipo            documento_tipo_enum NOT NULL,

    -- Arco exclusivo: exactamente UNO de estos SEIS tiene valor.
    -- cliente_id y contrato_id van con RESTRICT, no CASCADE: un RUT o un contrato
    -- firmado tienen valor legal y no desaparecen porque se borre su fila padre.
    -- El borrado tiene que fallar ruidosamente y obligar a decidir que se hace
    -- con los documentos. Mismo criterio que la migracion 083 aplico al historial
    -- regulatorio de fronteras.
    proyecto_id      BIGINT REFERENCES proyectos(id)       ON DELETE CASCADE,
    contrato_id      BIGINT REFERENCES contratos(id)       ON DELETE RESTRICT,
    equipo_id        BIGINT REFERENCES equipos(id)         ON DELETE CASCADE,
    equipo_modelo_id BIGINT REFERENCES equipo_modelos(id)  ON DELETE CASCADE,
    cliente_id       BIGINT REFERENCES clientes(id)        ON DELETE RESTRICT,
    falla_id         BIGINT REFERENCES fallas(id)          ON DELETE CASCADE,

    nombre          VARCHAR(300),
    url             VARCHAR(1000) NOT NULL,
    content_type    VARCHAR(120),
    tamano_bytes    BIGINT,
    fecha_documento DATE,
    fecha_expiracion DATE,
    subido_por_id   BIGINT REFERENCES usuarios(id) ON DELETE SET NULL,
    subido_en       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,

    CONSTRAINT ck_documentos_arco_exclusivo CHECK (
        num_nonnulls(proyecto_id, contrato_id, equipo_id,
                     equipo_modelo_id, cliente_id, falla_id) = 1
    ),
    CONSTRAINT ck_documentos_expiracion CHECK (
        fecha_expiracion IS NULL OR fecha_documento IS NULL
        OR fecha_expiracion >= fecha_documento
    )
);
```

`num_nonnulls()` es `IMMUTABLE` y existe desde Postgres 9.6, así que **el arco lo impone la base**, no
la aplicación. Es la diferencia con `audit_log.registro_id`, que es polimórfica sin FK y por eso puede
apuntar a filas que ya no existen (`00-inventario-actual.md` §11.G).

Índices: uno parcial por brazo (`CREATE INDEX ... ON documentos (proyecto_id) WHERE proyecto_id IS NOT NULL`),
más `(tipo)` y `(fecha_expiracion) WHERE fecha_expiracion IS NOT NULL` — este último responde
«qué documentos de cliente están por vencer», que es el equivalente documental de la consulta de
garantías de D-04.

### Qué se migra

| Origen | `tipo` | Brazo |
|---|---|---|
| `proyectos.url_ubicacion` | `mapa_ubicacion` | `proyecto_id` |
| `equipo_modelos.datasheet_url` | `datasheet` | `equipo_modelo_id` |
| `equipos.documentacion_url` | `manual` | `equipo_id` |
| `contratos.documento_url` | `contrato_firmado` | `contrato_id` |
| `proyecto_composiciones.documento_url` | `acta` | **`proyecto_id`** (ver nota) |
| `planos_url` del JSON Schema de `subestacion` | `planos` | `equipo_id` |
| **`falla_adjuntos` (tabla completa)** | `evidencia_falla` / `fotografia` | `falla_id` |
| — (nuevos, del brief) | `rut`, `camara_comercio`, `certificacion_bancaria` | `cliente_id` |

**`falla_adjuntos` se absorbe y desaparece.** Tenía las mismas 6 columnas (`url`, `nombre`,
`content_type`, `tamano_bytes`, `subido_por_id`, `subido_en`) y mantenerla aparte dejaría dos entidades
para lo mismo — justo lo que esta decisión corrige.

**Y sale una propiedad del JSON Schema.** `planos_url` deja de ser una clave dentro de
`equipo_tipos.esquema_especificaciones`: los documentos son documentos, no una especificación técnica.
Es un ajuste a D-01 que la hace más limpia.

### Los tres puntos abiertos, cerrados por Juan el 2026-08-26

**1 · Seis brazos, no siete.** Se saca `composicion_id`: **el acta de una composición cuelga del
proyecto**, con `tipo = 'acta'`. La composición concreta se puede recuperar cruzando la fecha del
documento con la `vigencia` de la composición, y si algún día hace falta el vínculo directo, se agrega
una columna `composicion_id` *sin* brazo de arco — informativa, no discriminante.

*Alternativa descartada:* siete brazos con `composicion_id` en el arco. Se descartó porque un arco de
siete columnas empieza a costar más de lo que aporta: siete índices parciales, siete FK, y un `CHECK`
que hay que leer dos veces.

**2 · `cliente_id` y `contrato_id` van con `RESTRICT`.** *«Un RUT no se borra solo.»* Un documento con
valor legal no desaparece porque se borre su fila padre: el borrado falla ruidosamente y obliga a
decidir qué se hace con él. Es el mismo criterio que la migración 083 aplicó al historial regulatorio de
fronteras, y el que la Fase 1 paso 1.4 propone como regla general.

Los otros cuatro brazos siguen en `CASCADE`, y por qué: un datasheet sin su modelo de equipo, un manual
sin su equipo o una foto sin su falla no son documentos huérfanos con valor propio — son ruido.

⚠️ **Consecuencia operativa:** borrar un cliente con documentos pasa a fallar. Hoy devuelve 500 porque
la API no captura `IntegrityError` — por eso el paso **1.5** de la Fase 1 (traducir a 409 legible) tiene
que ir **antes** de que esta tabla exista, no después.

**3 · `url_ubicacion`: la salida queda idéntica, confirmado en `05`.** Alimenta
`detalles.ubicacion.url_mapa` de la API externa. Cambia de dónde se lee, no lo que se devuelve. La
confirmación con sus dos condiciones verificables está en `05-impacto-campos-congelados.md` §F.

## D-23 · Coherencia entre `operador_red_id` y `punto_conexion_id`

**Decisión de Juan (2026-08-26):** no se mueven, pero hay que impedir que se contradigan.

El invariante: si un proyecto tiene punto de conexión, su operador de red **tiene que ser** el dueño del
circuito al que pertenece ese punto. Hoy nada lo impide: `punto_conexion → circuito → operador_red` es
una cadena que la fila del proyecto puede desmentir.

### Lo que propongo: FK compuesta, no trigger

```sql
-- 1 · Claves candidatas redundantes que habilitan la FK compuesta.
ALTER TABLE red_circuitos       ADD CONSTRAINT uq_red_circuitos_id_operador
    UNIQUE (id, operador_red_id);

-- 2 · El punto de conexion carga el operador y lo ata a su circuito.
ALTER TABLE red_puntos_conexion ADD COLUMN operador_red_id BIGINT NOT NULL;
ALTER TABLE red_puntos_conexion ADD CONSTRAINT fk_punto_circuito_operador
    FOREIGN KEY (circuito_id, operador_red_id)
    REFERENCES red_circuitos (id, operador_red_id) ON DELETE RESTRICT;
ALTER TABLE red_puntos_conexion ADD CONSTRAINT uq_punto_id_operador
    UNIQUE (id, operador_red_id);

-- 3 · Y el proyecto queda atado a los dos a la vez.
ALTER TABLE proyectos ADD CONSTRAINT fk_proyecto_punto_operador
    FOREIGN KEY (punto_conexion_id, operador_red_id)
    REFERENCES red_puntos_conexion (id, operador_red_id) ON DELETE SET NULL;
```

**Por qué esta y no un trigger:**

- **La contradicción se vuelve imposible por construcción**, no detectable a posteriori. No hay ventana
  entre la escritura y la validación, ni deriva silenciosa si alguien escribe por fuera de la API.
- **Es declarativa.** No agrega código procedimental a una base que hoy tiene cero triggers, y D-21 ya
  va a agregar tres. Un mecanismo declarativo más es barato; el cuarto trigger no.
- **Cubre la segunda dirección, que un trigger sobre `proyectos` no cubre:** si mañana un circuito
  cambia de operador, la FK compuesta bloquea el `UPDATE` en `red_circuitos` mientras haya puntos —y
  proyectos— colgando con el operador viejo. Un trigger sobre `proyectos` no se enteraría.

**La semántica de los NULL es exactamente la que hace falta.** Una FK compuesta usa `MATCH SIMPLE` por
defecto: **si alguna columna es NULL, la restricción no se evalúa**. O sea:

| `punto_conexion_id` | `operador_red_id` | ¿Permitido? |
|---|---|---|
| NULL | NULL | Sí — planta sin datos de red |
| NULL | puesto | Sí — **el caso común hoy**: se conoce el operador, no el punto |
| puesto | NULL | Sí (no se evalúa) ⚠ ver abajo |
| puesto | puesto | **Solo si concuerdan** |

El tercer caso es el único hueco: se podría registrar el punto sin el operador. No es una
contradicción —es un dato incompleto— y **Juan decidió el 2026-08-26 cerrarlo también**, con un `CHECK`
que no necesita consultar otra tabla y por tanto es `IMMUTABLE`:

```sql
ALTER TABLE proyectos ADD CONSTRAINT ck_proyectos_red_completa CHECK (
    punto_conexion_id IS NULL OR operador_red_id IS NOT NULL
);
```

Con eso la matriz queda en tres casos válidos y uno prohibido: **si hay punto de conexión, tiene que
haber operador, y tiene que ser el correcto.**

**Cerrada por Juan el 2026-08-26:** FK compuesta, con la denormalización de `operador_red_id` en
`red_puntos_conexion` y el `CHECK` del hueco. *Alternativa descartada:* el trigger que rellena
`operador_red_id` desde el punto de conexión — menos esquema, pero no cubre el cambio de operador de un
circuito y suma un cuarto trigger a una base que hoy tiene cero.

**Trade-offs aceptados:**

- ⚠️ **`red_puntos_conexion` carga un `operador_red_id` denormalizado.** Es el precio estándar de esta
  técnica, y no puede desincronizarse: su propia FK compuesta contra `red_circuitos` lo impide.
- ⚠️ **Es un patrón que el repo no tiene**: cero FK compuestas en las 148 de producción. Un
  `UNIQUE (id, otra_columna)` se lee como redundante si no se sabe para qué está; los dos
  `CONSTRAINT` llevan `COMMENT` explicándolo.
- ⚠️ **`red_puntos_conexion.operador_red_id` es `NOT NULL`**, así que ningún punto de conexión se
  puede crear sin decir de qué operador es. Es lo correcto —un punto siempre pertenece a un circuito y
  un circuito a un operador— pero conviene tenerlo presente al cargar la topología, que hoy no existe
  y hay que crear desde cero.

## D-16 (nota de deuda) · `municipio` y `departamento` siguen como texto

**Decisión de Juan (2026-08-26):** se queda como está, anotado como deuda con su razón.

Lo correcto sería `municipio_id` contra un catálogo DIVIPOLA. **No se hace, y la razón es el contrato
congelado:** `ubicacion.municipio` y `ubicacion.departamento` se resuelven por **cascadas
independientes** —el municipio puede venir de la oferta comercial y el departamento del proyecto— y el
comentario del código explica por qué: *«hay filas con el departamento cargado y el municipio en blanco,
y colapsarlos en un solo campo perdería el que sí está»* (`app/services/comercial.py`). Un
`municipio_id` único no puede representar «departamento sí, municipio no».

**Y desde el 2026-08-25 pesa más**, no menos: las migraciones 091-095 consolidaron `municipio`,
`departamento`, `latitud`, `longitud` y `direccion` **desde `fronteras` hacia `proyectos`**, así que
`proyectos` es ahora la única fuente de ubicación de la plataforma. Normalizar hoy rompe más
consumidores que hace tres días.

**Coste de la deuda, para que esté dicho:** no hay forma de garantizar que «Sabana de Torres» se escriba
igual en dos filas, ni de desambiguar los municipios homónimos (~15 «La Unión» en Colombia) sin mirar el
departamento al lado. El consumidor externo ya carga con eso: su `_resolve_municipio_id` necesita los dos
strings justamente porque no hay id.

**Cuándo se paga:** cuando el consumidor externo confirme que puede recibir un id, o cuando aparezca un
segundo consumidor que necesite cruzar por municipio. Entra el catálogo y los dos strings se conservan
como campos derivados de la salida.

---

## D-24 · `contrato_tarifas`, **versionada** — cerrada 2026-08-26

Juan confirmó: las tarifas van en el contrato, no en el inversionista. **El inversionista las alcanza
vía `contrato_partes`**, y `proyecto_composicion` NO las duplica. Y pidió revisar si hay evidencia de
que se renegocien, porque si la hay la tabla necesita vigencia.

### La evidencia: no es que *puedan* cambiar, es que **cambian todos los años**

Busqué en el código y en los datos que ya están cargados. Cinco pruebas, de más a menos concluyente:

**1 · La misma tarifa con tres valores distintos, en el propio repo.** `app/main.py:1478-1482`, la serie
que alimenta los contratos de Ayura 1:

```python
_IDX_AYURA1 = [
    {"año": 2024, "ipc": None, "valor": 5.0,     "esBase": True},
    {"año": 2025, "ipc": 5.2,  "valor": 5.26},
    {"año": 2026, "ipc": 5.1,  "valor": 5.52826},
]
```

Eso no es una tarifa con historia posible: es una tarifa **con historia real, ya cargada**, indexada por
IPC año a año. Se usa como `indexacion_cgm` y `indexacion_representacion` en 14 contratos.

**2 · `ppa_tarifas` ya está versionada, en la misma base.** `(contrato_id, año, mes) → tarifa`, con
`UNIQUE (contrato_id, "año", mes)` (`app/models/contratos.py`). El precio de la energía de un PPA se
guarda **por mes** desde siempre. La pregunta ya está respondida para un tipo de contrato; lo raro es
que no lo esté para los otros.

**3 · Cuatro columnas JSONB que son series temporales.** `indexacion_anual`, `indexacion_mensual`,
`indexacion_cgm`, `indexacion_representacion` (`contratos.py:114-127`). Son exactamente el histórico que
esta decisión necesita, guardado sin esquema.

**4 · Un endpoint de carga masiva de indexación.** `POST /contratos-servicio/importar-indexacion?tipo=anual|mensual`
(`app/api/v1/contratos_servicio.py:150-185`) recibe `[{anio, ipc_aplicado, valor}]` por proyecto. Existe
una operación de negocio dedicada a **cargar el histórico de tarifas**.

**5 · Tres catálogos de tasas y la fórmula escrita.** `om_ipc_tasas`, `arr_ipc_tasas`, `ipp_mensual`, más
las columnas `indice_indexacion`, `fecha_indexacion`, `periodicidad_indexacion`,
`periodo_indexacion_base`, `valor_indexacion_base`. Y el docstring de `contratos.py:225`:
`tarifa_indexada = tarifa_base × (IPP_del_mes / valor_indexacion_base_del_PPA)`.

**Conclusión: versionada, sin duda.** No hay que descartar nada — la evidencia es positiva y abundante.

### El diseño

`contrato_tarifas` con `vigencia DATERANGE` y
`EXCLUDE USING gist (contrato_id WITH =, concepto WITH =, vigencia WITH &&)`: un concepto no puede tener
dos valores vigentes a la vez en el mismo contrato. Es el mismo mecanismo de D-08, y por la misma razón
que Juan señaló: **la liquidación de un periodo se calcula con la tarifa vigente en ese periodo.**

Las columnas escalares (`tarifa_admin`, `tarifa_cgm`, `tarifa_representacion`, `tarifa_base`)
**desaparecen**. Hoy el escalar guarda el valor base y el JSONB la serie indexada — dos sitios que pueden
discrepar. En el modelo nuevo la base es la fila con `es_base = TRUE`.

### `concepto` como enum, y son **cinco**, no tres

Juan nombró tres: administración, CGM y representación. En los datos hay dos más:

| Concepto | De dónde sale |
|---|---|
| `administracion` | `contratos_servicio.tarifa_admin` |
| `cgm` | `tarifa_cgm` + `indexacion_cgm` |
| `representacion` | `tarifa_representacion` + `indexacion_representacion` |
| **`canon`** | `tarifa_base` / `tarifa_mensual` + `indexacion_anual`/`_mensual` — el canon de mantenimiento, arriendo e internet |
| **`energia`** | `ppa_tarifas` — el precio del PPA |

Va como **enum nativo**, no como catálogo tabla: agregar un concepto es un cambio de modelo de negocio
que necesita código de todos modos, no un dato que administre el usuario. Es el criterio de D-15.

### ✅ Verificado: `btree_gist` sí soporta enums en un `EXCLUDE`

El `EXCLUDE` incluye `concepto WITH =`, así que `btree_gist` tiene que soportar el tipo enum. La
documentación lo dice desde 9.1, pero **este repo no tiene ni un `EXCLUDE` ni una FK compuesta en
producción**, así que no había precedente propio. **Se probó** (2026-08-26) contra la base local de
desarrollo, dentro de una transacción con `ROLLBACK` — no quedó ni el tipo ni la tabla:

| Paso | Resultado |
|---|---|
| `CREATE EXTENSION btree_gist` | **OK** — no estaba instalada en la base local; se instala sin problema |
| `CREATE TYPE ... AS ENUM` con los 5 conceptos | **OK** |
| `EXCLUDE USING gist (contrato_id WITH =, concepto WITH =, vigencia WITH &&)` | **OK, aceptado** |
| Dos periodos **consecutivos** del mismo concepto | aceptados ✔ (es lo correcto: 2024→2025 no se solapa con 2025→2026) |
| Mismo periodo, **otro concepto** | aceptado ✔ (CGM y representación conviven en el mismo año) |
| **Solapamiento del mismo concepto** | **RECHAZADO** ✔ `llave en conflicto viola la restricción de exclusión` |

Entorno: PostgreSQL **17.9**, la misma versión mayor que produccion. No hace falta el plan B del catálogo
tabla con `id` entero.

⚠️ **Lo único que queda dicho de esto:** `btree_gist` **no estaba instalada** en la base local, así que la
migración tiene que crearla — y ya hay precedente de que hace falta, porque D-08 y D-09 la necesitan
igual para la composición accionaria. Va en la misma revisión, antes de cualquier tabla con `EXCLUDE`,
y con la verificación de permisos que la Fase 2 ya tiene como condición de entrada.

### 🛑 `unidad` es obligatoria, y esto lo descubrí mirando los datos

`tarifa_admin` vale `0.038` y `0.05`. `tarifa_cgm` vale `6.0`. **No son la misma magnitud:** el commit
que cargó Cedillanos lo dice explícito — *«Cedillanos administra al 5 % (no al 3,8 % del resto) y no
cobra representación ni CGM; Sabana va al 3,8 % con 6 y 6»*.

O sea: **administración es un porcentaje, CGM y representación son COP/kWh**, y hoy viven en columnas
`Numeric` del mismo aspecto donde son indistinguibles. Meterlas en una sola tabla sin `unidad` sería
empeorar el problema, no arreglarlo. Por eso `tarifa_unidad_enum` (`porcentaje`, `cop_kwh`, `cop_mes`,
`cop_total`) es `NOT NULL`, con un CHECK que obliga a que un porcentaje se guarde como fracción ≤ 1,
como ya está hoy.

### ⚠️ El hallazgo que no esperaba: administración no tiene serie

`tarifa_cgm` y `tarifa_representacion` tienen su `indexacion_*`. El canon tiene la suya. **La
administración no.**

Dos lecturas y no sé cuál es: o no se indexa —es un porcentaje sobre el ingreso, así que sube sola—, o
**sí se renegocia y ese histórico se pierde** cada vez que alguien edita el campo. La segunda explicaría
por qué Cedillanos está al 5 % y el resto al 3,8 %.

### ✅ RESUELTO 2026-08-26: **es la hipótesis B**

Juan confirmó con el negocio: **todas las tarifas se pueden renegociar, incluida administración.** El
requisito que sale de ahí es explícito — *«histórico completo de tarifas: cada valor con su vigencia, y
renegociar nunca borra el valor anterior. Consultar qué tarifa aplicaba a este contrato en tal fecha
tiene que ser siempre respondible.»*

Eso confirma lo que temía: **hoy se está perdiendo historia de liquidación.** Cada vez que alguien edita
`tarifa_admin` el valor anterior desaparece, y con él la capacidad de recalcular un periodo pasado. No es
un hueco del modelo nuevo: es un bug activo del actual. Las tres consecuencias van en §§ a, b y c de
abajo.

*(Las dos hipótesis quedan acá como registro de lo que se preguntó y por qué.)*

| | Hipótesis A | Hipótesis B |
|---|---|---|
| **Qué dice** | La administración **no se indexa**. Es un porcentaje sobre el ingreso, así que sube sola cuando sube el ingreso: renegociar el porcentaje sería raro | La administración **sí se renegocia**, y ese histórico **se está perdiendo** cada vez que alguien edita `tarifa_admin` |
| **Qué explicaría** | Que nunca se haya construido una `indexacion_admin`, a diferencia de CGM y representación | Que Cedillanos esté al 5 % y el resto al 3,8 % — dos valores distintos para el mismo concepto |
| **Qué implica en la migración** | Una fila por contrato, `es_base = TRUE`, vigencia abierta. Trivial | Hay que **recuperar el histórico de otra fuente** (actas, correos, el Excel del panel) antes de migrar, o las liquidaciones pasadas quedan con la tarifa de hoy |
| **Cómo se distingue** | Preguntando. En los datos no se puede: el histórico que faltaría es justamente el que no está | |

**Era la B.** Es un bug de liquidación activo hoy: cualquier recálculo de un periodo pasado usa la tarifa
actual. La tabla nueva lo cierra hacia adelante; lo que ya se perdió se recupera solo en parte (§ c).

### a · Administración va versionada igual, y el modelo distingue por qué cambió

La administración no se indexa por IPC: **se renegocia**. Las demás hacen las dos cosas. Para que el
modelo lo refleje sin inventar dos tablas, la columna `origen` (`tarifa_origen_enum`) dice de dónde salió
cada valor:

| `origen` | Qué significa | Lleva `indice`/`indice_pct` |
|---|---|---|
| `pactada` | el valor inicial del contrato | no |
| `indexacion` | ajuste automático por IPC/IPP sobre el valor anterior | **sí, obligatorio** |
| `renegociacion` | acuerdo entre las partes, sin índice — **el caso de administración** | no |
| `correccion` | se corrigió un valor mal cargado | no |
| `migracion` | viene del escalar de hoy: **la fecha de inicio no se conoce** (§ b) | no |

Un `CHECK` lo impone: solo una `indexacion` puede traer índice, y ninguna otra puede traerlo. Con eso,
«¿esta tarifa subió por IPC o porque se renegoció?» deja de ser una pregunta sin respuesta, que es
justamente lo que hoy no se puede distinguir en un `Numeric` suelto.

**No hace falta ninguna tabla ni columna extra para administración**: es una fila más, con
`origen = 'renegociacion'` en vez de `'indexacion'`.

### b · La migración: qué vigencia darle al valor que hay hoy

El problema es real y no tiene solución perfecta: **el escalar de hoy no dice desde cuándo vale.** Las
tres opciones que planteó Juan, con lo que implica cada una:

| Opción | Qué afirma | Qué implica para las liquidaciones pasadas |
|---|---|---|
| **A · vigencia abierta hacia atrás** `daterange(NULL, X)` | «esta tarifa aplicó desde siempre» | La consulta siempre responde, **pero puede responder mal y sin avisar**. Afirma algo que sabemos falso en los casos renegociados. Peor: cubre periodos anteriores al contrato |
| **B · desde la fecha del contrato** | «la tarifa no cambió desde la firma» | Es la misma afirmación falsa, acotada. Y **no es aplicable en la cuarta parte de los contratos**: `fecha_inicio` está al **18,6 %** (33 de 177) y `fecha_firma_contrato` al **73,4 %** (130). Unos 47 contratos no tienen ninguna de las dos |
| **C · marcada como origen desconocido** | «este es el valor actual; desde cuándo aplica, no se sabe» | La consulta responde **y la respuesta se sabe incierta**. Una liquidación puede detectar que está usando un valor migrado y marcar su propio resultado |

**Propongo C, combinada con B para la fecha.** Concretamente, por cada tarifa escalar de hoy:

⚠️ **Corregido el 2026-08-27 — Juan aprobó el borrado.** Este párrafo decía «combinada con la
recuperación de § c encima», y tenía un primer paso que reconstruía desde `audit_log` las filas con
`origen = 'renegociacion'`. **Ese paso ya no existe: se corrió la consulta y no hay nada que
reconstruir** (§ e). Todas las filas nacen con `origen = 'migracion'`.

1. **El valor actual del escalar** entra como **una fila con `origen = 'migracion'`** —todas, sin
   excepción—, cuya `nota` es obligatoria por CHECK y dice de dónde salió.
2. **El inicio de esa fila** es `fecha_inicio` → `fecha_firma_contrato` → y si no hay ninguna,
   `daterange(NULL, ...)`, abierta hacia atrás **pero etiquetada**.
3. ⚠️ **Un `0.0` no se migra como valor: se omite la fila.** No significa «tarifa cero», significa
   «todavía no lo lleno» (§ e, contrato 108). La regla completa, con su verificación, está en
   `06-plan-migracion.md` Fase 6.

La diferencia con la opción A no es el rango: **es que la incertidumbre queda en el dato**, no en la
cabeza de quien lo consulta. `origen = 'migracion'` es consultable, tiene su índice parcial, y una
liquidación de un periodo cubierto por una fila así puede decir «este número usa una tarifa cuya vigencia
no está confirmada» en vez de presentarlo como un hecho.

⚠️ **Lo que ninguna opción arregla:** si una tarifa se renegoció **antes** del 2026-05-19 y nadie lo
anotó, ese valor no existe en ninguna parte. Ver § c.

### Dónde quedó escrito

`03-esquema.sql` (tabla + 2 enums + 3 índices, validado: 37 tablas, orden de dependencias correcto),
`02-modelo.md` (ER y cardinalidades) y `04-mapeo.md` §F (qué se migra y cómo se convierte cada JSONB).
**La Fase 6 sigue esperando**: esto es diseño, no implementación.

### c · Qué histórico se puede recuperar, y qué es irrecuperable

Busqué en las cuatro fuentes posibles. **Hay una que sirve y sirve bastante.**

#### ✅ `audit_log` — la fuente real

| Hecho | Verificado en |
|---|---|
| **`contratos_servicio` está auditada**, y desde el primer día | `app/services/audit.py:20-31`, `_AUDITED_TABLES` |
| Guarda `{campo: {old, new}}` por UPDATE, con usuario y timestamp | `_diff_attrs()` + la columna `cambios` JSONB |
| La auditoría arrancó el **2026-05-19** | `git log --diff-filter=A -- app/services/audit.py` |
| Tiene **12 765 filas** y `cambios` al **99,9 %** | `uso_real.json`, medición del 2026-08-23 |
| **No hay política de retención ni purga** — nada borra lo viejo | grep sobre `app/` |

O sea: **todo cambio de `tarifa_admin`, `tarifa_cgm` o `tarifa_representacion` hecho desde el 2026-05-19
por la API es recuperable**, con su valor anterior, su valor nuevo, quién lo hizo y cuándo. Son unos tres
meses de historia real, no una estimación.

La consulta que lo extrae —**para correr contra producción, no la corrí**:

```sql
SELECT registro_id AS contrato_id, created_at, usuario_nombre,
       cambios -> 'tarifa_admin'          AS admin,
       cambios -> 'tarifa_cgm'            AS cgm,
       cambios -> 'tarifa_representacion' AS representacion
  FROM audit_log
 WHERE tabla = 'contratos_servicio'
   AND accion = 'UPDATE'
   AND (cambios ? 'tarifa_admin' OR cambios ? 'tarifa_cgm' OR cambios ? 'tarifa_representacion')
 ORDER BY registro_id, created_at;
```

Su resultado decide cuántas filas de la migración son reales y cuántas quedan como `'migracion'`.

#### ⚠️ Las otras tres fuentes: poco o nada

| Fuente | Veredicto |
|---|---|
| **Los JSONB `indexacion_*`** | Sirven para CGM (67,8 % lleno), representación y canon (22,6 %). **Para administración, no existe ninguno.** Es la asimetría que originó la pregunta |
| **`fecha_indexacion` / `indice_indexacion`** | Inservibles: **0 %** y **0,6 %** de llenado — un contrato de 177. Los campos existen y nadie los llenó |
| **`enlace_drive`** (actas y contratos en Drive) | **70,1 %** de los contratos tienen enlace. Es la única vía para lo anterior a mayo, pero **no es automatizable**: alguien tiene que abrir el documento y leer la tarifa. Sirve para los casos que importen, no para una migración masiva |
| **La historia de git del seed** | 5 commits tocaron `tarifa_admin` en `app/main.py`. Pero el seed **solo inserta, nunca actualiza** — si un valor cambió después por la UI, el seed no se enteró. Sirve para saber el valor *inicial* declarado, no la trayectoria |

#### 🛑 Lo irrecuperable, dicho sin rodeos

**Cualquier renegociación anterior al 2026-05-19 que solo haya vivido en la columna escalar está
perdida.** No hay backup de esos valores, no hay JSONB para administración, `fecha_indexacion` está
vacía, y el seed no registra actualizaciones.

Y hay un segundo hueco más chico: **la auditoría arranca *después* de los seeds.** `init_audit()` está en
`app/main.py:3408` y `_run_cgm_seed` en `:3386`, así que **lo que escriben los seeds no queda auditado**.
La carga inicial de tarifas de Cedillanos y Sabana de Torres del 2026-08-25, por ejemplo, no dejó rastro
en `audit_log`. Para esas el valor de hoy *es* el valor inicial, así que no se pierde nada — pero conviene
saberlo antes de leer `audit_log` como si fuera completo.

### d · ✅ Confirmado: el diseño ahora **sí** impide sobrescribir — no lo hacía

Juan pidió confirmarlo, y la respuesta honesta es que **el diseño anterior no lo impedía**. El `EXCLUDE`
prohíbe dos vigencias solapadas, pero **nada impedía un `UPDATE contrato_tarifas SET valor = ...`** sobre
una fila existente — que es exactamente cómo se pierde la historia hoy en la columna escalar. Habría sido
el mismo bug con otra forma.

Se cierra con `fn_tarifa_append_only()`, un trigger `BEFORE UPDATE OR DELETE` que hace la tabla
**append-only**:

| Operación | Resultado |
|---|---|
| Cambiar `valor`, `unidad`, `concepto`, `contrato_id` u `origen` | **rechazada** — *«Renegociar = cerrar la vigencia de la fila actual e INSERTAR una fila nueva»* |
| Cambiar el **inicio** de la vigencia | **rechazada** |
| Cerrar el **fin** de una vigencia abierta | **permitida** — es la mitad legítima de una renegociación |
| Modificar el fin de una vigencia **ya cerrada** | **rechazada** |
| `DELETE` | **rechazada** — *«si se cargó por error, se ANULA»* |
| Anular (`anulada_en`, `anulada_motivo`, `anulada_por_id`) | **permitida** — y las anuladas salen del `EXCLUDE`, que ahora es parcial (`WHERE anulada_en IS NULL`) |

**Entonces una renegociación son dos operaciones en una transacción, y no hay tercera vía:** cerrar la
vigencia de la fila viva e insertar la nueva. El valor anterior **no se puede borrar ni editar**, que es
literalmente el requisito.

Un error de carga tampoco borra: se anula, con motivo y autor, y la fila sigue ahí. El histórico completo
se mantiene incluso cuando lo que se registró estaba mal.

⚠️ **Costo:** es el cuarto trigger del modelo objetivo (con los tres de D-21) en una base que hoy tiene
cero. La alternativa —confiar en que la aplicación no haga `UPDATE`— es exactamente la que produjo el bug
que estamos cerrando.

### e · ✅ 2026-08-27 · La consulta del §c, corrida contra producción: **no hay histórico recuperable**

Juan la corrió. Salida completa en `esquema-bd-produccion/historico_tarifas.txt`.

| | |
|---|---|
| Filas | **25** |
| Contratos distintos | **23** |
| Ventana | **2026-08-24 17:00:35 → 21:09:45 UTC** (12:00 → 16:09 hora Colombia). **Un solo día** |
| `usuario_nombre` | **NULL en las 25** |
| Cambios de valor reales | **4 filas, 4 contratos** |
| Diffs que no cambiaron nada | **22 de 25** |

**Conclusión: la hipótesis de recuperar renegociaciones desde `audit_log` se cae.** No hay ni una sola
fila fuera del 2026-08-24, así que entre el 2026-05-19 (arranque de la auditoría) y hoy **ninguna tarifa
escalar cambió de valor por el ORM**, salvo los primeros llenados de ese día. El §c decía «unos tres
meses de historia real»: **la ventana existe, pero está vacía**.

#### Los 22 diffs fantasma: `{"antes": 0.038, "despues": 0.038}`

No es un script de reescritura masiva. Es un artefacto de comparación, y la cadena está verificada de
punta a punta:

1. `RepresentacionView.vue:458-473` arma el payload del `PATCH` con **las tres tarifas siempre incluidas**,
   toque el usuario el campo o no. Además hace `tarifa_admin × 100` al abrir el diálogo y `÷ 100` al
   guardar — el redondeo es limpio (`0.038*100/100 == 0.038`), así que **el valor que viaja es idéntico**.
2. El esquema Pydantic las declara `Optional[float]` (`app/schemas/contratos_servicio.py:125-127`), así
   que llegan como `float`.
3. `update_contrato` (`app/api/v1/contratos_servicio.py:278`) usa `exclude_unset=True` — pero el campo
   **sí vino en el body**, así que cuenta como set y se asigna.
4. La columna es `Numeric(8,4)` (`app/models/contratos.py:123`), así que el valor cargado es
   `Decimal('0.0380')`. En `_diff_attrs` (`app/services/audit.py:86`) la comparación es
   `old != new` sobre los valores crudos, y **`Decimal('0.0380') != 0.038` es `True`** en Python.
5. `_serialize` castea el `Decimal` a `float`, y los dos lados salen `0.038`.

**Por qué solo pasa con `tarifa_admin`:** 0.038 no es representable exacto en binario. Los valores de
`tarifa_cgm` y `tarifa_representacion` que hay en los datos —5.0, 7.0, 3.0, 6.0, 0.0— sí lo son, y
`Decimal('5.000000') != 5.0` da `False`. Por eso las 22 filas fantasma son todas del mismo campo.

⚠️ **Deuda que esto abre, y no es del refactor:** cada guardado de un contrato de representación escribe
una fila de auditoría que afirma un cambio de tarifa que no ocurrió. Ensucia la única fuente histórica
que hay. El arreglo es de una línea —comparar `_serialize(old) != _serialize(new)` en vez de los valores
crudos— y conviene hacerlo **antes** de que `contrato_tarifas` exista, porque el mismo patrón va a
alimentar el `origen` de las filas nuevas.

#### `usuario_nombre` NULL en las 25: la atribución está rota, no es un script

El §c daba por hecho que `audit_log` guarda «quién lo hizo». **No lo hace.** El ritmo de las 25 filas
—intervalos irregulares de 1 a 3 minutos a lo largo de una tarde de trabajo— es de una persona guardando
formularios uno por uno, no de un bucle. Lo que falla es la propagación del autor:

- `set_audit_user()` solo se llama desde `get_current_user` (`app/api/v1/auth.py:41-54`), que es una
  dependencia **síncrona** (`def`).
- FastAPI ejecuta las dependencias `def` y los endpoints `def` con `run_in_threadpool`, y **cada llamada
  recibe una copia del contexto**. Un `ContextVar` escrito dentro de la dependencia muere con esa copia.
- Verificado con el `starlette`/`anyio` de este repo: dependencia `def` que hace `v.set((7,'Juan'))` +
  endpoint `def` que hace `v.get()` → el endpoint lee **`(None, None)`**.

O sea: **toda escritura hecha desde la API queda con `usuario_id` y `usuario_nombre` en NULL**, en las 10
tablas auditadas, desde el 2026-05-19. Lo único que sí queda atribuido son los seeds de arranque desde el
2026-08-26 (`'sistema (seed de arranque)'`), porque `_run_init_audit` corre en el mismo hilo y contexto
que ellos (`app/main.py:3369-3389`).

**Consecuencia para leer la ventana:** un NULL **no** significa «lo hizo un script». No significa nada.
La columna es inservible tal como está, y arreglarla es cambiar la dependencia a `async def` o mover el
`set_audit_user` a un middleware.

#### El contrato 108, tres guardados en 3 minutos

`20:38:40`, `20:40:24`, `20:41:30`. Los dos primeros solo traen el fantasma de `tarifa_admin`: alguien
abrió el formulario y guardó sin cambiar nada. El tercero trae, además, `tarifa_cgm` y
`tarifa_representacion` de **`0.0` a `5.0`**.

**No es una renegociación.** El `"antes"` es `0.0`, no un precio anterior: es un cero de relleno que se
corrigió al tercer intento. Lo mismo, en su versión limpia, con los contratos 1, 2 y 205, donde el
`"antes"` es `null` — primer llenado de un campo vacío.

⚠️ **Y deja una advertencia para la migración:** en este modelo **`0.0` no significa «tarifa cero», significa
«todavía no lo lleno»**. Antes de migrar hay que contar cuántos contratos siguen con `0.0` en alguna de las
tres columnas y decidir si esas filas entran a `contrato_tarifas` o se quedan fuera. Una fila de tarifa que
afirma «vale 0» es peor que la ausencia de fila, porque una liquidación la usa sin dudar.

#### Qué queda para el mapeo

**Las 25 filas no aportan ni una vigencia.** Ninguna registra un valor anterior que hoy no esté en la
columna: 22 no cambiaron nada, 3 son `null → valor` y 1 es `0.0 → valor`. En los cuatro casos el valor
posterior **es el que está hoy en el escalar**.

Entonces el §b se aplica sin la parte de recuperación: **todas** las filas de `contrato_tarifas` nacen con
`origen = 'migracion'`, con la cascada `fecha_inicio` → `fecha_firma_contrato` → rango abierto etiquetado,
y ninguna con `'renegociacion'`. El paso 1 del §b —«lo que `audit_log` sí sabe se reconstruye como filas
reales»— queda **sin insumo**, y hay que borrarlo del plan de la Fase 6 en vez de dejarlo como trabajo
pendiente que nadie va a poder hacer.

Lo único que la salida sí prueba, y que vale conservar como nota: **las tarifas de representación se
cargaron el 2026-08-24**, así que para esos 23 contratos el escalar de hoy tiene a lo sumo tres días menos
de antigüedad que la fecha del contrato. No es una vigencia, es una cota.

#### Corroboración lateral del `unidad` obligatoria (§ del 🛑)

`RepresentacionView.vue` multiplica `tarifa_admin` por 100 para mostrarla y divide al guardar; a
`tarifa_cgm` y `tarifa_representacion` no les hace nada. Es la confirmación en el código de lo que el
🛑 dedujo de los datos: **administración es una fracción, las otras dos no.** `unidad` no es opcional.

#### ✅ 2026-08-27 · Medido en producción: el bug de atribución, confirmado

Salida en `esquema-bd-produccion/verificacion_auditoria_ceros.txt`.

| Autor | Filas | Tablas | Ventana |
|---|---|---|---|
| `(NULL)` | **13 303** | **9** | 2026-05-19 → 2026-08-27 |
| `sistema (seed de arranque)` | 50 860 | 1 | 2026-08-27 → 2026-08-27 |
| **un autor real** | **0** | — | — |

**Cero filas con autor real en tres meses.** El reparto por tabla —`fallas` 10 363, `proyectos` 885,
`reporte_energia_generacion` 617, `reporte_energia_consumo` 471, `contratos_servicio` 345,
`liquidaciones` 309, `clientes` 137, `ppa_contratos` 120, `fronteras` 56— confirma que no es un
endpoint suelto: es toda la API. Arreglado pasando el autor en la sesión en vez del `ContextVar`
(`app/services/audit.py`, `app/api/v1/auth.py`), con `tests/test_audit_atribucion.py` de regresión.

**Por qué ningún test lo detectó en tres meses:** `tests/conftest.py` reemplaza el módulo
`app.api.v1.auth` completo por un stub, así que `get_current_user` no se ejecuta nunca en la suite.

⚠️ **Corrección del 2026-08-27, mismo día:** una versión anterior de este párrafo decía que
`liquidaciones.py` y `panel_contable.py` tenían «13 rutas de escritura sin dependencia de auth» y que
sus filas seguirían en NULL. **Es falso, y el error era del grep**, que solo reconocía
`get_current_user` y `_require_admin`. Las 13 dependen de `_require_liquidaciones_write` y
`_require_write`, que envuelven a `get_current_user` y **además** exigen rol
(`admin`/`liquidaciones`). Resuelto el cierre transitivo, **las únicas rutas de escritura sin auth en
los 48 routers son las 4 de `auth.py`** —`/token`, `/token/mobile`, `/forgot-password`,
`/reset-password`—, que son públicas por definición. No hay hallazgo de control de acceso, y esas 13
rutas **sí quedan atribuidas** con este arreglo, porque `get_current_user` corre como
sub-dependencia.

#### ⚠️ 2026-08-27 · Las 50.860 filas firmadas por el arranque — sin causa confirmada

Una sola tabla, un solo día, y `fallas` deja de tener filas NULL justo el 2026-08-26, que es cuando se
movió `init_audit` antes de los seeds. Todo apunta a que el cambio de orden **destapó** escrituras de
arranque que antes no se auditaban, pero **qué tarea las produce no está determinado**, y no se puede
determinar leyendo el código: son 22 tareas y varias recorren tablas auditadas fila por fila.

Lo que sí se hizo, porque era la causa de no poder saberlo: **el rótulo dejó de ser único.**
`_run_init_audit` ya no firma nada, y `_deferred_init` firma cada tarea con su nombre
(`sistema (startup: cgm_seed)`, `sistema (startup: fallas_tipo_backfill)`, …), y al terminar los seeds
limpia la firma para que el scheduler no herede el rótulo de arranque. En el próximo deploy, el mismo
corte por autor dice cuál fue.

Para el ruido de ahora, `esquema-bd-produccion/diagnosticar_ruido_seed.py` da la tabla, los campos, las
ráfagas por minuto —que dicen si fue un arranque o veinte— y diez ejemplos de `cambios`. ⚠️ **Si esos
ejemplos salen con `{"antes": X, "despues": X}`, buena parte del ruido es el mismo diff fantasma de este
apéndice**, y el arreglo de `_diff_attrs` lo baja sin tocar ninguna tarea.
