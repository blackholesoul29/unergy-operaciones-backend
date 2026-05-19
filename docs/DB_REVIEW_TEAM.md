# Auditoría de Bases de Datos — Unergy
> Revisión completa: 19 de mayo 2026
> 6 bases de datos · 511 tablas · ~49 GB · ~6.2M filas

---

## Resumen Ejecutivo

Se auditaron las 6 bases de datos PostgreSQL que soportan la operación de Unergy. La auditoría revisó esquemas, relaciones, integridad, rendimiento e higiene de datos en cada base.

### Estado General

| Base de datos | Servidor | Tamaño | Tablas | Tablas vacías | Salud |
|--------------|----------|--------|--------|---------------|-------|
| **originabotdb** | GCP 34.74.198.101 | 30 GB | 269 | 141 (52%) | ⚠️ Requiere limpieza |
| **requestsdb** | GCP 34.74.198.101 | 17 GB | 101 | 65 (64%) | ⚠️ Requiere limpieza |
| **operations** | Railway | — | 62 | — | ✅ Bien estructurada |
| **rag** | AWS 54.174.147.51 | 1 GB | 11 | 0 | ✅ OK |
| **edubotapp** | AWS 54.174.147.51 | 42 MB | 7 | 0 | ✅ OK |
| **samantha_memory** | EVO-X2 local | 441 MB | 61 | 23 (37%) | ✅ Bien estructurada |

### Hallazgos por severidad
- **P0 (Crítico)**: 4 hallazgos — riesgo de pérdida de datos o degradación de rendimiento
- **P1 (Importante)**: 6 hallazgos — deuda técnica que afecta desarrollo y escalabilidad
- **P2 (Mejora)**: 5 hallazgos — optimizaciones y buenas prácticas

---

## P0 — Críticos (Acción inmediata)

### P0-1. Audit log sin control de retención (3M filas, ~75% del almacenamiento)

**Impacto:** Las tablas `django_tracker_auditlog` consumen la mayoría del espacio en disco de ambos servidores GCP.

| Base | Tabla | Filas | Impacto estimado |
|------|-------|-------|-----------------|
| requestsdb | `django_tracker_auditlog` | 2,438,465 | ~12-14 GB |
| originabotdb | `django_tracker_auditlog` | 584,938 | ~3-4 GB |

**Problema:** No hay política de retención. Estos logs crecen indefinidamente y representan ~75% del almacenamiento total de las bases GCP.

**Acción:**
```sql
-- 1. Verificar antigüedad de los registros más viejos
SELECT MIN(timestamp), MAX(timestamp), COUNT(*) 
FROM django_tracker_auditlog;

-- 2. Archivar registros mayores a 6 meses (backup primero)
CREATE TABLE django_tracker_auditlog_archive AS 
SELECT * FROM django_tracker_auditlog 
WHERE timestamp < NOW() - INTERVAL '6 months';

-- 3. Eliminar registros archivados
DELETE FROM django_tracker_auditlog 
WHERE timestamp < NOW() - INTERVAL '6 months';

-- 4. Recuperar espacio
VACUUM FULL django_tracker_auditlog;

-- 5. Agregar política de retención automática (cron semanal)
-- DELETE FROM django_tracker_auditlog WHERE timestamp < NOW() - INTERVAL '1 year';
```

**Responsable:** DevOps / Backend  
**Ahorro estimado:** 15-18 GB entre ambas bases

---

### P0-2. Operations DB no tiene auditoría de cambios

**Impacto:** Si alguien modifica o elimina un proyecto, contrato PPA, liquidación o falla, no queda rastro. No hay forma de saber quién cambió qué ni cuándo.

**Problema:** La base `operations` (Railway) no tiene ninguna tabla de auditoría, a diferencia de originabotdb que tiene `django_tracker_auditlog`.

**Acción:**
```sql
-- Crear tabla de auditoría
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    tabla VARCHAR(100) NOT NULL,
    registro_id BIGINT NOT NULL,
    accion VARCHAR(10) NOT NULL,      -- INSERT, UPDATE, DELETE
    usuario_id BIGINT,
    cambios JSONB,                     -- {campo: {antes: x, despues: y}}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tabla_registro ON audit_log(tabla, registro_id);
CREATE INDEX idx_audit_fecha ON audit_log(created_at);
```

Implementar en el backend con un middleware SQLAlchemy que registre automáticamente los cambios en tablas críticas: `proyectos`, `ppa_contratos`, `liquidaciones`, `fallas`, `clientes`, `fronteras`.

