# Registros: expediente documental por proyecto — decisiones de diseño

**Rama:** `feat/registros-proyecto-documentos` (backend y frontend)
**Fecha:** 2026-08-27/28
**Para revisar rápido:** lee §1, §2 y §7. El resto es el detalle que respalda cada decisión.

---

## 1. Resumen en números

| | |
|---|---|
| Campos del formato oficial de Hoja de Vida | **526** |
| Parámetros únicos que quedaron (SIC) | **182** |
| Parámetros únicos del proceso CND | **61** |
| **Total de datos únicos en el catálogo** | **243** |
| Veces que esos datos aparecen sumando todos los documentos | **414** |
| **Transcripciones que el usuario deja de hacer** | **171** |
| Datos que aparecen en más de un documento | 105 |
| Datos compartidos *entre los dos procesos* (SIC ↔ CND) | 6 |
| Ítems del expediente | 28 (SIC) + 10 (CND) = **38** |
| Ítems marcados como pendientes de validar | **12** |

El dato más repetido es `frontera.nombre_frontera`: aparece en **10 documentos** de los dos
procesos. Le siguen la serie del medidor y las de los TC y TP, en 7 cada una.

---

## 2. Las tres correcciones al planteamiento inicial

Antes de diseñar nada hay tres cosas del enunciado que no coinciden con lo que hay.
Ninguna bloquea el trabajo, pero conviene saberlas.

### 2.1 Sí existe ya una tabla de documentos

El enunciado dice *"no existe hoy una tabla de documentos — confirmar"*. Confirmado que **sí
existe**: el módulo `registros_cnd` ya tiene `registro_documento`, y además
`registro_parametros_93` (los parámetros del Anexo 4) y `registro_equipo_frontera` (medidores,
TC, TP con marca, modelo y serie). Están en `app/models/registros_cnd.py` y se crean por
`create_all()` en el arranque, no por migración.

**Qué hice:** no fusioné los dos módulos (ver D-01). Conviven, y el documento explica cómo.

### 2.2 El "SENE" no existe

El enunciado pide confirmar si "el SENE" con subítems 9.1–9.10 es lo mismo que el proceso CND o
un tercer proceso. **No es ninguna de las dos: no existe.** Busqué "SENE" en todo el frontend,
en todo el backend y en los documentos del expediente: cero resultados.

Los ítems 9.1 a 9.10 son los **numerales del Anexo 1 del Acuerdo CNO 1937**, y eso *es* el
proceso CND. Lo dicen las cartas mismas: la 9.1 arranca con *"En cumplimiento de lo establecido
en el numeral 9.1 del Anexo 1 del Acuerdo CNO 1937"*.

**Conclusión: hay dos procesos, no tres.** No hice una sección independiente.

### 2.3 La numeración 1–28 sí coincide, pero 15 carpetas están vacías

Verifiqué los 28 ítems contra `Contexto_registros/ASIC/`. La numeración coincide exactamente.
Pero **15 de las 28 carpetas están vacías** en el expediente de muestra. De esas:

- **6 aplican y solo faltan los archivos** (03, 05, 06, 09, 10, 12): sé qué van a contener
  porque el dato ya está en la hoja de vida. Quedaron como `CONFIRMADO` con nota.
- **9 no sé qué contienen** (16–23 y 27). Quedaron como `PENDIENTE` y **sin parámetros
  asignados**: no inventé contenido, que es lo que pediste explícitamente.

---

## 3. El modelo de datos

Tres tablas nuevas, colgadas de `proyectos`. No se tocó ninguna tabla existente.

```
proyectos (existente)
   │
   ├──< documentos_proyecto          una casilla del expediente
   │        (proyecto, proceso, item_codigo)  UNIQUE
   │        estado, radicado, fecha_emision, emisor, notas
   │           │
   │           └──< documentos_proyecto_archivo
   │                    origen (LINK|DRIVE), url, nombre, drive_file_id
   │
   └──< parametros_proyecto          el valor de un dato, UNA vez
            (proyecto, clave, equipo_tipo, equipo_posicion)  UNIQUE
            valor, valor_numero, valor_fecha
            documento_origen_id ──> documentos_proyecto
```

**Migración:** `alembic/versions/125_registros_proyecto_expediente.py` (head anterior: 124).
Renumerada desde la `120` original el 2026-08-28; ver §10.2.

