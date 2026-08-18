# Integración de los dos módulos de Mandatos — documento para decidir

Fecha: 2026-08-18
Estado: **propuesta, no aprobada.** Escrito para llevar a una conversación con Jessica.

> Las secciones 1–4 son hechos verificados contra el código. La 5 es el diseño.
> La 6 quedó respondida (ver más abajo).

## 0. Decisiones tomadas (2026-08-18)

Cerradas tras consultar a Jessica. Todo lo demás en este documento se lee a la luz
de estas.

| Decisión | Valor |
|---|---|
| Tabla destino | `finanzas_mandatos` (la de Jessica), **intacta** — datos reales y PDFs en Drive se quedan donde están |
| Se descarta | tabla `mandatos` de Fase A (31 registros de prueba) y su API |
| Ubicación en la UI | **Finanzas > Mandatos**, donde ya está, con subpestañas Ingresos / Costos |
| Sale del menú | la pestaña Costos > Mandatos (Fase A) — el módulo queda en **un solo lugar** |
| Ingesta | cron IMAP de Fase B; el script de Jessica deja de ser el camino principal |
| Almacenamiento de PDFs | Google Drive (el de Finanzas), no disco local |
| Envío a inversionista | **sigue en alcance** — hay que agregarlo al modelo de Finanzas |
| Identificación del tercero | por el **código numérico del P.A.** (`17844`, `18254`) extraído del cuerpo, no por cruce difuso de nombres |
| Migración de datos | **ninguna** — la tabla destino ya tiene los datos buenos |

Se conserva el nombre `finanzas_mandatos` y las rutas `/finanzas/mandatos/*` aunque
la pantalla viva bajo Finanzas: renombrar una tabla con datos reales en producción es
un riesgo que no compensa la mejora estética.

---

## 1. Qué pasó

Dos sistemas para lo mismo se construyeron en paralelo, sin saber uno del otro:

| | **Finanzas Mandatos** (Jessica) | **Mandatos Fase B** (Adhara) |
|---|---|---|
| Fecha | 2026-08-14 | 2026-08-18 |
| Estado | **En producción** | Rama `feat/mandatos-fase-b-imap`, sin mergear |
| Tabla | `finanzas_mandatos` | `mandatos` + `mandato_correos` |
| Ingesta | Script local en el PC de Jessica, manual | Cron en Railway, cada hora |

Ambos leen **los mismos correos de Vanessa Londoño** y rastrean **los mismos
mandatos del mundo real**.

El diseño de Jessica (`2026-08-14-modulo-mandatos-finanzas-design.md:19-20`) dice que
el módulo viejo está "dormido" y que su Fase B "quedó sin construir" — cierto cuando
lo escribió, y por eso decidió construir uno nuevo en vez de arriesgar el viejo. Fase
B se construyó cuatro días después sin que ninguna de las dos partes supiera de la
otra. No hay culpa que repartir; hay una duplicación que resolver.

## 2. Dónde acertó cada uno

Esto es lo que hace que la integración valga la pena: **los aciertos no se
superponen.**

### Aciertos de Finanzas Mandatos

**La identidad está bien modelada y la nuestra no.** Jessica llavea por
`(proyecto, tercero, periodo, tipo)` con el CMU como atributo mutable más
`cmu_anterior` (`app/models/finanzas_mandatos.py:32-46`,
`app/services/finanzas_mandatos_service.py:108-111`).

Fase B llavea por `(cmu, periodo)` (`app/models/mandatos.py:42`). Consecuencia real:
**si Vanessa reexpide un CMU corregido, Fase B crea una fila nueva en vez de
actualizar la existente.** El CMU no es un identificador durable y el diseño de
Jessica lo reconoce; el nuestro lo asumió estable. Es un defecto nuestro, no una
diferencia de opinión.

**Cubre ingresos y costos.** `TipoMandatoEnum` (`finanzas_mandatos.py:12-14`). La
tabla `mandatos` no tiene columna `tipo` en absoluto: Fase A y B son solo de costos.

**Los PDFs van a Google Drive** (`app/services/finanzas_mandatos_drive.py:39-49`),
no a disco local. Mejor: enlace compartible para inversionistas y auditoría, y no
depende del volumen persistente de Railway.

### Aciertos de Fase B