**Responsable:** Backend  
**Prioridad:** Antes de ir a producción con más usuarios

---

### P0-3. Referencias entre bases de datos son strings sin validación

**Impacto:** Los vínculos entre `originabotdb` y `operations` pueden desincronizarse silenciosamente.

**Problema:** La tabla `operations.proyectos` tiene:
- `origina_code VARCHAR` → referencia a `originabotdb.minifarm_project.code`
- `requestsdb_supply_id VARCHAR` → referencia a `requestsdb.supplies_supplyrequest.id`

Son strings, no foreign keys. Si se borra un proyecto en originabotdb, operations no se entera. Nadie valida que estos códigos existan.

**Acción:**
1. Crear un script de reconciliación que corra semanalmente:
```python
# reconcile_projects.py
# Lee proyectos de operations, verifica que origina_code exista en originabotdb
# Reporta discrepancias por Slack/Discord

import psycopg2

ops = psycopg2.connect("operations_url")
origina = psycopg2.connect("originabotdb_url")

ops_cur = ops.cursor()
ops_cur.execute("""
    SELECT id, nombre_comercial, origina_code 
    FROM proyectos 
    WHERE origina_code IS NOT NULL
""")

origina_cur = origina.cursor()
origina_cur.execute("SELECT code FROM minifarm_project")
valid_codes = {row[0] for row in origina_cur.fetchall()}

orphans = []
for pid, nombre, code in ops_cur.fetchall():
    if code not in valid_codes:
        orphans.append((pid, nombre, code))

if orphans:
    print(f"⚠️ {len(orphans)} proyectos en operations con origina_code inválido:")
    for pid, nombre, code in orphans:
        print(f"  id={pid} '{nombre}' → origina_code='{code}' NO EXISTE")
```

2. A largo plazo: definir cuál base es Source of Truth para proyectos y que la otra lea de ella.

**Responsable:** Backend + DevOps

---

### P0-4. Tablas sin Primary Key

**Impacto:** Tablas sin PK no pueden tener replicación lógica, no se pueden hacer UPSERTs, y son más difíciles de mantener.

| Base | Tabla | Filas |
|------|-------|-------|
| originabotdb | `django_celery_beat_crontabschedule` | 8 |
| originabotdb | `django_celery_beat_periodictask` | 17 |
| originabotdb | `django_celery_beat_periodictasks` | 1 |
| requestsdb | `tiger.zip_lookup_all` | 0 |

**Acción:** Agregar PKs a las 3 tablas de celery_beat (son de la librería django-celery-beat, verificar si una actualización de la librería lo soluciona). La tabla tiger se puede eliminar (ver P1-2).

**Responsable:** Backend

---

## P1 — Importantes (Sprint actual o siguiente)

### P1-1. 52% de originabotdb y 64% de requestsdb son tablas vacías

**Problema:**
- originabotdb: 141 de 269 tablas tienen 0 filas
- requestsdb: 65 de 101 tablas tienen 0 filas

Módulos completamente vacíos en originabotdb:
- `dataroom_*` (10 tablas) — nunca se usó el Data Room
- `timeline_*` (7 tablas) — nunca se usó el módulo de Timeline
- `silk_*` (5 tablas) — Django Silk profiler nunca se activó
- `easyaudit_*` (3 tablas) — reemplazado por django_tracker
- `cities_light_*` (4 tablas) — reemplazado por `territorial_*`
- `legal_validation_*` (2 tablas) — módulo abandonado
- `engineering_*` (2 tablas) — nunca se usó
- `government_*` (4 tablas, 1 fila total) — prácticamente vacío

**Acción:** No eliminar todavía, pero marcar como candidatos a deprecación. Crear documento de ownership por módulo: ¿quién es responsable de cada uno? Los que no tengan dueño se pueden archivar.

**Responsable:** Tech Lead + Product

---

### P1-2. requestsdb tiene 34 tablas PostGIS Tiger vacías

**Problema:** El esquema `tiger` (geocodificador de US Census) fue instalado con PostGIS pero nunca se pobló. Son 34 tablas y funciones que agregan complejidad sin valor.

**Acción:**
```sql
-- Verificar que no hay datos
SELECT schemaname, tablename, n_live_tup 
FROM pg_stat_user_tables 
WHERE schemaname IN ('tiger', 'topology');

-- Si todo está en 0:
DROP SCHEMA tiger CASCADE;
DROP SCHEMA topology CASCADE;
```

**Responsable:** DevOps  
**Ahorro:** Reduce complejidad de backups y migraciones

---