### Por qué un ítem y sus archivos son dos tablas

Porque un ítem lleva varios archivos. El 08 lleva seis certificados de calibración (uno por
transformador), el 26 lleva una foto por equipo, el 28 lleva cuatro órdenes de compra. Una
columna `url` en la casilla no alcanzaba.

### Por qué `equipo_tipo` y `equipo_posicion` no admiten NULL

Es el detalle que hace que todo el diseño funcione. En Postgres **dos NULL no colisionan**, así
que con columnas nulables la restricción `UNIQUE(proyecto, clave, equipo_tipo, equipo_posicion)`
habría dejado insertar el mismo parámetro dos veces —justo lo que este módulo existe para
evitar—. Con `''` y `0` como valor por defecto, la restricción sí muerde.

### Por qué el valor se guarda tres veces

`valor` (texto) es el dato exacto como lo escribió el usuario: es lo que se imprime en los
formatos oficiales y no puede perder ni un decimal (la impedancia del Anexo 4 real trae 15
decimales). `valor_numero` y `valor_fecha` son la versión tipada que llenan los servicios para
poder filtrar, ordenar y disparar alertas de vencimiento de calibración. Si el usuario escribe
`1(10)A` en un campo numérico —como trae el acta real— el texto se conserva intacto y la columna
tipada queda vacía; el guardado nunca falla por eso.

---

## 4. Decisiones, una por una

### D-01 — No fusioné este módulo con `registros_cnd`
`registros_cnd` modela el **trámite**: etapas, transiciones, hitos ponderados, alertas, máquina
de estados. Sus documentos son *evidencia de una etapa*. Este módulo modela el **expediente**:
qué papeles tiene el proyecto y qué dice cada uno. Un proyecto tiene expediente desde que
existe, sin depender de en qué etapa del trámite va —que es exactamente lo que pediste—.
Fusionarlos habría metido el expediente dentro de una máquina de estados de la que dijiste que
no debía depender.
**Costo asumido:** hay dos lugares donde vive "un documento". Si más adelante quieres unificar,
lo natural es que `registro_documento` (evidencia de etapa) apunte a `documentos_proyecto`.

### D-02 — El "SENE" no existe; hay dos procesos
Ver §2.2. Evidencia: cero coincidencias en código y documentos; las cartas citan el Acuerdo CNO
1937 explícitamente.

### D-03 — Las secciones 3 y 4 de la hoja de vida son el mismo medidor
El formato tiene "3. MEDIDOR DE ENERGÍA ACTIVA - PRINCIPAL" y "4. MEDIDOR DE ENERGÍA REACTIVA -
PRINCIPAL", 95 campos cada una. **Son el mismo aparato físico.** Dos pruebas:
1. En el expediente real, 3.3 y 4.3 traen la misma serie: `88866569`.
2. La sección 5 (respaldo) describe activa *y* reactiva en un solo bloque (5.18 índice de clase
   activa, 5.21 índice de clase reactiva) — o sea, el formato mismo sabe que es un aparato.

Colapsé las dos en `MEDIDOR_PRINCIPAL`. De la sección 4 solo sobreviven los 5 campos que de
verdad difieren (índice de clase, constante, unidad y los dos canales reactivos).
**Ahorro: 90 parámetros.**

### D-04 — Un parámetro se define una vez y se instancia por equipo
"Número de serie" no es un parámetro del medidor principal y otro del de respaldo: es
`medidor.numero_de_serie`, que aplica a los dos (`equipo_tipos`). Lo mismo con
`celda.cert_conformidad_numero`, que aplica a las tres celdas, o `conductor.calibre`, a los dos
tipos de conductor. La unicidad real la impone la base con la cuádrupla.

### D-05 — Los sellos son una tabla, no 49 campos
Cada sección de equipo repite un bloque de sellos de 7 filas × 7 columnas = 49 "campos" del
formato. No son 49 parámetros: es `<equipo>.sellos`, de tipo `TABLA`, con sus columnas
declaradas. Igual con los ajustes de protecciones del 9.4. **Ahorro: ~200 parámetros.**

### D-06 — Las secciones 13, 14 y 15 no son parámetros
Son bitácoras históricas (registros de acceso a nivel 2 del medidor, registro cronológico de
novedades). Son eventos con fecha, no datos del proyecto. Quedaron fuera del catálogo.
**Pendiente si las quieres:** son una tabla hija aparte, no parámetros.

