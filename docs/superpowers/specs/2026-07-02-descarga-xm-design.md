# Descarga de XM — pestaña en Finanzas

## Objetivo

Pestaña en Finanzas donde la usuaria elige tipo de archivo, extensión y rango
de fechas; el sistema se conecta al FTP de XM con las credenciales que ella
ingresa, descarga los archivos del tipo/rango, los unifica (misma lógica que
`Unificacion.ipynb`) y entrega un Excel + TXT unificado para descargar.

## Alcance de esta iteración

8 tipos de archivo (los que aparecen en `Unificacion.ipynb`):
`dspcttos`, `aenc`, `BalCttos`, `grip`, `arrpas`, `tgrl`, `trsd`, `cxcsb`.

Extensiones disponibles (dropdown único, independiente del tipo):
`txf, txr, tx1, tx2, tx3, tx4, tx5, tx6, tx7, tx8`.

## 1. Conexión FTP

Módulo `app/services/xm/ftp_client.py`.

- `ftplib.FTP_TLS` con contexto SSL relajado (`ssl.PROTOCOL_TLS_CLIENT`,
  `check_hostname=False`, `verify_mode=ssl.CERT_NONE`). Patrón tomado de
  `aenc_reporte.py` (script en producción) — el servidor de XM no pasa
  verificación TLS estricta con el `FTP_TLS` plano.
- Conecta a `host:210` (host/usuario/clave los ingresa la usuaria en el
  formulario, no se hardcodean ni se guardan en `.env`).
- Flujo: `connect(host, 210, timeout=30)` → `.auth()` →
  `.login(user, passwd)` → `.prot_p()` → `.cwd(directorio)`.
- Excepciones tipadas (mismo patrón que `xm.py` del GitLab de referencia):
  `FTPConnectionError` (503), `FTPAuthenticationError` (401),
  `FTPPermissionError` (403), `FTPFileNotFoundError` (404),
  `FTPTimeoutError` (504). Cada una trae un mensaje humano listo para
  mostrar en el frontend.
- Reintentos: 3 intentos por archivo con backoff (10s), reconectando el FTP
  entre intentos — igual que `ftp_grip_xm`/`ftp_grip_dspcttos` en `xm.py`.
  Si un día puntual no tiene archivo (feriado, aún no publicado), se omite
  y se reporta, no aborta el job completo.

## 2. Config de tipos

Módulo `app/services/xm/tipos.py`, tabla estática:

| tipo       | ruta                                    | patrón de nombre       |
|------------|------------------------------------------|-------------------------|
| dspcttos   | privada                                  | diario `{tipo}MMDD.ext` |
| aenc       | privada                                  | diario `{tipo}MMDD.ext` |
| BalCttos   | privada                                  | diario `{tipo}MMDD.ext` |
| grip       | pública                                  | diario `{tipo}MMDD.ext` |
| arrpas     | pública                                  | diario `{tipo}MMDD.ext` |
| tgrl       | pública                                  | diario `{tipo}MMDD.ext` |
| trsd       | pública                                  | diario `{tipo}MMDD.ext` |
| cxcsb      | pública                                  | mensual `{tipo}MM.ext`  |

Rutas base (confirmadas en `xm.py` del GitLab de referencia y en
`aenc_reporte.py`):

- Pública: `/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/{año}-{mes:02d}`
- Privada: `/INFORMACION_XM/USUARIOSK/UNGG/SIC/COMERCIA/{año}-{mes:02d}`

## 3. Descarga

Módulo `app/services/xm/downloader.py`.

- Si el rango de fechas cruza meses, itera cada `(año, mes)` del rango,
  reconectando al directorio correspondiente por mes.
- Para tipos diarios: por cada día del rango dentro del mes, intenta
  `RETR {tipo}{MM}{DD}.{ext}`.
- Para `cxcsb` (mensual): intenta `RETR {tipo}{MM}.{ext}` una vez por mes
  del rango.
- Archivos no encontrados se registran en el resultado del job
  (`archivos_faltantes: [...]`) sin abortar el proceso.

## 4. Unificación

Módulo `app/services/xm/unificador.py`. Replica la celda genérica de
`Unificacion.ipynb` (la de `dspcttos`/`aenc`):

- Encoding: `latin1` si `tipo == 'aenc'`, si no `utf-8-sig` — con fallback a
  `latin1` si `utf-8-sig` lanza `UnicodeDecodeError` (como en el resto de
  celdas del notebook).
- Lee cada archivo con `pandas.read_csv(sep=';')`, agrega columna
  `FechaDocumento` (`YYYY-MM-DD` para tipos diarios, `YYYY-MM` para
  `cxcsb`), la mueve a primera columna.
- Concatena todos los DataFrames del rango.
- Exporta:
  - `{tipo}_{ext}_{MM}.xlsx` si el rango cae en un solo mes, o
    `{tipo}_{ext}_{MM1}-{MM2}.xlsx` si cruza meses (vía `openpyxl`).
  - `{tipo}_{ext}_{MM}.{ext}` / `..._{MM1}-{MM2}.{ext}` (`sep=';'`,
    `utf-8-sig`).

