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
