# unergy-operaciones-backend

Backend FastAPI de la plataforma de Operaciones de Unergy. Base de datos `operations`
en PostgreSQL (Railway), desplegado automáticamente desde `master`.

## Por dónde empezar según la tarea

| Si vas a tocar… | Lee primero |
|---|---|
| Fallas, monitoreo solar o informes mensuales | `docs/ARQUITECTURA_MONITOREO.md` |
| Cualquier base de datos de Unergy | `docs/UNERGY_DATABASE_ATLAS.md` (6 bases, 511 tablas) |
| Integridad o higiene de datos | `docs/DB_REVIEW_TEAM.md` |
| Un endpoint concreto | `docs/API_*.md` — hay uno por API |

## Cosas que cuesta descubrir solo

**El repo local suele estar atrasado.** Antes de analizar nada:

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```

Si el segundo número no es 0, lo que estás leyendo no es lo que corre en producción.

**El working tree puede traer trabajo de otra persona.** Revisa `git status` y el
conteo del diff antes de commitear, o desplegarás cambios ajenos.

**Migraciones sin Alembic.** Columna nueva = `ALTER ... IF NOT EXISTS` en el
`add_columns()` de `init_db.py`. Tabla nueva = modelo + `create_all`.

**Producción no se escribe desde local.** El `.env` local no apunta a producción. La
única vía es una tarea `*_seed` en `_deferred_init`, que corre dentro del contenedor.

**Zona horaria.** Colombia es UTC−5 sin horario de verano y el contenedor corre en
UTC. Usa `_hoy_col()`, no `date.today()`: entre las 19:00 y medianoche de Bogotá el
servidor ya está en el día siguiente.

**Fuente de verdad del esquema.** Ante cualquier duda sobre una columna o una clave
foránea, gana el DDL: `esquema-bd-produccion/esquema_produccion.sql` (está en la raíz
del workspace, fuera de este repo). Los documentos derivados pueden tener errores —
`DEPURACION.md`, por ejemplo, afirma que `mantenimiento_impacto.falla_id` no tiene
clave foránea, y sí la tiene.

## Pruebas

```bash
python -m pytest -q
```

Deben pasar todas antes de subir. Al 23 de agosto de 2026: 1 551 pruebas.
