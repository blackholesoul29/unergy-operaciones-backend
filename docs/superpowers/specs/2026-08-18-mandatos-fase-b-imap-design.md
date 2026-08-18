# Mandatos — Fase B: lectura de correo por IMAP

Fecha: 2026-08-18
Estado: aprobado, pendiente de plan de implementación
Reemplaza: sección 8 ("Fase B — Integración Gmail") de
`2026-06-18-mandatos-costos-tab-design.md`

---

## 1. Por qué este diseño reemplaza al de junio

El diseño de junio planteaba Gmail API con OAuth2 o delegación de dominio. Eso quedó
bloqueado ocho semanas esperando una acción del admin de Google Workspace: habilitar
Gmail API y autorizar el client ID de la cuenta de servicio.

El 2026-08-14 Sara Jácome implementó la lectura automática del Excel de Cedillanos
(`app/services/reporte_energia/excel_terceros_email.py`, commits `b9844b9` y `37d1978`)
usando **IMAP con App Password** sobre la cuenta que ya se usaba para enviar correo.
Ese camino no requiere ninguna acción del admin de Workspace: basta con que la cuenta
tenga verificación en dos pasos e IMAP habilitado.

Esta Fase B adopta ese mismo camino. No se usa Gmail API, OAuth2 ni delegación de
dominio. La tabla `gmail_credenciales` creada en Fase A queda sin uso y no se toca.

## 2. Qué cambió respecto a los supuestos de junio

El diseño de junio se escribió sin correos reales a la vista. El 2026-08-18 se revisaron
seis correos reales (tres de la revisoría, tres de envío a inversionistas). Los supuestos
que resultaron falsos:

| Supuesto de junio | Realidad |
|---|---|
| Buzón a leer: `jessica@unergy.io` | `adhara@unergy.io` está en copia de **todos** los hilos, incluidos los de Jessica a inversionistas. `operaciones@` no (falta en el del 14 jul). |
| Asunto con patrón `revisión mandatos de costos {mes}` | No verificado y no necesario. Se filtra por remitente. |
| Vanessa escribe "mandato" | Escribe "**Certificado**" en la mayoría de los correos. Solo un correo de seguimiento dice "mandatos". |
| Fuente 3 requiere leer la carpeta Enviados de Jessica | Llega a `adhara@` como copia normal en INBOX. |
| Fuente 3 es la más compleja | Es la **más simple y robusta**: el CMU va en el nombre del PDF adjunto. |
| PDFs de la revisoría se llaman `CMU0975_firmado.pdf` | Sin verificar. Los de Jessica sí siguen `CMU####-Mandato-Costos-...pdf`. |

Lección aplicada: este spec se escribe sobre correos reales, y los correos reales quedan
como casos de prueba fijos (§10).

## 3. Decisiones

| Decisión | Valor | Motivo |
|---|---|---|
| Buzón | `adhara@unergy.io` | Único en copia de las tres fuentes |
| Mecanismo | IMAP + App Password | No depende del admin de Workspace |
| Acceso | Solo lectura, siempre | La plataforma nunca envía, responde ni modifica correo |
| Estado de la bandeja | **No se toca** | `adhara@` es un buzón de persona; marcar leídos desordenaría su trabajo |
| Modo | Automático, con compuerta | Ver §6 |
| Interpretación de texto | Regex, sin LLM | El backend no tiene infraestructura de LLM y el volumen no la justifica |
| Bitácora | Todos los correos leídos | Se registra lo procesado **y** lo omitido |
| Reversión | Todo cambio automático | Trazado al correo que lo causó, revertible en un clic |

## 4. Arquitectura

Cuatro unidades, cada una con una responsabilidad:

| Unidad | Responsabilidad | Depende de |
|---|---|---|
| `app/services/mandatos/imap_client.py` | Conectar, buscar, traer correos. No sabe de mandatos. | `config` |
| `app/services/mandatos/email_parser.py` | **Función pura**: texto/HTML → estructura. Sin red ni BD. | `mandatos_service` |
| `app/services/mandatos/email_sync.py` | Orquesta: IMAP → parser → BD, aplica transiciones | las anteriores |
| cron en `app/main.py` | Dispara el ciclo | `email_sync` |

`email_parser.py` no toca nada externo. Concentra toda la fragilidad del sistema y se
prueba con los correos reales como fixtures, sin conectarse a Gmail ni a la base.

Se reusa lo que Fase A ya construyó en `app/services/mandatos_service.py`:
`CMU_RE`, `ZIP_NOMBRE_RE`, `extraer_cmus()`, `extraer_cmu_de_nombre()`,
`mes_a_periodo()` y `transicion_valida()` con el diccionario `TRANSICIONES`.

## 5. Configuración