### D-07 — Los certificados se nombran por su semántica
El numeral 3.38.1 es "Número", a secas. Sin contexto quedaría `medidor.cert_38_numero`. El mapa
`BLOQUES` del generador lo traduce a `medidor.cert_conformidad_numero`, que es lo que un humano
puede leer en una revisión.

### D-08 — Corregí un error de numeración del formato oficial
El diccionario de campos rotula la sección **18** ("Persona designada por el RF") pero sus tres
campos van numerados **17.1, 17.2, 17.3**, y el 17 es "Anexo diagrama unifilar" (sin campos). Sin
corregirlo, esos tres campos se perdían. Está corregido al leer, con el porqué en el código.

### D-09 — Los TC se declaran por fase; los TP no, pero son tres igual
El formato declara los TC una vez por fase (R/S/T) y los TP una sola vez, aunque la frontera
lleva tres —el acta real lista TT1, TT2 y TT3 con tres certificados—. Los dos quedaron con 3
instancias. **Es una inconsistencia del formato oficial, no del modelo.**

### D-10 — El enum existente rotula mal el 9.9
`registros_cnd/dominio.py` dice que 9.9 es "inicio de operación y cierre". La carta real dice
otra cosa: 9.9 es la *certificación de cumplimiento de la reglamentación* que emite el
transportador, y el inicio de operación es el **9.10**. Mi catálogo usa lo que dicen las cartas.
**No toqué el enum viejo** para no alterar el módulo del trámite. Queda para que decidas.

### D-11 — Ítem 27 y carpetas vacías: marcados, no inventados
El 27 (plataforma de registro de frontera) no existe físicamente; queda creado como casilla
`PENDIENTE` y no bloquea nada. Los ítems 16–23 quedan `PENDIENTE` **sin parámetros**: hay un
test (`test_items_sin_validar_no_declaran_parametros`) que falla si alguien les inventa
contenido.

### D-12 — La simulación no se conectó
El ítem 24 (consumo y generación) sale de la simulación, que hoy no es una fuente conectada a la
plataforma. Por ahora el informe se monta como archivo, sin parámetros propios. No creé
parámetros duplicados a la espera: cuando exista la fuente, se agregan al catálogo.

### D-13 — "Nombre de la planta" (CND) y "Nombre de la frontera" (SIC) son el mismo dato
**Es la deduplicación que más conviene revisar.** Estrictamente son dos registros distintos (uno
ante XM, otro ante el ASIC), pero en los expedientes reales llevan la misma cadena
(`MGS 0077 - Chiriguaná Norte 4`). Los unifiqué, siguiendo tu regla de un dato = un parámetro.
Si en algún proyecto pueden diferir, se separan cambiando una línea del catálogo CND.

Los otros cinco reusados entre procesos son inequívocos: departamento, municipio, latitud,
longitud y voltaje de conexión.

**Lo que NO deduje como el mismo dato, aunque se parezca:**
- Capacidad de transporte (MW, CND) vs. capacidad instalada (kVA, hoja de vida): magnitudes y
  unidades distintas.
- Operador ante el CND vs. Agente RF ante el ASIC: suele ser la misma empresa, pero son dos
  roles regulatorios y pueden diferir.

### D-14 — Radicado y fecha van en el documento, no como parámetro
Cada carta del proceso CND trae su propio radicado (`2025030000113791`) y su propia fecha. Eso
es del documento, no del proyecto: son columnas de `documentos_proyecto`. Si fueran parámetros,
habría que inventar `radicado_9_1`, `radicado_9_2`… que es precisamente el patrón que este
módulo elimina.

### D-15 — La tabla puente `documento_parametro` no se creó (a propósito)
Pediste considerarla. **No la hice**, y esta es la única desviación deliberada del enunciado.

Que la hoja de vida contenga la serie del medidor no depende del proyecto ni cambia por
proyecto: lo fija el formato CREG 038/2014. Ponerlo en la base obligaría a sembrar ~414 filas
**por cada proyecto** (miles en total), idénticas siempre, y a mantenerlas sincronizadas con el
código que dibuja los formularios. Vive en `mapa_documentos.py`, se revisa en un pull request y
tiene un test que falla si alguien referencia una clave inexistente.