### Checkbox "Enriquecer con datos de planta Unergy"

Visible/aplicable solo para `grip`, `arrpas`, `tgrl`, `cxcsb` (los tipos
cuyo archivo trae código SIC de planta en columna `PLANTA` o
`SUBMERCADO`).

**Fuente: el archivo diario de fronteras del FTP de XM, del mismo
mes/año del dato — no la tabla `fronteras` de la BD.** La BD no guarda
histórico por período (solo el estado actual), y el archivo de fronteras
sí es diario en el FTP, así que respeta el histórico real de cada mes.

- Ruta: `/INFORMACION_XM/USUARIOSK/UNGG/sic/Fronteras/{año}-{mes:02d}/`
  (confirmado en `configuracion.json` de `aenc_reporte.py` — carpeta
  separada de la de `aenc`/`dspcttos`, que usa `.../sic/comercia/{año}-{mes}`).
- Nombre de archivo: `UNGG_FronterasComerciales_{DD-MM-YYYY}.xlsx` — un
  archivo por día (confirmado con 10 muestras locales reales: dic-2025,
  ene a jun-2026).
- Para el mes que se está consultando: `ftp.nlst()` sobre esa carpeta,
  filtrar `UNGG_FronterasComerciales_*.xlsx`, ordenar alfabéticamente y
  tomar el último — como el nombre empieza por `DD` dentro de una carpeta
  de mes fijo, esto da el día más reciente disponible ese mes (mismo
  truco que ya usa `aenc_reporte.py::obtener_fronteras_desde_ftp`).
- Si la carpeta del mes exacto no tiene archivos (mes muy reciente, aún
  sin publicar), retroceder mes a mes hasta encontrar el más cercano
  anterior con datos — igual que hace `aenc_reporte.py` — y **reportar en
  el resultado del job qué mes de fronteras se usó realmente** para cada
  tramo de datos, para que quede trazable.
- **Rango multi-mes**: cada fila se enriquece con el archivo de fronteras
  del mismo mes que su `FechaDocumento` — no un solo archivo para todo el
  rango. Si el rango cubre abril y mayo, se descargan y usan dos
  snapshots de fronteras (último de abril, último de mayo), cada uno
  aplicado solo a las filas de su mes.
- Del Excel se leen por **nombre de columna** (no por índice fijo, para no
  romper si XM reordena columnas): `Código SIC Submercado Exportador`,
  `Nombre de la Frontera`, `Capacidad efectiva [MW]`. Se agregan esas tres
  columnas al resultado; **no** `codigo_frontera`/`Código SIC` (col. A del
  Excel) — ese es el identificador interno tipo `"Frt39007"`, no el código
  de 4 caracteres (`"3A44"`) que traen `PLANTA`/`SUBMERCADO` en
  grip/arrpas/tgrl/cxcsb.
- Merge por ese código contra la columna `PLANTA`/`SUBMERCADO` del archivo
  XM. Códigos sin match se dejan sin enriquecer y se listan en
  `codigos_sin_match: [...]` — no rompen ni abortan el proceso.

**Verificado con datos reales** (`UNGG_FronterasComerciales_31-12-2025.xlsx`,
columna BN = "Código SIC Submercado Exportador"): `3A44`→PLANTA SOLAR
BAYUNCA I, `4Z8L`→MGS 0024 - San Diego Sur, `4Z8N`→MGS 0023 - El Joropo,
todos con su `Capacidad efectiva [MW]` en la misma fila. Antes de dar el
enriquecimiento por bueno, se repite esta misma verificación pero
descargando el archivo directamente del FTP (no la copia local) para el
mes de la prueba end-to-end.

## 5. Backend — endpoints async

Módulo `app/api/v1/xm_descargas.py`. Un mes completo con reintentos puede
tardar más de lo prudente para un solo request HTTP, así que se usa un job
en memoria (el backend corre en un solo proceso uvicorn — confirmado en
`start.sh`, sin `--workers`):

- `POST /api/v1/xm/descargas`
  Body: `{ftp_host, ftp_user, ftp_pass, tipo, extension, fecha_inicio, fecha_fin, enriquecer}`.
  Devuelve `{job_id}` de inmediato. Las credenciales se usan en memoria
  para la conexión y se descartan — nunca se persisten en BD ni se
  escriben en logs.
- `GET /api/v1/xm/descargas/{job_id}`
  Devuelve estado: `descargando` (con contador `x/y archivos`),
  `unificando`, `listo`, `error` (con `error_code` + mensaje humano,
  reusando los códigos de `FTP_*`).
- `GET /api/v1/xm/descargas/{job_id}/archivo?formato=xlsx|txt`
  Descarga el resultado cuando el job está en `listo`.
- Jobs y archivos temporales expiran a la hora de creados (limpieza
  perezosa al consultar/crear jobs nuevos).