Dos variables nuevas en Railway. **No se reusan** `SMTP_USER`/`SMTP_PASSWORD` porque esas
son de `operaciones@` y aquí se lee `adhara@`:

```
MANDATOS_IMAP_USER=adhara@unergy.io
MANDATOS_IMAP_PASSWORD=<App Password de esa cuenta>
```

`IMAP_HOST` (`imap.gmail.com`) e `IMAP_PORT` (`993`) ya existen en `app/core/config.py`,
agregadas por el trabajo de Cedillanos.

Si alguna de las dos falta, el cron **no se registra** y queda un aviso en el log —
mismo comportamiento que el de Cedillanos. Nada más se ve afectado.

Requisitos del lado de Google, previos al despliegue: la cuenta `adhara@unergy.io` debe
tener verificación en dos pasos activa (necesaria para generar un App Password) e IMAP
habilitado en la configuración de Gmail.

## 6. Detección y clasificación

### 6.1 Búsqueda IMAP

Se busca por **remitente y fecha**, nunca por asunto:

```
(SINCE "<hoy - 30 días>" FROM "vlondono@jbp.com.co")
(SINCE "<hoy - 30 días>" FROM "jessica@unergy.io")
```

Filtrar por remitente evita la clase de bug que Sara encontró en producción: el `SEARCH`
de Gmail busca por **token completo**, no por subcadena, así que `85329` nunca hacía match
con `FRT85329`. Las direcciones de remitente son estables y conocidas, así que no hay
token que adivinar.

No se usa `UNSEEN`, porque eso obligaría a marcar los correos como leídos.

### 6.2 Deduplicación sin tocar la bandeja

Cada correo tiene un header `Message-ID` único y estable. Se guarda en la tabla
`mandato_correos` (§7). Si el `Message-ID` ya está registrado, el correo se ignora.

Los UIDs de IMAP no sirven para esto: pueden cambiar. El `Message-ID` sí es estable.

Consecuencia deseada: un correo que la persona ya leyó a mano se procesa igual, y la
bandeja de `adhara@` queda exactamente como estaba.

### 6.3 Compuerta de molde conocido

La compuerta gobierna **únicamente la interpretación del cuerpo del correo** (Fuente 1).
Los adjuntos se procesan siempre, cualquiera sea la clasificación, porque un archivo
adjunto es un hecho objetivo que no depende de interpretar prosa (Fuente 2, §6.4).

Los correos de la revisoría se clasifican **antes** de parsear su texto:

- **`molde_simple`** — introduce observaciones nuevas. Se reconoce por una frase de
  apertura de listado (`encuentro las siguientes observaciones`,
  `relaciono a continuación las diferencias identificadas`, o equivalente) seguida de
  ítems donde cada CMU va acompañado de su descripción. **Se procesa automáticamente.**
- **`seguimiento`** — responde sobre observaciones previas. Se reconoce por señales de
  hilo: `agradezco`, `sin embargo`, `siguen siendo las mismas`, `ajustes realizados`,
  `su respuesta`, o asunto que empieza por `RE:`. **Su texto no se interpreta.** Se
  registra y se marca `requiere_revision`.
- **`desconocido`** — no encaja en ninguno. **Su texto no se interpreta.** Se registra y
  se marca `requiere_revision`.

En los dos últimos casos, si el correo trae adjuntos PDF, esos sí se procesan (Fuente 2)
y el correo queda con `resultado = aplicado` **y** `requiere_revision = true`: se guardó
el firmado, pero su texto quedó pendiente de que alguien lo lea.

La compuerta existe porque el regex no puede distinguir un CMU resuelto de uno con
novedad. Correo real del 2026-08-10 5:50 p.m.:

> "Agradezco su respuesta y los ajustes realizados para el mandato **CMU1255**. Sin
> embargo, para los mandatos CMU1266, CMU1269, CMU1271 y CMU1284, las observaciones
> siguen siendo las mismas."

Un regex de `CMU\d+` marcaría CMU1255 como `con_correcciones` cuando es justo el único
resuelto. Con la compuerta, ese correo se clasifica `seguimiento` y nunca llega al regex.

Ese mismo correo expone un caso irresoluble: el correo previo listaba CMU1270, y este ya
no lo menciona. No hay forma de saber si se resolvió o si fue un olvido. Ningún parser
puede decidirlo — por eso queda para revisión humana.

### 6.4 Las tres fuentes

**Fuente 1 — observaciones de la revisoría → `con_correcciones`**

Correo de `vlondono@jbp.com.co` clasificado `molde_simple`. Por cada ítem del listado se
extrae el CMU y el texto de su observación. Los CMU listados pasan a `con_correcciones`
con la observación guardada en `Mandato.observacion`, y el `Message-ID` en
`Mandato.correo_ref_revisoria`.

