# 01 · Decisiones de diseño

**Qué es esto:** cada decisión del modelo objetivo con las opciones que consideré, la que elegí y el
trade-off que acepté. Las marcadas **⚠️** son las que no tengo cerradas o donde el trade-off es discutible.
**Criterio general:** lo que ya funciona no se toca. Cuatro decisiones grandes cambian respecto del plan
inicial, y una queda **abierta a tu confirmación** (D-06, frontera).
**Cómo leerlo:** las ⚠️ primero — son D-01, D-03, D-04, D-06, D-09, D-11, D-13, D-16.

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
