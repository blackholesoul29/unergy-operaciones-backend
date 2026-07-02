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
| cxcsb      | auto-detectar (pública primero, si falla con 403/404 reintenta privada; se registra cuál funcionó) | mensual `{tipo}MM.ext` |

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

Cuando está marcado:
- `SELECT codigo_frontera, nombre_frontera, capacidad_efectiva_mw FROM fronteras`
- Merge por código SIC contra la columna `PLANTA`/`SUBMERCADO` del archivo.
- Agrega columnas `Nombre de la Frontera`, `Tipo de Frontera`,
  `Capacidad efectiva [MW]` (mismo nombre de columnas que el notebook).
- No se descarta ninguna fila — todas las fronteras del universo XM de
  Unergy interesan siempre (confirmado por la usuaria).

**Pre-requisito de implementación**: antes de codear este merge, correr un
`SELECT` real contra `fronteras.codigo_frontera` y confirmar que los
códigos SIC de planta (tipo `4Z8L`, `3A44`, etc.) están efectivamente
poblados ahí — la tabla existe y se llena vía
`scripts/cargar_fronteras_gescon.py`, pero no se ha verificado cobertura
completa de los ~52 códigos del notebook. Si faltan códigos, reportarlo
antes de dar la funcionalidad por lista (no rellenar con el diccionario
del notebook por debajo sin avisar).

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

## Fuera de alcance (explícitamente)

- Reporte HTML/envío por correo de AENC (`aenc_reporte.py`) — es un
  proceso distinto y ya existe.
- Descarga del Excel de fronteras del FTP de XM — no aporta nada que
  `fronteras.codigo_frontera` en BD no tenga ya.
- Persistir credenciales de XM en BD o `.env` del backend.
- Tipos de archivo fuera de los 8 listados arriba (se agregan en una
  segunda iteración, junto con su ruta pública/privada confirmada).
