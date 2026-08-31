# unergy-operaciones-backend

Backend FastAPI de la plataforma de Operaciones de Unergy. Base de datos `operations`
en PostgreSQL, externa al despliegue (`POSTGRES_*`/`PG_*` en el `.env`). Se despliega con
`docker compose up -d --build` en el servidor, y automáticamente en cada push a la
rama **`test`** (la de producción, no `master`). Cómo se construye: `README.md`.

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

**Alembic SI se usa, y corre ultimo.** Un solo head, y el `command` del
`docker-compose.yml` aplica `alembic upgrade head` en cada arranque. Lo que confunde es el orden: `create_all()` y las
~518 sentencias de `_PENDING_DDLS` (`app/main.py`) corren **antes**, asi que pueden crear
objetos que luego hagan fallar una revision — y como todo el `upgrade head` va en una
transaccion, un `Duplicate*Error` hace rollback de **toda** la cadena. Por eso las
migraciones se escriben con los helpers de `alembic_idempotencia.py`.

**Donde va cada cambio.** Esquema (CREATE/ALTER/indice/constraint) = revision de Alembic.
Datos (backfill, migracion de filas) = tarea `*_seed` idempotente en `_deferred_init`, nunca
en Alembic: retrasaria el arranque y su fallo es silencioso.

**Tabla nueva = revision de Alembic.** No `_PENDING_DDLS`, y no alcanza con declarar el
modelo y dejarselo a `create_all()`. Las tres razones, en orden de cuanto duelen:

1. `_PENDING_DDLS` no tiene control de version: corre entero en cada arranque y no sabe
   que ya se aplico. Asi se llego a **44 `CREATE TABLE` duplicados**, 15 de ellos
   declarando **menos columnas** que su modelo — no rompia solo porque `create_all()`
   ganaba la carrera.
2. `create_all()` solo sabe crear lo que el modelo sabe expresar. Una `EXCLUDE`
   constraint, un indice parcial, una extension, un trigger o una columna generada no
   viajan por ahi. Toda la Fase 2 del refactor depende de eso.
3. Una revision deja el cambio con fecha, autor, motivo y `downgrade`. Una linea suelta
   en una lista de 478 sentencias, no.

⚠️ **Si ademas declaras el modelo** —que es lo normal, porque el ORM lo necesita—
`create_all()` va a crear la tabla **antes** de que corra tu revision. No es un error, pero
obliga a que la revision sea idempotente: escribila con los helpers de
`alembic_idempotencia.py` y no asumas que la tabla no existe.

⚠️ **Y `_PENDING_DDLS` no es la via rapida para cargar datos.** Se limpio en la Fase 0 (de
551 sentencias a 478, 47 `UPDATE`/`INSERT` movidos a tareas `*_seed`) y el 2026-08-25 ya
habia sentencias de datos nuevas ahi. Cada vez que se usa asi, la limpieza se deshace y el
arranque se alarga para todos.

**El despliegue aborta si la migración falla, y eso es a propósito.** El compose
tiene dos servicios del mismo `Dockerfile`: `migrate` (one-shot,
`init_db.py && alembic upgrade head`, sin `||`) y `operaciones` (solo uvicorn, con
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