Los CMU del período que **no** aparecen en el correo no se tocan. El diseño de junio
proponía confirmarlos como `enviado_revisoria`; se descarta, porque la ausencia de un CMU
en un correo no es evidencia de nada (ver el caso CMU1270).

**Fuente 2 — PDF firmado de la revisoría → `firmado`**

Cualquier correo de `vlondono@jbp.com.co` con adjuntos PDF, sin importar su clasificación
— un adjunto es un hecho objetivo y no depende de interpretar prosa. Correo real del
14 jul: *"Adjunto comparto los certificados de Sol de la Sierra debidamente firmados"*,
que además trae observaciones en el mismo cuerpo. Un correo puede disparar Fuente 1 y
Fuente 2 a la vez.

Por cada PDF se intenta `extraer_cmu_de_nombre()`. Si da un CMU conocido, el mandato pasa
a `firmado`, se guarda el archivo en `uploads/mandatos/` y se llenan `pdf_firmado_ruta` y
`pdf_firmado_nombre`. Si no se identifica el CMU, **el archivo se guarda igual** y queda
marcado para asociación manual — el endpoint `POST /mandatos/{id}/asociar-pdf` de Fase A
ya cubre ese caso. Nunca se descarta un PDF firmado.

No está verificado que los PDFs de la revisoría usen la convención `CMU####-...`. El
diseño no lo asume: si no la usan, caen en la rama de asociación manual.

**Fuente 3 — envío a inversionista → `enviado_inversionista`**

Correo de `jessica@unergy.io` con adjuntos PDF cuyo nombre empieza por `CMU####`. Esos
CMU pasan a `enviado_inversionista` con `fecha_envio_inversionista` = fecha del correo y
el `Message-ID` en `Mandato.correo_ref_envio`.

**No se lee el cuerpo del correo.** El CMU viene en el nombre del archivo, que ya sigue
`ZIP_NOMBRE_RE` (`CMU####-Mandato-Costos-{Proyecto}-{Inversionista}.pdf`), el mismo patrón
que la carga por ZIP de Fase A. Esto hace de Fuente 3 la más robusta de las tres.

Adjuntos que no son PDF se ignoran (los correos reales traen un `REGISTRO MANDATOS.xlsx`
junto a los certificados).

*Regla de estado.* `TRANSICIONES` solo permite `enviado_inversionista` desde `firmado`. Si
el mandato está en `enviado_revisoria` o `corregido`, el PDF adjunto es evidencia de que
fue firmado, así que se aplica la cadena `firmado` → `enviado_inversionista` en una sola
operación. Si está en `con_correcciones`, **no se aplica nada** y se registra el conflicto:
enviar a un inversionista un mandato con observaciones pendientes es una anomalía real que
merece revisión humana, no una corrección automática.

*Falso positivo cubierto.* Jessica también envía correos de "Liquidación preliminar" a los
mismos destinatarios, y su cuerpo menciona *"una vez se emitan los certificados de mandato"*.
No traen adjuntos PDF de mandato, así que la regla de Fuente 3 los descarta sin necesidad
de una excepción especial.

## 7. Modelo de datos

### Tabla nueva `mandato_correos`

Una fila por correo leído, procesado o no.

| Columna | Tipo | Nota |
|---|---|---|
| `id` | BigInteger PK | |
| `message_id` | String(998) UNIQUE | header `Message-ID`; clave de deduplicación |
| `fecha` | DateTime(tz) | fecha del correo |
| `remitente` | String(255) | |
| `asunto` | String(1000) | |
| `fuente` | String(20) | `revisoria` \| `envio_inversionista` |
| `clasificacion` | String(20) | `molde_simple` \| `seguimiento` \| `desconocido` |
| `resultado` | String(20) | `aplicado` \| `omitido` \| `error` |
| `requiere_revision` | Boolean | destaca la fila en la UI |
| `detalle` | JSONB | CMU afectados, estados anteriores, motivo de omisión, error |
| `created_at` | DateTime(tz) | |

Índices: `message_id` (único), `fecha`, `requiere_revision`.

El DDL va en `_PENDING_DDLS` de `app/main.py`, siguiendo la convención del proyecto —
la tabla se crea sola en el arranque del deploy.

### Cambios en `mandatos`

Ninguna columna nueva. `correo_ref_revisoria` y `correo_ref_envio` ya existen en el modelo
(`app/models/mandatos.py`) y se usan para guardar el `Message-ID` de origen.

La reversión se reconstruye desde `mandato_correos.detalle`, que guarda el estado anterior
de cada mandato afectado.

## 8. Manejo de errores

Ninguna ruta pierde información. Ante la duda, no actuar y avisar.