**La lectura de correo está en la plataforma; la de Jessica no.** El endpoint
`/finanzas/mandatos/ingest` recibe `estado` y `comentario` **ya decididos**, como
campos de formulario (`app/api/v1/finanzas_mandatos.py:29-34`). Las funciones
`estado_por_direccion` y `detectar_comentario`
(`finanzas_mandatos_service.py:56-69`) existen en el repo pero **no las llama
ningún endpoint** — solo los tests. Toda la interpretación real vive en
`C:\Users\jessi\OneDrive\Documentos\MandatosRevisoria\mandatos_revisoria.py`, fuera
del repositorio, y **no se puede auditar ni versionar desde acá**.

Operativamente: si Jessica no prende su equipo y corre el script, no entra nada.

**El parser de Fase B es más robusto, y está probado contra correos reales**
(`tests/fixtures_mandatos_correos.py`, seis correos):
- Compuerta de clasificación (`email_parser.py:133-152`): los correos de
  seguimiento nunca se interpretan por texto, porque ahí un CMU puede estar
  **resuelto**, no con novedad. Caso real: el correo del 10 ago 5:50 p.m. donde
  CMU1255 quedó resuelto y un regex ingenuo lo marcaría con correcciones.
- Recorte de historial citado (`email_parser.py:176-202`): un CMU citado del hilo
  anterior no revive como observación nueva.

**Máquina de estados más fina.** Jessica: `sin_firma | firmado | con_comentarios`.
Fase B agrega el ciclo de corrección (`con_correcciones` → `corregido`) y la pata
de envío al inversionista (`enviado_inversionista`), con un grafo explícito de
transiciones válidas (`mandatos_service.py:18-26`). El diseño de Jessica difirió
esa parte a propósito, no la modeló mal.

**Bitácora y reversión.** `mandato_correos` guarda una fila por correo leído —
procesado u omitido — con los valores anteriores de cada campo, de donde sale el
botón de revertir. Finanzas Mandatos solo guarda un `correo_ref` de texto.

## 3. Qué está vivo hoy (verificado, no supuesto)

- El router de Finanzas Mandatos **sí está registrado**: `app/api/v1/router.py:46`.
- **No hay DDL de `finanzas_mandatos` en `_PENDING_DDLS`.** La tabla se crea por
  `Base.metadata.create_all()` en el arranque (`app/main.py:1794-1798`), porque el
  modelo está importado en `app/models/__init__.py:44`. Funciona, pero se sale de la
  convención del repo y es invisible si alguien audita el esquema buscando en
  `_PENDING_DDLS`. Vale la pena normalizarlo aparte de esta integración.
- **Finanzas Mandatos no tiene ningún cron.** Depende enteramente del script manual.
- Fase B sí registra un cron horario, pero está en la rama sin mergear.

## 4. Lo que se preguntó y ya está respondido (2026-08-18)

Las respuestas cambiaron partes del diseño. Se dejan acá con lo que implica cada una.

**El script de Jessica hace dos cosas que la plataforma no tiene.** Además de bajar
y organizar los mandatos que ella envió:
- **Abre cada PDF y verifica que traiga las dos firmas.** Eso es un hecho objetivo
  leído del documento, y es *más* confiable que deducir el estado de quién va en el
  `De:` (`estado_por_direccion`). La integración no puede perder esta capacidad.
- **Reconcilia por conteo:** si se enviaron 32 mandatos en julio, verifica que
  vuelvan los 32. Hoy **ninguna de las dos tablas registra cuántos se enviaron**, así
  que esto no es algo que se migre — es una capacidad nueva que hay que construir.

El repo ya tiene con qué: `pdfplumber` y `pypdf` en `requirements.txt`, y
`app/services/conciliacion_mandatos.py` ya inspecciona PDFs.

**El envío a inversionistas sigue en pie.** Hay que llevar a `finanzas_mandatos` los
estados `enviado_inversionista` y el ciclo `con_correcciones` → `corregido`.

**Los datos: dos tablas, dos destinos distintos.**

| Tabla | Contenido | Destino |
|---|---|---|
| `mandatos` (Fase A) | 31 registros de prueba de mayo 2025, 0 firmados | se descarta |
| `finanzas_mandatos` | mandatos reales + PDFs en Drive | **se conserva intacta** |