### P1-3. `fronteras` tiene 88 columnas (God Table)

**Problema:** La tabla `operations.fronteras` es la más ancha del ecosistema con 88 columnas. Mezcla información de:
- Identificación (código frontera, nombre, tipo)
- Registro XM (fechas, estados, códigos SIC)
- Equipos de medición (marca, modelo, clase exactitud)
- Punto de conexión (nivel tensión, transformador)
- Facturación (cuentas, tarifas)
- Relaciones (gemela, agrupada, embebida, proyecto)

**Impacto:** Dificulta el mantenimiento, aumenta el riesgo de bugs, hace queries innecesariamente costosos (SELECT * trae 88 columnas).

**Acción recomendada:** Descomponer en 4 tablas:
```
fronteras (core)           → id, proyecto_id, codigo_frontera, tipo, estado
fronteras_registro_xm      → frontera_id, codigo_sic, fecha_registro, estado_xm, ...
fronteras_medicion          → frontera_id, marca_medidor, modelo, clase_exactitud, ...
fronteras_facturacion       → frontera_id, cuenta, tarifa_base, ...
```

**Responsable:** Backend  
**Nota:** Requiere migración de datos y actualización de queries

---

### P1-4. `validation_field` + `validation_weightfield` = 2.3M filas en originabotdb

**Problema:** Estas dos tablas representan ~2.3M filas y son las más pesadas después de audit logs. Cada uno de los 6,332 terrenos tiene ~181 campos de validación × ~184 scores de peso. Es un diseño EAV (Entity-Attribute-Value) que escala mal.

**Contexto:** Estas tablas alimentan el scoring de terrenos para evaluar viabilidad. ¿Todos los terrenos necesitan todas las 245 plantillas de campos?

**Acción:**
1. Auditar cuántos `validation_field` tienen valor no-nulo vs. nulo:
```sql
SELECT 
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE value IS NOT NULL AND value != '') as con_valor,
    ROUND(100.0 * COUNT(*) FILTER (WHERE value IS NOT NULL AND value != '') / COUNT(*), 1) as pct_llenos
FROM validation_field;
```

2. Si <30% tiene valor, considerar migrar a JSONB:
```sql
-- Alternativa: un JSONB por terrain con solo los campos que tienen valor
ALTER TABLE termsheet_terrain ADD COLUMN validation_data JSONB DEFAULT '{}';
```

**Responsable:** Backend (módulo de validación)

---

### P1-5. Estadísticas desactualizadas en edubotapp y rag

**Problema:** `pg_stat_user_tables.n_live_tup` reporta 0 para todas las tablas de `edubotapp` y `rag`, pero los datos existen (82K mensajes Discord, 126K filas en rag). Esto significa que el planificador de queries está tomando decisiones sub-óptimas.

**Acción:**
```sql
-- Ejecutar en edubotapp
ANALYZE;

-- Ejecutar en rag
ANALYZE;

-- Verificar que autovacuum está habilitado
SHOW autovacuum;
-- Si está off:
ALTER DATABASE edubotapp SET autovacuum = on;
ALTER DATABASE rag SET autovacuum = on;
```

**Responsable:** DevOps

---

### P1-6. Más de 300 FK columns sin índice dedicado en originabotdb

**Problema:** Se encontraron ~350 columnas de FK en originabotdb que no tienen índice propio. Esto significa que cualquier JOIN o DELETE cascada hace un sequential scan completo.

**Tablas más críticas afectadas (con datos reales):**

| Tabla | FK sin índice | Filas |
|-------|--------------|-------|
| `validation_field.project_id → minifarm_project` | ❌ | 1.15M |
| `validation_field.terrain_id → termsheet_terrain` | ❌ | 1.15M |
| `validation_weightfield.field_id → validation_field` | ❌ | 1.16M |
| `termsheet_filesofterrain.terrain_id` | ❌ | 29K |
| `termsheet_terrainstatuschange.terrain_id` | ❌ | 20K |
| `termsheet_terrainpowerofattorney.terrain_id` | ❌ | 17K |
| `termsheet_terraincomment.terrain_id` | ❌ | 16K |
| `prospecting_contactnote.contact_id` | ❌ | 1.4K |

