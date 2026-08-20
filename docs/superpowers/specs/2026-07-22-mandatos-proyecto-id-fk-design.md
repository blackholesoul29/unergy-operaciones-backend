# Diseño — FK `mandatos.proyecto_id`

**Fecha:** 2026-07-22
**Tipo:** Cambio de esquema + datos (backend)
**Estado:** Aprobado (pendiente de plan de implementación)

## Problema

La tabla `mandatos` referencia al proyecto solo con un campo de **texto libre**
(`proyecto: VARCHAR(255)`, `app/models/mandatos.py:49`) — sin llave foránea a
`proyectos`. Esto impide joins fiables, permite nombres inexistentes o mal
escritos y deja el vínculo dependiendo de coincidencia por nombre.

Las demás tablas de costos ya tienen su FK correcta y **no** se tocan:
`contratos_servicio.proyecto_id`, `costos_variables.proyecto_id`,
`liquidaciones.proyecto_id`. `liquidacion_costos` se relaciona con el proyecto a
través de su liquidación padre (por diseño; tampoco se toca).

## Objetivo

Agregar `mandatos.proyecto_id` como FK real a `proyectos.id`, enlazar los
registros existentes de forma conservadora, y hacer que los nuevos mandatos
nazcan enlazados. Conservar el texto `proyecto` como respaldo/legacy.

## Alcance

- **Incluye:** solo la tabla `mandatos` (modelo, esquema en producción, backfill,
  enlazado al crear, exposición en API, tests).
- **No incluye:** cambios en `proyectos`, otras tablas de costos, ni el endpoint
  de re-enlace manual (posible iteración futura).

## Contexto técnico del repo (crítico)

En este repo conviven **tres mecanismos** que tocan el esquema, y Alembic **no**
es el camino confiable de deploy:

1. `create_all` (arranque, `app/main.py`): crea solo tablas faltantes; **nunca**
   altera una tabla existente.
2. **Bloque DDL idempotente de arranque** (`app/main.py`, lista de
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`): **es el camino garantizado** para
   agregar columnas en producción (ver notas de migración 031 y del bloque
   starlink en `main.py`).
3. Alembic `upgrade head` (en `start.sh`): corre con **fallback de
   solo-advertencia**; si falla, el deploy continúa.

Como todos los pasos usan `IF NOT EXISTS`, son idempotentes y no hay conflicto
entre ellos, sin importar el orden ni el estado de la BD (nueva o producción).
Head único confirmado: `046` (la rama `5650ccf73b5c` de starlink ya está
fusionada vía `020` y el merge `037`).

## Diseño

### 1. Modelo — `app/models/mandatos.py`
- Nueva columna `proyecto_id: Mapped[int | None]` con
  `ForeignKey("proyectos.id", ondelete="SET NULL")`, `nullable=True`, `index=True`.
- `relationship("Proyecto")` **unidireccional** (sin `back_populates`, para no
  modificar `proyectos.py`; mismo patrón que `mantenimiento_impacto`).
- Se conserva el campo `proyecto` (texto).

### 2. Esquema en producción — doble vía idempotente
- **Bloque DDL de arranque (`app/main.py`)** — camino garantizado:
  - `ALTER TABLE mandatos ADD COLUMN IF NOT EXISTS proyecto_id BIGINT REFERENCES proyectos(id)`
  - `CREATE INDEX IF NOT EXISTS ix_mandatos_proyecto_id ON mandatos (proyecto_id)`
- **Migración `alembic/versions/047_mandato_proyecto_id.py`** (`down_revision = "046"`):
  misma DDL con `IF NOT EXISTS` en `upgrade()`; `downgrade()` revierte índice y
  columna. Para historia/paridad y desarrollo local.

### 3. Backfill — paso idempotente en el arranque (Python)
- Función nueva ejecutada en el startup (junto a `ensure_maestra` y demás pasos).
- Selecciona `mandatos WHERE proyecto_id IS NULL AND proyecto IS NOT NULL`.
- **Match exacto normalizado**, reutilizando `app/utils/nombre_matching.normalizar`:
  si `normalizar(proyecto)` coincide con **exactamente un** proyecto por
  `normalizar(nombre_comercial)`, asigna `proyecto_id`; si hay 0 o >1, queda NULL.
- Nunca sobrescribe un `proyecto_id` ya asignado ni modifica el texto. Solo
  afecta filas sin enlazar (tabla pequeña; costo despreciable por boot).
- **No** usa coincidencia difusa (decisión: conservador, mejor NULL que enlace
  equivocado en datos contables).

### 4. Enlazado al crear — `app/api/v1/mandatos.py`
- En `crear` (POST `/mandatos`) y `upload_zip` (POST `/mandatos/upload-zip`):
  tras obtener el nombre del proyecto, resolver con
  `app/utils/proyecto_matching.find_proyecto_by_name(db, nombre)` (utilidad
  canónica ya usada en `contratos_servicio`/`monitoreo`, con desambiguación que
  no adivina ante empate) y guardar `proyecto_id`. Se sigue guardando `proyecto`
  (texto).

### 5. Exposición en API
- `app/services/mandatos_service.mandato_to_dict`: agregar `proyecto_id` al dict.
- `app/schemas/mandatos.py`: agregar `proyecto_id` en el esquema de respuesta.

### 6. Tests — `tests/test_mandatos.py`
- Backfill: nombre con match exacto → enlaza; ambiguo o sin match → NULL.
- Creación: `crear` y `upload_zip` pueblan `proyecto_id` cuando el nombre resuelve.

## Seguridad de datos y despliegue
- Todo se despliega vía Git → Railway (nada de BD directa).
- Idempotente en los tres mecanismos; el backfill solo rellena NULLs por match
  exacto; nunca pisa datos existentes ni el texto legacy.

## Riesgos / notas
- Nombres que no den match exacto quedan en `proyecto_id = NULL` (aceptable; se
  llenan al crear/editar en adelante, o en una iteración futura de re-enlace).
- `ondelete="SET NULL"`: si se borra un proyecto, el mandato conserva su historia
  con `proyecto_id = NULL` y el texto legacy.

## Fuera de alcance (posible futuro)
- Endpoint/UI para re-enlazar manualmente los mandatos que queden en NULL.
- Migrar el texto `proyecto` a solo-FK (deprecación del campo legacy).