No hay migración de datos. La tabla de Jessica *es* el destino: sus filas se quedan
donde están y sus PDFs siguen en Drive con las mismas URLs. Lo único que cambia es
quién le escribe — hoy su script, después el cron.

**Los ZIP de Vanessa vienen con la misma convención de nombres**, así que el mismo
parser sirve; pero el cliente IMAP tiene que abrir el ZIP. `POST /mandatos/upload-zip`
(Fase A) ya tiene esa lógica, se reusa.

### Sigue abierto

- **¿Jessica quiere dejar de correr su script?** Si existe para organizarle a *ella*
  los mandatos enviados, puede que no sea un pipeline duplicado sino herramienta
  personal que la plataforma no reemplaza. La integración correcta entonces no es
  retirarlo, sino que la plataforma cubra la ingesta automática y él siga a su lado.
- **Si los PDFs quedaron realmente cargados en Drive.** El usuario dijo "se supone
  que cargó los PDFs". Conviene confirmarlo antes de construir encima; un endpoint de
  diagnóstico que cuente cuántas filas tienen `drive_url` lo resuelve.

## 4b. La convención de nombres: verificada, y un bug en producción

Captura del Drive de Jessica (2026-08-18), carpeta "Mandato Costos Sol de la Sierra":

```
CMU1135-Mandato-Costos-Minigranja Solar La Paz Levende.pdf
CMU1140-Mandato-Costos-Minigranja Solar Merengue.pdf
CMU1147-Mandato-Costos-Minigranja Solar Cumbia.pdf
```

**Tres partes, no cuatro.** `CMU####-Mandato-Costos-{Proyecto}.pdf`, sin sufijo de
inversionista.

**Consecuencia 1 — el tercero no está en el adjunto.** El tercero es el P.A., y vive
en el cuerpo del correo: `17844 - P.A SOL DE LA SIERRA`. El adaptador debe sacarlo
de ahí; si confía en el nombre del archivo, `parsear_proyecto_tercero` devuelve
`tercero=''` y la identidad `(proyecto, tercero, periodo, tipo)` colapsa.

**Consecuencia 2 — bug vivo en Fase A.** `ZIP_NOMBRE_RE` (`mandatos_service.py:9`)
exige ese sufijo inexistente, y `upload-zip` hace `if not parsed: continue`. Con un
ZIP real de Vanessa **saltaría todos los archivos y reportaría cero detectados**.
Fijado en `test_el_parser_de_zip_de_fase_a_rechaza_los_nombres_reales`, que pasa
mientras el bug exista. Es independiente de esta integración y se puede corregir ya.

## 5. Propuesta: el esquema de ella, el motor de nosotros

Una sola tabla, una sola ingesta, automática.

**Se conserva de Finanzas Mandatos**
- La tabla `finanzas_mandatos` y su identidad `(proyecto, tercero, periodo, tipo)`
- `cmu_anterior` para CMU reexpedido
- La distinción ingreso / costo
- Almacenamiento de PDFs en Drive
- Los endpoints `/finanzas/mandatos/*` y la vista de Finanzas

**Se aporta desde Fase B**
- `email_parser.py` completo: compuerta de clasificación y recorte de cita
- `imap_client.py` y el cron horario — la ingesta pasa a ser automática y auditable
- La bitácora `mandato_correos` y el botón de revertir
- Los estados finos `corregido` y `enviado_inversionista`, si siguen queriéndose
- El FK al maestro de inversionistas, en vez de `tercero` como texto libre

**Se retira**
- El script local de Jessica como camino de ingesta (queda como respaldo manual
  mientras el cron demuestre que funciona)
- La tabla `mandatos` y su API, una vez migrado lo que valga la pena

### El trabajo es menor de lo que parecía (corregido 2026-08-18)

La primera versión de este documento decía que había que ampliar el parser de
Fase B para extraer proyecto, tercero y tipo. **Eso estaba mal: el parser de
Finanzas ya lo hace**, y del lado del servidor, no en el script local.

En `app/services/finanzas_mandatos_service.py` ya existen y están probados:
`tipo_de_nombre` (24), `extraer_cmu` (29), `extraer_periodo_de_asunto` (37),
`parsear_proyecto_tercero` (72) y `upsert_mandato` (91). Más `subir_pdf` en
`finanzas_mandatos_drive.py`. Lo único que falta es **que algo las llame de forma
automática** — hoy solo las invoca el script de Jessica, indirectamente, mandando
los valores ya resueltos a `/ingest`.