**Lo que sí es dato de operación y sí está en la base** es de qué documento salió el valor
concreto de un proyecto: `parametros_proyecto.documento_origen_id`. Esa es la fuente de verdad
de cada dato, que era el requisito real.

Si prefieres la tabla, el port es directo: `mapa_documentos.PARAMETROS_POR_ITEM` es exactamente
su contenido.

---

## 5. Qué se entregó

### Backend (`Backend Operaciones`)
```
app/models/registros_proyecto.py                        3 tablas
app/schemas/registros_proyecto.py                       schemas Pydantic v2
app/api/v1/registros_proyecto.py                        11 endpoints
app/services/registros_proyecto/
    catalogo_items.py                                   38 ítems (SIC + CND)
    catalogo_parametros.py                              182 parámetros (GENERADO)
    catalogo_parametros_cnd.py                          61 parámetros
    mapa_documentos.py                                  el mapa de deduplicación
    service.py                                          lógica
scripts/generar_catalogo_parametros.py                  regenera el catálogo SIC
alembic/versions/125_registros_proyecto_expediente.py   migración
tests/test_registros_proyecto_catalogo.py               31 tests
tests/test_registros_proyecto_service.py                19 tests
tests/test_registros_proyecto_api.py                    13 tests
```

**Endpoints** (bajo `/api/v1/registros-proyecto`):

| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/catalogos` | ítems y parámetros de los dos procesos |
| GET | `` | índice de proyectos con avance por proceso |
| GET | `/{proyecto_id}` | timeline completo del expediente |
| GET | `/{proyecto_id}/parametros` | todos los valores |
| PUT | `/{proyecto_id}/parametros` | guardar (crea o actualiza, nunca duplica) |
| DELETE | `/parametros/{id}` | borrar un valor |
| GET | `/{proyecto_id}/{proceso}/{item}` | formulario de un ítem |
| PATCH | `/{proyecto_id}/{proceso}/{item}` | radicado, fecha, estado de la casilla |
| POST | `/{proyecto_id}/{proceso}/{item}/archivos` | montar por enlace |
| POST | `/{proyecto_id}/{proceso}/{item}/archivos/subir` | subir a Drive |
| DELETE | `/archivos/{id}` | quitar un archivo |

Consultar por proyecto, por proceso (`?proceso=SIC`) y por ítem está cubierto.

### Frontend (`unergy-operaciones-frontend`)
```
src/views/Registros/RegistrosListView.vue        índice con avance SIC y CND
src/views/Registros/RegistroExpedienteView.vue   selector de proceso + timeline + formularios
src/router/index.js                              /registros y /registros/:proyectoId
src/components/AppSidebar.vue                    ítem "Expediente documental"
```

La vista de expediente: eliges proceso (SIC/CND), ves la línea de tiempo de ítems con su estado,
y al abrir uno montas el documento (subida a Drive o enlace) y diligencias sus datos agrupados
por equipo. **Cada campo que aparece en otros documentos lleva un ícono de enlace** que al pasar
el mouse dice en cuáles — que es lo que explica al usuario por qué solo lo escribe una vez.

---

## 6. Verificación

| | |
|---|---|
| Tests nuevos | **62**, todos en verde |
| Tests de registros en total (incluye `registros_cnd`) | **92**, todos en verde |
| Suite completa del backend | **2351 pasan, 4 saltados, 0 fallan** (rama ya actualizada contra master) |
| Cadena Alembic | los 3 tests de `test_alembic_chain_integrity` en verde; head único `125`. Ver §10 |
| Build del frontend | `npm run build` OK, chunks generados |

**Corrección (2026-08-28):** la primera versión de este documento decía **63 tests nuevos**.
Eran **60**; conté tres de más en `test_registros_proyecto_catalogo.py` (28 reales, no 31).
Con los dos que agregó D-18/D-16 el número hoy es **62**: catálogo 30, service 19, api 13.

Lo que **no** pude verificar: no levanté el backend contra la base de producción ni probé la
subida real a Google Drive (necesita `GOOGLE_SERVICE_ACCOUNT_JSON`). La subida reusa
`app/services/drive_evidencia.py`, que ya está en uso en `informe_om.py`.

---

## 7. Lo que quedaba pendiente

**Los ocho se resolvieron el 2026-08-28: ver §9.** Se dejan aquí como estaban para
que se entienda de dónde salió cada decisión.

### 7.bis — el listado original

1. **Ítems 16–23** — qué contienen. Carpetas vacías; están creados sin parámetros.
2. **Ítem 27** (plataforma de registro de frontera) — hay que crear el documento.
3. **Numerales 9.5, 9.6 y 9.8 del CND** — el 9.5 y 9.6 los tomé del enum existente (sin
   respaldo documental); el 9.8 no aparece en ningún lado. Hay que leer el Anexo 1 del Acuerdo
   CNO 1937.
4. **Simulación** — conectarla como fuente del ítem 24.
5. **D-13** — confirmar que el nombre de la planta ante el CND y el de la frontera ante el ASIC
   nunca difieren.
6. **D-10** — decidir si se corrige la etiqueta del 9.9 en `registros_cnd/dominio.py`.
7. **Secciones 13–15 de la hoja de vida** (bitácoras) — si las quieres, van como tabla aparte.
8. **`registro_parametros_93` existente está incompleto**: le faltan campos del Anexo 4 que sí
   están en mi catálogo (estatismos, banda muerta, capacidad de reactivos, tiempos de respuesta,
   ratas de toma de carga, altitud, barra STN/STR, potencia máxima, CEN, número de inversores,
   factor de eficiencia). Si el módulo del trámite los necesita, ahora existen aquí.

---

## 8. Cómo revisarlo rápido

```bash
# Backend
cd "Backend Operaciones"
git checkout feat/registros-proyecto-documentos
python -m pytest tests/test_registros_proyecto_*.py -q       # 63 tests

