# unergy-operaciones-backend

Backend FastAPI de la plataforma de Operaciones de Unergy. Base de datos `operations`
en PostgreSQL, externa al despliegue (`POSTGRES_*`/`PG_*` en el `.env`). Se despliega con
`docker compose up -d --build` en el servidor, y automáticamente en cada push a
`master` (`.github/workflows/deploy.yml`). Cómo se construye: `README.md`.

## Por dónde empezar según la tarea

| Si vas a tocar… | Lee primero |
|---|---|
| Fallas, monitoreo solar o informes mensuales | `docs/ARQUITECTURA_MONITOREO.md` |
| Cualquier base de datos de Unergy | `docs/UNERGY_DATABASE_ATLAS.md` (6 bases, 511 tablas) |
| Integridad o higiene de datos | `docs/DB_REVIEW_TEAM.md` |
| Un endpoint concreto | `docs/API_*.md` — hay uno por API |
| El build, el compose o el despliegue | `README.md` |

## Cosas que cuesta descubrir solo

**El repo local suele estar atrasado.** Antes de analizar nada:

```bash
git fetch origin && git rev-list --left-right --count master...origin/master
```

Si el segundo número no es 0, lo que estás leyendo no es lo que corre en producción.

**El working tree puede traer trabajo de otra persona.** Revisa `git status` y el
conteo del diff antes de commitear, o desplegarás cambios ajenos.

**Alembic es el UNICO camino para el esquema.** Un solo head. El servicio
`migrate` del compose corre `alembic upgrade head`, `alembic current` y despues
`scripts/verificar_esquema.py`. Ese ultimo compara
los modelos contra la base y **falla el deploy** si el modelo declara una columna o
tabla que la base no tiene — es lo que reemplaza a la vieja `_PENDING_DDLS`.

El 2026-08-31 se retiraron `_PENDING_DDLS` (468 sentencias en `app/main.py`),
`init_db.py` entero y el `create_all()` del lifespan. Corrian en CADA arranque con un try/except
por sentencia, sin control de version: reejecutaban todo, lo ya aplicado respondia
`DuplicateObject`, seis `ALTER TYPE ... RENAME VALUE` fallaban para siempre y un
backfill roto (`proyectos.altitud_msnm`) llevaba meses sin ejecutarse en silencio.
Antes de borrarlas se verifico contra la base que no les quedaba nada por hacer.
Si necesitas ver ese DDL: `git log -S_PENDING_DDLS -- app/main.py`.

**Ya no hay `create_all()`.** Una tabla nueva EXIGE su revision de Alembic: si
solo declaras el modelo, la tabla no se crea en ningun lado y
`scripts/verificar_esquema.py` tumba el deploy. Escribi igual las revisiones con
los helpers de `alembic_idempotencia.py` (una revision puede reaplicarse sobre una
base donde corrio a medias) y, si la tabla tiene un enum, usa
`postgresql.ENUM(..., create_type=False)` en las columnas: `op.create_table` emite
`CREATE TYPE` sin `checkfirst` y revienta con `DuplicateObject` si el tipo ya
existe (paso en la revision 131).

**Sembrar usuarios en un entorno nuevo** es manual y de una sola vez:
`uv run python -m app.seeds.seed_data` (contrasena inicial: `SEED_USER_PASSWORD`).

⚠️ **La cadena de Alembic NO corre desde cero**: la revision 001 referencia
`cliente_servicios`, una tabla que ya no existe en los modelos. Provisionar un
entorno nuevo hoy exige un dump del esquema vivo como baseline; no lo intentes
con `alembic upgrade head` sobre una base vacia.

**Donde va cada cambio.** Esquema (CREATE/ALTER/indice/constraint) = revision de
Alembic. Datos (backfill, migracion de filas) = tarea `*_seed` idempotente en
`_deferred_init`, nunca en Alembic: retrasaria el arranque y su fallo es silencioso.

**El despliegue aborta si la migración falla, y eso es a propósito.** El compose
tiene dos servicios del mismo `Dockerfile`: `migrate` (one-shot,
`alembic upgrade head` + verificacion de esquema, sin `||`) y `operaciones` (solo uvicorn, con
`depends_on: service_completed_successfully`). Si tu revisión falla, el servicio no
levanta — antes toleraba el fallo y la app quedaba sirviendo 500 con el esquema
atrasado. `tests/test_modelo_vs_ddl.py` vigila que no vuelva la tolerancia.

**El código está montado, no copiado.** El compose monta el repo en `/app`, así que
un cambio de Python entra con `docker compose restart operaciones`; solo hace falta
`--build` si cambió `pyproject.toml`, `uv.lock` o el `Dockerfile`. Por eso el venv de
la imagen vive en `/opt/venv` y no en `/app/.venv`: el bind mount lo taparía.

**Dependencias con uv, y `uv.lock` se commitea.** El `Dockerfile` corre
`uv sync --frozen`, que falla si el lock no cuadra con el `pyproject.toml`. `uv add
<paquete>` actualiza los dos; van en el mismo commit o el build se cae.

**`WORKERS=1` no es pereza.** El `BackgroundScheduler` (`app/main.py`) vive dentro del
proceso web: con más de un worker de uvicorn cada uno arranca su propio scheduler y
los jobs corren duplicados. Subirlo exige sacar el scheduler a su propio servicio.

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
uv sync
uv run pytest -q
```

Deben pasar todas antes de subir. Al 31 de agosto de 2026: 2 313 pruebas (4 skipped).