Verificado contra los correos reales (`tests/test_mandatos_integracion_contrato.py`,
12 tests): los cuatro adjuntos del correo del 12 ago rinden identidad completa
—tipo `costo`, proyecto `Sol de la Sierra`, tercero `Bancolombia`, CMU propio de
cada uno— y el período sale del asunto, infiriendo el año cuando no aparece.

Como ambos módulos viven en el mismo proceso, el adaptador **no necesita hacer
HTTP contra `/ingest`**: compone servicios directamente. Queda:

```
cron IMAP (Fase B)
  └─ por correo:
       clasificar_correo + _sin_cita          (Fase B, más robusto)
       tipo_de_nombre / parsear_proyecto_tercero / extraer_periodo_de_asunto
       upsert_mandato + subir_pdf             (Finanzas)
       registrar en mandato_correos           (Fase B, bitácora reversible)
```

### El riesgo real que sí apareció

`tipo_de_nombre` **nunca dice "no sé"**: devuelve `ingreso` para todo lo que no
diga literalmente `mandato-costos`. En el flujo de Jessica es inofensivo, porque su
script solo le entrega adjuntos que ya sabe que son mandatos. El cron de Fase B ve
**todos** los adjuntos del correo, así que un archivo suelto entraría como mandato
de ingreso con identidad inventada. Caso concreto y real: el correo del 12 ago trae
`REGISTRO MANDATOS.xlsx` junto a los PDFs, y hoy se ingeriría como
`(tipo=ingreso, proyecto="REGISTRO MANDATOS.xlsx", tercero="")`.

**El adaptador debe decidir por sí mismo si un adjunto es un mandato antes de
preguntar el tipo.** No puede delegar esa decisión, porque esa función no tiene
forma de responder que no lo es. Fijado en
`test_tipo_de_nombre_cae_en_ingreso_para_archivos_que_no_son_mandato`.

Queda pendiente de validar la convención de nombres de **los adjuntos de Vanessa**
(Fuente 2). Los de Jessica están verificados; los de ella no, y el propio diseño de
Finanzas marca esa extracción como riesgo sin validar
(`2026-08-14-...-design.md:131-134`).

### Orden sugerido

1. Normalizar el DDL de `finanzas_mandatos` a `_PENDING_DDLS` (independiente, chico)
2. Ampliar el parser para extraer proyecto/tercero/tipo, validado contra correos reales
3. Escribir el adaptador que conecta el cron de Fase B con la lógica de upsert de Finanzas
4. Correr ambas ingestas en paralelo un ciclo y comparar resultados
5. Retirar el script manual
6. Migrar o descartar los datos de `mandatos` y dar de baja esa tabla

Los pasos 1 y 2 son útiles pase lo que pase con el resto.

## 6. Preguntas para Jessica

1. **¿El script local hace algo que no esté en el diseño?** Manejo de hilos citados,
   correos con varios adjuntos, casos raros que ya te hayan mordido.
2. **¿Cuántos datos reales hay ya en `finanzas_mandatos`?** ¿Vale la pena migrar lo
   de la tabla `mandatos` o se descarta?
3. **¿Sigue en pie el envío a inversionistas?** Fase B lo implementó; tu diseño lo
   dejó fuera de v1.
4. **¿El `tercero` en texto libre te ha dado problemas?** Fase B tiene una tabla
   maestra de inversionistas con cruce difuso; puede servirte o puede sobrar.
5. **¿Te sirve que la ingesta deje de depender de tu equipo?** Es el cambio más
   grande de la propuesta y el que más te afecta a ti.

## 7. Si la integración no se hace

La alternativa honesta es dejar Fase B sin mergear y quedarse solo con Finanzas
Mandatos. Se pierde la ingesta automática, la compuerta de clasificación y la
bitácora reversible, pero se evita mantener dos sistemas. **Es preferible a
mergear Fase B tal cual y dejar dos ingestas vivas escribiendo sobre el mismo
hecho** — esa es la única opción que no se debería tomar.

---

Relacionado:
`2026-08-18-mandatos-fase-b-imap-design.md` (Fase B),
`2026-08-14-modulo-mandatos-finanzas-design.md` (Finanzas Mandatos),
`2026-06-18-mandatos-costos-tab-design.md` (Fase A)