**Acción:**
```sql
-- Índices más urgentes (tablas con >10K filas)
CREATE INDEX CONCURRENTLY idx_validation_field_project 
    ON validation_field(project_id);
CREATE INDEX CONCURRENTLY idx_validation_field_terrain 
    ON validation_field(terrain_id);
CREATE INDEX CONCURRENTLY idx_validation_weightfield_field 
    ON validation_weightfield(field_id);
CREATE INDEX CONCURRENTLY idx_termsheet_filesofterrain_terrain 
    ON termsheet_filesofterrain(terrain_id);
CREATE INDEX CONCURRENTLY idx_termsheet_terrainstatuschange_terrain 
    ON termsheet_terrainstatuschange(terrain_id);
CREATE INDEX CONCURRENTLY idx_termsheet_terrainpowerofattorney_terrain 
    ON termsheet_terrainpowerofattorney(terrain_id);
CREATE INDEX CONCURRENTLY idx_termsheet_terraincomment_terrain 
    ON termsheet_terraincomment(terrain_id);
```

**Responsable:** Backend / DBA  
**Nota:** Usar `CONCURRENTLY` para no bloquear lecturas en producción

---

## P2 — Mejoras (Backlog)

### P2-1. Tres espacios de embeddings incompatibles

| Base | Modelo | Dimensiones | Uso |
|------|--------|------------|-----|
| edubotapp | Google (desconocido) | 3072 | Summaries de Discord |
| rag | gemini-embedding-001 | 1536 | LightRAG knowledge graph |
| samantha_memory | mxbai-embed-large | 1024 | Memoria personal AI |

**Problema:** No se puede hacer búsqueda semántica entre bases de datos. Un query en rag no puede buscar en samantha ni viceversa.

**Acción:** Estandarizar en un solo modelo de embeddings para datos de negocio Unergy. Candidato: `gemini-embedding-001` (1536d) ya que es el más usado en el pipeline de Edubot.

---

### P2-2. `investment_minifarm` duplica `minifarm_project`

**Problema:** Ambas tablas tienen exactamente 3,089 filas — la misma cantidad de proyectos. `investment_minifarm` es una copia de `minifarm_project` con campos adicionales de inversión.

**Acción:** Debería ser una relación FK, no una tabla separada. Los campos de inversión deberían vivir en una tabla `investment_project_details` con FK a `minifarm_project.id`.

---

### P2-3. Falta soft delete en operations

**Problema:** Si se borra un proyecto, cliente o contrato PPA en operations, se pierde permanentemente.

**Acción:**
```sql
ALTER TABLE proyectos ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE clientes ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE ppa_contratos ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE fallas ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE liquidaciones ADD COLUMN deleted_at TIMESTAMPTZ;

-- Agregar filtro por defecto en el backend:
-- .filter(Proyecto.deleted_at.is_(None))
```

---

### P2-4. Índices faltantes en operations

```sql
-- Queries frecuentes que se beneficiarían de índices
CREATE INDEX idx_proyectos_estado ON proyectos(estado);
CREATE INDEX idx_proyectos_cliente ON proyectos(cliente_id);
CREATE INDEX idx_proyectos_origina ON proyectos(origina_code) WHERE origina_code IS NOT NULL;
CREATE INDEX idx_fallas_estado_proyecto ON fallas(estado_id, proyecto_id);
CREATE INDEX idx_fallas_fecha ON fallas(fecha_reporte DESC);
CREATE INDEX idx_liquidaciones_proyecto_periodo ON liquidaciones(proyecto_id, periodo);
CREATE INDEX idx_ppa_contratos_comprador ON ppa_contratos(comprador_id);
CREATE INDEX idx_generacion_proyecto_fecha ON generacion_diaria(proyecto_id, fecha);
CREATE INDEX idx_fronteras_proyecto ON fronteras(proyecto_id);
CREATE INDEX idx_fronteras_codigo ON fronteras(codigo_frontera);
```

---

### P2-5. Usuarios fragmentados en 4 bases de datos

**Problema:** No hay un directorio unificado de usuarios.

| Base | Tabla | Filas | Identificador |
|------|-------|-------|---------------|
| originabotdb | `auth_user` | 262 | email (Django) |
| requestsdb | `auth_user` | 13 | email (Django) |
| operations | `usuarios` | — | email (FastAPI) |
| edubotapp | `discord_users` | 332 | discord_snowflake_id |