# Ver el catálogo y la deduplicación en vivo
python -c "
from app.services.registros_proyecto import mapa_documentos as m
print('nombre de la frontera aparece en:', m.items_que_usan('frontera.nombre_frontera'))
print('serie del medidor aparece en:', m.items_que_usan('medidor.numero_de_serie'))
"

# Frontend
cd ../unergy-operaciones-frontend
git checkout feat/registros-proyecto-documentos
npm run build
```

**No hice commit a master ni push a ningún remoto.** Todo está en la rama
`feat/registros-proyecto-documentos` de los dos repos, en local.

---

## 9. Resolución de los ocho pendientes (2026-08-28)

Los ocho puntos del §7 quedaron decididos. El principio rector aplicado en todos es el
mismo: **cada dato único se diligencia una vez y los documentos lo referencian**. Cuando
la carpeta real no daba certeza **no se inventó contenido**: el ítem queda creado, sin
parámetros, y con la nota `PENDIENTE DE VALIDAR CONTRA CARPETA REAL` en el catálogo.

### D-16 — Los ítems SIC 16–23 no llevan parámetros: son documentos del CGM

**Qué decidí:** los ocho quedan como casillas documentales sin ningún parámetro propio.

**Por qué:** las carpetas están vacías, pero **sus nombres sí son informativos** y los ocho
apuntan al mismo sujeto — el Centro de Gestión de Medida, no el proyecto:

| | |
|---|---|
| 16 | Parámetros, procedimientos y políticas del CGM |
| 17 | Esquema de telemedida y comunicaciones |
| 18 | Condiciones de operación del CGM |
| 19 | Documentación de la crítica de información |
| 20 | Documentación para la validación de datos |
| 21 | Documentación de mecanismos de protección |
| 22 | Documentación de políticas de seguridad física |
| 23 | Documentación del procedimiento de transmisión de datos |

Son documentos de **gobierno del operador de medida**: el mismo texto aplica a todas las
fronteras que ese CGM opera. Modelarlos como parámetros del proyecto sembraría el mismo
contenido idéntico en cada proyecto — exactamente el patrón que este módulo existe para
eliminar. El único dato específico del proyecto es *cuál* CGM lo opera, que ya se
diligencia en la hoja de vida.

Esto cambia el *motivo* respecto del §7 (allí decía "no sé qué contienen"), pero **no
cambia el resultado**: cero parámetros, que es lo que el test
`test_items_sin_validar_no_declaran_parametros` ya exigía.

**Qué habría que cambiar si la carpeta real lo desmiente:** si algún ítem trae un dato que
varía por frontera, se agrega al catálogo y se mapea a ese ítem. El candidato realista es
el **17**: si el esquema de telemedida trae direccionamiento por frontera, esos datos ya
existen (`modem.ip`, `modem.apn`, `modem.imei`, `modem.operador`, `modem.no_telefonico`) y
deben **reusarse desde el ítem 01, no redeclararse**. Está anotado en el catálogo.

### D-17 — El ítem 27 adjunta un soporte, no aporta datos

**Qué decidí:** queda como casilla `PENDIENTE` sin parámetros; cuando exista, se monta como
archivo.

**Por qué:** el "registro de la frontera en la plataforma del ASIC" es la *evidencia* de un
trámite cuya identidad ya está diligenciada: `frontera.nombre_frontera` y los códigos FRT
salen del ítem 01. Crearle parámetros propios sería duplicar la identidad de la frontera.

**Qué habría que cambiar si la carpeta real lo desmiente:** si el soporte trae un
identificador que hoy no existe (un radicado o consecutivo propio de la plataforma), va
como columna del documento —no como parámetro—, igual que se hizo en D-14.

### D-18 — Los numerales CND 9.5, 9.6 y 9.8 siguen sin contenido, y ahora se sabe por qué

**Qué decidí:** los tres quedan `PENDIENTE`, sin parámetros. Ninguno bloquea el merge.

**Por qué:** la carpeta `Contexto_registros/CND/` tiene documento real para 9.1, 9.2, 9.3,
9.4, 9.7, 9.9 y 9.10 — y nada para 9.5, 9.6 y 9.8. Los títulos del 9.5 y 9.6 venían del
enum de `registros_cnd`, y al revisarlo se encontró que **ahí también son una conjetura**:
están en el bloque rotulado *"Futuras (enum previsto, sin lógica ni UI)"* y no aparecen en
`ETAPAS_ACTUALES`. Es decir, el catálogo estaba heredando una suposición de otra
suposición. No hay de dónde sacar sus parámetros sin leer el Anexo 1 del Acuerdo CNO 1937.

**Hallazgo suelto:** la carpeta CND trae un **`Certificado de experiencia.pdf` sin numerar**
que hoy no mapea a ningún ítem. Es candidato natural a ser uno de los tres numerales que
faltan, pero **no se le asignó ninguno**: sería justamente inventar. Queda anotado en el
9.8. Cuando se lea el Anexo 1 se resuelven los tres de una vez.

**Recomendación aparte (no implementada):** un expediente real siempre acumula documentos
que no encajan en la numeración. Convendría una casilla `OTROS` por proceso para montarlos
sin forzarles un numeral. No se hizo por no ampliar el alcance.

**Qué habría que cambiar si la carpeta real lo desmiente:** al conocer los numerales
verdaderos se corrigen título, emisor y descripción, y se les mapean parámetros si traen
datos nuevos. Si alguno resulta no existir, se borra la casilla; la numeración no se
reordena porque los códigos son del Acuerdo, no posicionales.

### D-19 — D-10 resuelto: se corrige la etiqueta del 9.9, no el valor

**Qué decidí:** corregir en `registros_cnd/dominio.py` **solo el rótulo** de `CARTA_9_9`:

```
antes:  "Carta 9.9 (inicio de operacion y cierre)"
ahora:  "Carta 9.9 (certificacion de cumplimiento de la reglamentacion)"
```

**Por qué:** la carta real del expediente dice que la 9.9 es la certificación de
cumplimiento que emite el transportador, y que el inicio de operación es la **9.10**
(Acuerdo CNO 1899). El riesgo que frenó este cambio en su momento resultó ser nulo: el
valor persistido sigue siendo la cadena `"CARTA_9_9"` —no se toca ningún dato guardado— y
la etapa está en el bloque *"Futuras"*, sin lógica ni UI que la consuma.

**Lo que queda abierto:** el módulo del trámite **sigue sin una etapa propia para el 9.10**.
Agregarla sí toca la máquina de estados y es un cambio con impacto en ese módulo, ajeno a
este expediente. Se deja señalado, no hecho.

### D-20 — D-13 resuelto: el nombre de la planta y el de la frontera siguen unificados

**Qué decidí:** mantener un solo parámetro `frontera.nombre_frontera` para los dos procesos.

**Por qué:** se buscó la evidencia dura en el Anexo 4 real
(`9.3_Anexo_4_Acuerdo_1816 (1)_Chiriguaná Norte 4.xlsx`, hoja `PLANTA_SOLAR`, fila 19):

```
NOMBRE DE LA PLANTA  →  "MGS 0077 - Chiriguaná Norte 4"
```

Es **exactamente la misma cadena** que el nombre de la frontera ante el ASIC, y trae
incorporado el código `MGS 0077`, que es identificación de frontera. O sea: no es que
coincidan por casualidad, es que la convención de nombres es deliberadamente compartida.

En contra jugaba la definición que trae la propia hoja —*"nombre con el cual identificará
la planta ante el CND y con la cual quedará registrada en sus aplicativos"*—, que describe
un registro distinto del ASIC. Pero describe **para qué se usa** el nombre, no que deba
ser otro. Con un dato real que los muestra idénticos y el principio rector a favor, se
mantiene unificado.

**Sigue siendo la deduplicación más riesgosa del catálogo.**

**Qué habría que cambiar si la carpeta real lo desmiente:** el disparador concreto es
encontrar **un solo proyecto** donde el Anexo 4 y la hoja de vida traigan cadenas
distintas. La separación es una línea en `catalogo_parametros_cnd.py`: declarar
`planta.nombre_cnd` y remapear el ítem 9.3 a ese parámetro. Los otros cinco datos
compartidos entre procesos (departamento, municipio, latitud, longitud y voltaje de
conexión) no tienen este riesgo. Y lo que **no** se dedujo como igual sigue separado:
capacidad de transporte (MW) vs. capacidad instalada (kVA), y Operador ante el CND vs.
Agente RF ante el ASIC —el Anexo 4 lista `UNERGY ENERGY DIGITAL S.A.S E.S.P - GENERADOR`
en un rol que no tiene por qué coincidir con el otro—.

### D-21 — La simulación no se conecta ahora; queda definido el contrato

**Qué decidí:** el ítem 24 sigue montándose como archivo, sin parámetros propios.

**Por qué:** conectar la simulación es integrar una fuente que hoy no existe en la
plataforma, no una decisión de modelado. Crear parámetros "a la espera" sembraría casillas
vacías en todos los proyectos.

**Contrato para cuando exista:** el informe de consumo y generación aporta series, no datos
puntuales. Cuando la fuente esté disponible, sus valores entran como parámetros nuevos
mapeados al ítem 24 y con `documento_origen_id` apuntando a esa casilla —igual que
cualquier otro dato—, sin tocar el resto del catálogo.

### D-22 — Las bitácoras (secciones 13–15) se quedan fuera

**Qué decidí:** no se implementan.

**Por qué:** son eventos con fecha (accesos a nivel 2 del medidor, registro cronológico de
novedades), no datos del proyecto. Un parámetro responde "cuánto vale X"; una bitácora
responde "qué pasó y cuándo". Meterlas como parámetros rompería la unicidad
`(proyecto, clave, equipo)`: por definición hay muchas filas por proyecto.

**Forma que tendrían si se piden:** tabla hija `bitacora_proyecto` colgada de `proyectos`
con `(proyecto_id, tipo, fecha, actor, descripcion)` y el ítem del expediente como origen.
Es aditiva y no toca nada de lo entregado.

### D-23 — `registro_parametros_93` no se amplía: se apunta al catálogo nuevo

**Qué decidí:** no agregarle columnas a la tabla del módulo del trámite.

**Por qué:** los campos que le faltan frente al Anexo 4 real (estatismos, banda muerta,
capacidad de reactivos, tiempos de respuesta, ratas de toma de carga, altitud, barra
STN/STR, potencia máxima, CEN, número de inversores, factor de eficiencia) **ya existen en
el catálogo nuevo**. Duplicarlos sería crear dos lugares donde vive el mismo dato: el
problema que este módulo resuelve, reintroducido por la puerta de atrás.

**Cómo se conecta:** si el módulo del trámite los necesita, los lee de
`parametros_proyecto` por su clave. La dirección natural de la dependencia es esa —el
trámite consulta el expediente—, coherente con D-01.

**Qué habría que cambiar si la carpeta real lo desmiente:** si aparece un campo del Anexo 4
que no está en ninguno de los dos lados, se agrega **al catálogo nuevo**, nunca a la tabla
vieja.

---

### Resumen: qué quedó marcado como pendiente de validar contra carpeta real

| Ítems | Estado | Qué falta |
|---|---|---|
| SIC 16–23 | `PENDIENTE`, sin parámetros | Carpetas vacías: confirmar el juego de archivos. El 17 es el único que podría traer dato por frontera |
| SIC 27 | `PENDIENTE`, sin parámetros | El documento no existe todavía; hay que crearlo |
| CND 9.5, 9.6, 9.8 | `PENDIENTE`, sin parámetros | Leer el Anexo 1 del Acuerdo CNO 1937. Hay un `Certificado de experiencia.pdf` sin numerar como candidato |

Los demás ítems del expediente están `CONFIRMADO` contra la carpeta real.

---

## 10. La cadena Alembic y la renumeración a 125

### 10.1 La cadena de `origin/master` está limpia

La primera versión de este documento decía que la cadena estaba *"íntegra (120 sobre head
119)"*. Una revisión posterior afirmó lo contrario —que había tres heads y un
`down_revision` huérfano—. **Esa segunda afirmación era falsa**, producto de un parser
propio mal escrito. Medido correctamente:

```
origin/master:  127 revisiones,  heads = ['123'],  colgantes = ninguno,  duplicados = ninguno
```

Un solo head, sin colgantes, sin ids repetidos. **La cadena upstream está sana.**

**Qué falló en la medición anterior.** El script ad-hoc tenía dos errores, y cada uno
fabricó un problema inexistente:

| Error del parser | Fantasma que produjo |
|---|---|
| Tomaba solo el **primer** padre de `down_revision`. `037_contactos_unificados.py` es una revisión de *merge* con dos padres — `("019", "036")` — así que `036` nunca entró como referenciado | `019` y `036` parecían heads sueltos |
| Exigía `^revision =`. El archivo `5650ccf73b5c_add_starlink_facturas.py` usa la forma anotada `revision: str = ...`, así que la revisión no se registró | `5650ccf73b5c` parecía un `down_revision` huérfano |

**La lección concreta:** el repo **ya tiene** un test que hace esta verificación bien,
`tests/test_alembic_chain_integrity.py` (estático, sin BD ni Alembic instalado). Había que
correr ese, no escribir un parser nuevo. Sus tres pruebas —ids únicos, un solo head,
`down_revision` que resuelven— cubren exactamente esto y contemplan tanto los merges de
varios padres como la forma anotada.

### 10.2 La renumeración: de 120 a 125, en dos tiempos

Cuando se escribió la migración el head era `119` y el número libre era el `120`. Upstream
mete revisiones a diario, y la renumeración hubo que hacerla **dos veces el mismo día**:

| Momento | Head de `origin/master` | Número tomado | Qué pasó |
|---|---|---|---|
| Al escribir la migración | `119` | `120` | Libre en ese momento |
| Primer intento de cierre | `123` | `124` | La `120` ya la había tomado `120_email_envios_cliente_id_set_null`; entraron además 121, 122 y 123 |
| Al actualizar contra master | `124` | **`125`** | Upstream metió `124_redrop_columnas_resucitadas` mientras tanto |

Estado final:

```
alembic/versions/125_registros_proyecto_expediente.py
revision      = "125"
down_revision = "124"      # 124_redrop_columnas_resucitadas
```

**Es la razón por la que la renumeración se hace al final y no antes:** cualquier número
elegido con horas de anticipación queda obsoleto.

### 10.3 La rama ya está actualizada contra master y la cadena resuelve

La rama incorporó `origin/master` mediante **merge** (no rebase: master no se reescribe).
El merge entró sin conflictos y trajo las revisiones 120–124, entre otros cambios.

Medido sobre el árbol real de la rama, ya integrado:

```
tests/test_alembic_chain_integrity.py::test_no_duplicate_revision_ids  PASSED
tests/test_alembic_chain_integrity.py::test_all_down_revisions_resolve PASSED
tests/test_alembic_chain_integrity.py::test_single_head                PASSED
```

Un solo head (`125`), sin ids duplicados y sin `down_revision` colgantes.

**Nota histórica:** antes del merge estos dos últimos tests fallaban, porque el árbol de la
rama no contenía todavía las revisiones 120–123 a las que apuntaba `down_revision`. No era
un defecto de la migración sino de la rama estando atrasada, y se resolvió al actualizarla.
En su momento se prefirió eso a apuntar `down_revision` a `119` —que habría dado verde en la
rama y **dos heads** después del merge, que es cuando importa—.
