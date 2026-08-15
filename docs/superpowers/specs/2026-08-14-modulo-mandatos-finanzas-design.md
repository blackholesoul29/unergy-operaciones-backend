# Módulo "Mandatos" (Finanzas) — Diseño

Fecha: 2026-08-14
Estado: aprobado (diseño), pendiente plan de implementación

## Objetivo

Un módulo nuevo en **Finanzas**, llamado **Mandatos**, que muestra por período el
estado de firma de los mandatos de **ingresos y costos**, alimentado desde el
correo de la revisoría fiscal por un script local. Es un tablero para saber, de un
vistazo, **qué mandatos faltan por firmar** (o volvieron con comentarios).

Reemplaza el flujo manual actual (bajar adjuntos del correo a mano). Es
**independiente** del módulo viejo "Mandatos (Costos)" (`/mandatos`), que NO se toca.

## Por qué un módulo nuevo (no el viejo)

El módulo viejo (`app/api/v1/mandatos.py`, tabla `mandatos`) existe pero está
dormido (31 registros de prueba de mayo 2025, 0 firmados) y es **solo de costos**,
llavea por CMU y su integración de correo quedó como "Fase B" sin construir.
Decisión del usuario: construir uno nuevo para ingresos+costos y no arriesgar el
viejo.

## Arquitectura (3 piezas)

### 1. Script local (extendido)
El harvester que ya existe en `C:\Users\jessi\OneDrive\Documentos\MandatosRevisoria\mandatos_revisoria.py`.
- Lee el correo de forma **incremental** (mantiene `estado_procesados.json`; no
  re-baja el pasado en cada corrida).
- Por cada correo con la revisora, extrae de cada adjunto: **CMU**, **tipo**
  (ingreso/costo), **proyecto**, **tercero/inversionista**, y del **asunto** el
  **período**.
- Clasifica **estado de firma** por dirección: revisora en `De` = firmado;
  revisora en `Para/CC` = sin_firma.
- Lee el **cuerpo** del correo: si la revisora menciona un CMU con lenguaje de
  corrección ("diferencia", "corregir", "ajuste", "está mal"…), marca ese mandato
  como **con_comentarios** y guarda el texto.
- En vez de solo guardar a carpetas, hace **POST a la API** (`/ingest`) con los
  metadatos + el PDF. Se autentica con un **token** guardado en su config.
- Se dispara manualmente (un `.bat` / comando).

### 2. Backend (nuevo, sin tocar el viejo)
Tabla nueva `finanzas_mandato`:

| Campo | Tipo | Notas |
|---|---|---|
| id | PK | |
| proyecto | str | de la identidad |
| tercero | str | inversionista/mandante |
| periodo | date | primer día del mes; **del asunto del correo** |
| tipo | enum | `ingreso` \| `costo` |
| cmu | str, nullable | atributo (puede corregirse) |
| cmu_anterior | str, nullable | si hubo corrección de consecutivo |
| estado | enum | `sin_firma` \| `firmado` \| `con_comentarios` |
| comentario | text, nullable | texto extraído del correo |
| fecha_envio | date, nullable | primer correo hacia la revisora |
| fecha_firma | date, nullable | correo de vuelta firmado |
| drive_file_id / drive_url | str, nullable | PDF firmado en Google Drive |
| pdf_sin_firma_drive_url | str, nullable | opcional: la versión enviada |
| correo_ref | str, nullable | Message-ID / asunto de referencia |
| created_at / updated_at | ts | |

- **Identidad (clave lógica):** `(proyecto, tercero, periodo, tipo)`. El CMU es un
  atributo que puede cambiar; si llega un nuevo CMU para la misma identidad, se
  **actualiza** el mismo registro (guardando `cmu_anterior`), NO se duplica.
- Índice único sobre `(proyecto, tercero, periodo, tipo)`.