**Acción a largo plazo:** Crear tabla de directorio unificado en operations:
```sql
CREATE TABLE user_directory (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    nombre VARCHAR(255),
    origina_user_id INTEGER,
    requests_user_id INTEGER,
    operations_user_id BIGINT,
    discord_user_id BIGINT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Mapa de Relaciones entre Bases de Datos

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│   originabotdb (GCP)              operations (Railway)           │
│   ┌─────────────────┐            ┌──────────────────┐           │
│   │ minifarm_project │──origina──►│ proyectos        │           │
│   │ (3,089 projects) │  _code    │ (source of truth) │           │
│   │                  │            │                   │           │
│   │ termsheet_terrain│            │ fronteras (88col) │           │
│   │ (6,332 terrains) │            │ ppa_contratos     │           │
│   │                  │            │ liquidaciones     │           │
│   │ contract_*       │            │ fallas            │           │
│   │ investment_*     │            │ clientes          │           │
│   │ validation_*     │            │ precios_bolsa_*   │           │
│   │ (2.3M rows!)     │            │ clima_*           │           │
│   └─────────────────┘            └──────────────────┘           │
│           │                              ▲                       │
│           │                              │ API                   │
│   requestsdb (GCP)               ┌──────┴───────┐               │
│   ┌─────────────────┐            │  Frontend    │               │
│   │ supplies_*       │──request──►│  (Vue 3)     │               │
│   │ (18K requests)   │  _db_id   │              │               │
│   │ entities_*       │            └──────────────┘               │
│   │ management_*     │                                           │
│   │ (transformers)   │                                           │
│   └─────────────────┘                                           │
│                                                                  │
│   edubotapp (AWS)       rag (AWS)         samantha (EVO-X2)     │
│   ┌──────────────┐    ┌──────────┐       ┌──────────────┐      │
│   │ discord_msgs │───►│ LightRAG │◄──────│ contracts    │      │
│   │ (82K msgs)   │    │ entities │  tool │ trm_*        │      │
│   │ summaries    │    │ relations│  call │ memories     │      │
│   └──────────────┘    └──────────┘       └──────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Source of Truth por Entidad

| Entidad | SoT Actual | SoT Recomendado | Notas |
|---------|-----------|-----------------|-------|
| Proyectos | originabotdb (legacy) | **operations.proyectos** | Deprecar escrituras directas a originabotdb |
| Terrenos | originabotdb | originabotdb (hasta migrar) | No existe en operations todavía |
| Contratos PPA | operations | operations | Ya correcto |
| Clientes | operations | operations | Ya correcto |
| Supply Requests | requestsdb | requestsdb | Workflow especializado, mantener |
| Infraestructura eléctrica | requestsdb | requestsdb | PostGIS especializado, mantener |
| Precios energía | energy-api + operations | operations (persistir) | energy-api debería escribir a operations |
| Discord knowledge | edubotapp → rag | Mantener pipeline actual | Agregar tagging por proyecto |
| Usuarios | Fragmentado (4 bases) | operations con user_directory | Ver P2-5 |

---

## Checklist de Acciones

### Esta semana
- [ ] **P0-1:** Verificar antigüedad de audit logs y ejecutar limpieza en requestsdb
- [ ] **P0-2:** Crear tabla `audit_log` en operations + middleware de auditoría
- [ ] **P1-5:** Ejecutar `ANALYZE` en edubotapp y rag
- [ ] **P1-6:** Crear los 7 índices más urgentes en originabotdb (CONCURRENTLY)

### Este mes
- [ ] **P0-3:** Implementar script de reconciliación de proyectos entre bases
- [ ] **P0-4:** Resolver PKs faltantes en celery_beat
- [ ] **P1-1:** Documentar ownership de módulos vacíos en originabotdb
- [ ] **P1-2:** Eliminar esquema tiger/topology de requestsdb

### Backlog
- [ ] **P1-3:** Planificar descomposición de `fronteras` (88 → 4 tablas)
- [ ] **P1-4:** Auditar densidad de `validation_field` para evaluar migración a JSONB
- [ ] **P2-1:** Estandarizar modelo de embeddings
- [ ] **P2-2:** Refactorizar `investment_minifarm` como FK
- [ ] **P2-3:** Agregar soft delete a tablas críticas de operations
- [ ] **P2-4:** Crear índices en operations
- [ ] **P2-5:** Diseñar user_directory unificado

---

## Apéndice: Datos de la Auditoría

- **Herramienta:** Script Python con psycopg2 + introspección de `pg_catalog`
- **Fecha:** 2026-05-19
- **Datos raw:** `data/db_audit_raw.json` (2.2 MB, esquemas completos 5 bases)
- **Operations:** `data/db_audit_operations.json` (122 KB, extraído de modelos SQLAlchemy)
- **Atlas completo:** `data/UNERGY_DATABASE_ATLAS.md` (referencia técnica detallada)

---

*Documento generado por auditoría automatizada. Revisar con equipo técnico antes de ejecutar acciones en producción.*