## 6. Frontend

`src/views/Finanzas/DescargaXMView.vue` + entrada en
`src/router/index.js` y en el menú de Finanzas (`AppSidebar.vue`).

- Formulario: usuario/clave FTP (checkbox "recordar en esta sesión" →
  `sessionStorage`, se borra al cerrar la pestaña del navegador), dropdown
  tipo (8 tipos), dropdown extensión (10 opciones), date pickers
  inicio/fin, checkbox "Enriquecer con datos de planta Unergy" (habilitado
  solo si el tipo es grip/arrpas/tgrl/cxcsb).
- Botón "Descargar y unificar" → `POST` inicial, luego polling a
  `GET .../{job_id}` cada 2s. Estados visibles: descargando (con
  contador), unificando, listo, error.
- Al llegar a `listo`: dos botones de descarga (Excel / TXT).
- Errores del backend (`FTP_AUTH_FAILED`, `FTP_TIMEOUT`,
  `FTP_FILE_NOT_FOUND`, etc.) se muestran tal cual, sin genérico "algo
  salió mal".
- Paleta de marca: `#2C2039 #915BD8 #F6FF72 #FDFAF7`.

## Validación antes de cerrar

Correr `dspcttos txf mayo 2026` contra el FTP real de XM con las
credenciales de la usuaria: conexión, ruta privada, descarga de ~31
archivos, unificación y export end-to-end.

## Adenda 2026-07-02 (tarde) — pivote a agente local

**Problema descubierto en producción**: Railway no puede conectarse al FTP
de XM (`xmftps.xm.com.co:210`) — el `POST /descargas` original (corriendo
la conexión en un hilo dentro del backend de Railway) fallaba siempre con
`FTP_TIMEOUT` en el paso de `ftp.connect()`, incluso con credenciales
correctas. Se validó que:
- El código de conexión es funcionalmente idéntico al de `aenc_reporte.py`
  (mismo host/puerto/contexto TLS/secuencia auth-login-prot_p-cwd), que sí
  conecta en <1 segundo corriendo en el computador de la usuaria.
- El `docker-compose.yml`/`resolve_route.sh`/README del proyecto de
  referencia (`ftp-xm-main`) confirman que ese conector estaba pensado
  para correr en un host con salida de red específica a XM (VPN/IP
  conocida), no en un servidor cloud genérico.
- La usuaria no tiene forma de gestionar un whitelist de IP con XM.

**Solución**: la conexión real a XM se mueve a un **agente local** que la
usuaria corre en su propio computador (`local_agent/`, mismo repo). La
pestaña "Descarga de XM" (servida desde Vercel) llama directo a
`http://127.0.0.1:8420` desde el navegador — los navegadores permiten
llamadas a `localhost` aunque la página esté en HTTPS. Railway deja de
participar en el flujo de descarga por completo.

Cambios respecto al diseño original:
- **Eliminado**: `app/api/v1/xm_descargas.py` (endpoints en Railway) y su
  registro en `router.py` — no pueden funcionar nunca desde ahí.
- **Sin cambios**: todo `app/services/xm/*` (tipos, plan de descarga,
  fronteras, unificador, ftp_client, downloader, orquestador, jobs) — se
  reutiliza tal cual, solo que ahora se importa desde `local_agent/` en
  vez de desde el backend de Railway.
- **Nuevo**: `local_agent/servidor.py` — mismos 3 endpoints
  (`POST /descargas`, `GET /descargas/{id}`, `GET /descargas/{id}/archivo`),
  sin autenticación (protegido por escuchar solo en `127.0.0.1`), con CORS
  restringido a la URL de producción del frontend
  (`frontend-taupe-six-252g9aw47x.vercel.app`) y a los puertos de dev de
  Vite. Se activa con doble clic en `local_agent/iniciar_descarga_xm.bat`.
- **Frontend**: `src/api/xm.js` ahora apunta a `http://127.0.0.1:8420` en
  vez de al backend de Railway; la vista muestra un aviso de que hace
  falta el agente local corriendo y un mensaje claro si no logra conectar
  con él.

**Validado end-to-end por la ruta real** (navegador → agente local →
FTP de XM): `dspcttos` mayo 2026 (3 días de prueba) — job pasa por
`descargando → unificando → listo`, archivo Excel de 38,640 bytes
descargado correctamente vía `GET /descargas/{id}/archivo`.

## Fuera de alcance (explícitamente)

- Reporte HTML/envío por correo de AENC (`aenc_reporte.py`) — es un
  proceso distinto y ya existe.
- Consultar la tabla `fronteras` de la BD para el enriquecimiento — se
  usa el archivo de fronteras del FTP del mes correspondiente en su
  lugar (ver sección 4), porque respeta el histórico por período.
- Persistir credenciales de XM en BD o `.env` del backend.
- Tipos de archivo fuera de los 8 listados arriba (se agregan en una
  segunda iteración, junto con su ruta pública/privada confirmada).