Endpoints:
- `POST /finanzas/mandatos/ingest` — idempotente. Recibe metadatos + PDF; sube el
  PDF a **Google Drive** (reusa el servicio Drive existente, `app/services/drive.py`);
  upsert por identidad. Si el estado entrante es `firmado`, actualiza fecha_firma y
  el PDF; si es `con_comentarios`, guarda el comentario. Nunca degrada un `firmado`
  a `sin_firma`.
- `GET /finanzas/mandatos?periodo=&tipo=` — lista del período.
- `GET /finanzas/mandatos/resumen?periodo=` — métricas: Total, Firmados,
  Falta firma, Con comentarios (por tipo).
- Auth: token de servicio para el `/ingest` (el script) + `get_current_user` para
  las lecturas.

### 3. Frontend (nueva vista en Finanzas)
`src/views/Finanzas/MandatosFinanzas.vue` (nombre tentativo):
- Selector de mes (estilo Facturación) + pestañas **Ingresos / Costos**.
- Tarjetas de métricas: **Total · Firmados · Falta firma · Con comentarios**.
- Tabla: CMU, proyecto, tercero, estado (badge de color), fecha envío, fecha firma,
  comentario (si hay), **link al PDF en Drive**.
- Filtro rápido: "solo falta firma" / "con comentarios".
- Consume `GET /finanzas/mandatos` y `/resumen`.

## Flujo de datos

```
Correo (buzón de Jessica, incremental)
  → script local: parse (cmu, tipo, proyecto, tercero, periodo, estado, comentario) + PDF
  → POST /finanzas/mandatos/ingest (token)
      → PDF a Google Drive
      → upsert por (proyecto, tercero, periodo, tipo)
  → GET /finanzas/mandatos  →  vista Finanzas/Mandatos
```

## Reglas de negocio

- **Período**: mes del **asunto** del correo (regex de meses en español). Año: del
  asunto si aparece; si no, del año de la fecha del correo (con ajuste en el borde
  diciembre/enero).
- **Tipo**: del nombre del archivo — `costo` si contiene "Mandato-Costos", si no
  `ingreso`.
- **Estado de firma (manejo normal):** volvió de la revisora = `firmado`. No se
  verifica la firma criptográficamente (comprobado: la revisora no firma
  digitalmente, 0/60 con firma digital) ni por peso del PDF (comprobado no
  confiable: firmado pesa más solo ~50% de las veces). Se confía en el correo.
- **Falta firma** = existe registro `sin_firma` sin su par `firmado` para la misma
  identidad.
- **Consecutivo corregido**: mismo `(proyecto, tercero, periodo, tipo)` con distinto
  CMU → se actualiza el registro (no duplica), guardando `cmu_anterior`.
- **Con comentarios**: el cuerpo del correo de la revisora menciona el CMU con
  lenguaje de corrección. Heurístico (no perfecto); guarda el texto para revisión.

## Fuera de alcance (v1)

- Enviar correos a la revisora o a inversionistas (era la "Fase B" del viejo).
- Conciliación contable de costos.
- Mandatos que debían existir pero nunca se enviaron (el tablero se basa en lo que
  pasó por el correo).
- Verificación real de firma escaneada (imagen) y botón manual "marcar revisar"
  (se puede agregar después; no v1).
- Que el backend lea Gmail directamente (se decidió: lo hace el script local; el
  servidor no maneja credenciales de correo).

## Riesgos / a validar en implementación

1. **Parsing de proyecto+tercero** del nombre del archivo: limpio en costos
   (`CMU####-Mandato-Costos-{Proyecto}-{Inversionista}.pdf`), más variable en
   ingresos. Es la base de la identidad → hay que validarlo contra los nombres
   reales antes de confiar en el conteo.
2. **Heurística de "con comentarios"**: lenguaje natural; puede tener falsos
   positivos/negativos.
3. **Autenticación del script** al backend: definir el mecanismo de token de
   servicio sin exponer credenciales.
4. **Almacenamiento en Drive**: carpeta destino, permisos del service account, y
   evitar duplicar el PDF en re-ingestas.

## No se toca

El módulo viejo `/mandatos` (tabla `mandatos`, `MandatosOperaciones.vue`) queda
intacto.