| Situación | Comportamiento |
|---|---|
| IMAP no conecta o autentica | Log de error, `return` sin excepción hacia el scheduler. Reintenta en la próxima corrida. |
| Correo no clasificable | `desconocido` → cero cambios, `requiere_revision` |
| CMU extraído que no existe en `mandatos` | Sin cambios, se registra en `detalle` para revisión |
| PDF sin CMU identificable | Archivo **guardado**, marcado para asociación manual |
| Transición inválida según `TRANSICIONES` | No se aplica, se registra el conflicto |
| Estado puesto a mano por una persona | No se sobrescribe, se registra el intento |
| Un correo falla a mitad | Transacción **por correo**: ese se marca `error`, los demás siguen |

El scheduler nunca se cae por un fallo de esta rutina, siguiendo el patrón de
`revisar_correo_cedillanos()`.

## 9. Frecuencia y UI

**Cron:** cada hora entre 7 a.m. y 7 p.m. hora Bogotá, en el mismo scheduler
(APScheduler) que ya usa el resto del pipeline. Estos correos no son urgentes como el de
Cedillanos, que debía procesarse antes de las 6 a.m. Cuando no hay correos nuevos, la
corrida es solo un `SEARCH` de IMAP y no toca la base de datos.

**UI — panel "Correos leídos"** en la pestaña Mandatos: lista de `mandato_correos` con
fecha, remitente, asunto, clasificación y resultado. Las filas con `requiere_revision` se
destacan arriba. Muestra el 100% de lo que el sistema vio, no solo aquello sobre lo que
actuó.

Cada mandato modificado por correo muestra un indicador de origen con enlace a la fila que
lo causó y un botón **revertir**, que restaura el estado anterior guardado en `detalle`.

## 10. Pruebas

`email_parser.py` es puro, así que los correos reales se vuelven casos fijos. Los seis
revisados el 2026-08-18:

| Fixture | Clasificación esperada | Extracción esperada |
|---|---|---|
| Revisoría 10 ago 2:25 p.m. | `molde_simple` | CMU1255, CMU1266, CMU1269, CMU1270, CMU1271, CMU1284 con su observación |
| Revisoría 10 ago 5:50 p.m. | `seguimiento` | **nada** — prueba de regresión más importante del sistema |
| Revisoría 14 jul 3:20 p.m. | `molde_simple` + adjuntos | CMU1052, CMU1122 + PDFs firmados |
| Jessica 12 ago 8:14 a.m. | Fuente 3 | CMU1135, CMU1139, CMU1141, CMU1142 desde los nombres; ignora el `.xlsx` |
| Jessica 18 ago 10:10 a.m. | Fuente 3 | los CMU de sus dos adjuntos |
| Jessica 12 ago 5:05 p.m. ("Liquidación preliminar") | Fuente 3 | **nada** — caso negativo |

Casos adicionales: cuerpo con tabla HTML embebida (el del 10 ago 2:25 p.m. la trae) que no
debe romper la extracción; `Message-ID` repetido que debe ignorarse; transición inválida
que debe registrarse sin aplicarse.

`email_sync.py` se prueba con un cliente IMAP simulado. No se hacen pruebas contra el
buzón real en CI.

## 11. Fuera de alcance

- Enviar, responder o modificar correos. La plataforma es solo-lectora, siempre.
- Marcar correos como leídos, mover o etiquetar en la bandeja de `adhara@`.
- OAuth2, Gmail API o delegación de dominio. Todo el punto es no depender del admin de
  Workspace.
- Multi-buzón. Solo `adhara@`.
- Reinterpretar correos de seguimiento. Quedan para revisión humana por diseño (§6.3).
- Confirmar `enviado_revisoria` por ausencia de un CMU en un correo (§6.4, Fuente 1).

## 12. Riesgos conocidos

- **Si Vanessa cambia su redacción**, la compuerta clasificará sus correos como
  `desconocido` y dejarán de procesarse automáticamente. Falla hacia el lado seguro: se
  ven en el panel, no se pierden. La corrección es agregar el correo como fixture y
  ajustar el clasificador.
- **Los correos de seguimiento siguen siendo trabajo manual.** Es el precio de no usar un
  LLM. Si el volumen crece, reconsiderar.
- **Un App Password da acceso de lectura a todo el buzón**, no solo a los mandatos. El
  alcance se limita en el código (filtro por remitente), no en la credencial. Rotarlo si
  se sospecha exposición; se revoca desde la cuenta de Google sin tocar la plataforma.
- **CMU1270 y casos análogos** no tienen solución automática. Requieren que una persona
  cierre el ciclo.

---

Relacionado: `2026-06-18-mandatos-costos-tab-design.md` (Fase A),
`2026-06-18-mandatos-carga-zip-design.md` (parser de nombres reusado),
`app/services/reporte_energia/excel_terceros_email.py` (patrón IMAP de referencia).
