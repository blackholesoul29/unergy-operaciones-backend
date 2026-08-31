# unergy-operaciones-backend

Backend FastAPI de la plataforma de Operaciones de Unergy. Qué hace y cómo está
organizado por dentro: `backend.md`. Convenciones para trabajar en el repo:
`CLAUDE.md`. Este archivo es solo cómo se construye, se corre y se despliega.

## Requisitos

- [uv](https://docs.astral.sh/uv/) para las dependencias (no pip: la verdad está en
  `pyproject.toml` + `uv.lock`).
- Docker + Docker Compose v2 para construir y desplegar.
- Un PostgreSQL alcanzable. La base es externa al compose: se apunta con
  `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `PG_HOST` / `PG_PORT`.

## Configuración

Todo entra por variables de entorno; `.env` es la única fuente y no se commitea.

```bash
cp .env.example .env
```

Mínimo a completar: las cinco `POSTGRES_*`/`PG_*` de la base, `SECRET_KEY`,
`IMAGE` y `PORT`.

La URL de conexión se arma en `app/core/config.py::armar_database_url`, y de ahí
la leen igual la app, Alembic y los scripts. Si el proveedor entrega una URL de
un solo pegue, ponla en `DATABASE_URL` y gana sobre las cinco piezas; acepta
`postgres://` y `postgresql://` tal cual.

⚠️ Desde el contenedor, `PG_HOST=localhost` es el propio contenedor. Si el
Postgres corre en el host, usa `PG_HOST=host.docker.internal` — el compose ya
trae el `extra_hosts` que lo resuelve.

## Correr en local sin Docker

```bash
uv sync                          # crea .venv desde uv.lock
uv run alembic upgrade head      # el esquema sale SOLO de aca
uv run python scripts/verificar_esquema.py
uv run uvicorn app.main:app --reload
```

## Construir la imagen

```bash
docker compose build            # o: docker compose build --no-cache
```

Qué hace el `Dockerfile`, en orden:

1. `python:3.12-slim` como base.
2. `apt-get install libpq-dev gcc libreoffice-calc` — LibreOffice Calc recalcula
   headless las fórmulas de los Estados de Resultados del Panel Contable. Va con
   `--no-install-recommends` a propósito: los recommends (JRE, fuentes, ayuda)
   inflaban la imagen cientos de MB y el build se quedaba sin disco.
3. Copia el binario de `uv` desde `ghcr.io/astral-sh/uv:0.9`.
4. `COPY pyproject.toml uv.lock` y `uv sync --frozen --no-dev`.
5. 
6. 
7. 
8.  Solo los dos
   archivos, antes del código, para que el layer de dependencias se cachee y un
   cambio en un `.py` no reinstale nada.
5. `COPY . .` y `CMD uvicorn app.main:app`.

Dos detalles que no son obvios:

- El venv se instala en **`/opt/venv`** (`UV_PROJECT_ENVIRONMENT`), no en
  `/app/.venv`: el compose monta el repo sobre `/app` y taparía el venv de la
  imagen. `PATH=/opt/venv/bin:$PATH` es lo que hace que `uvicorn` y `alembic` se
  encuentren.
- `--frozen` falla si `uv.lock` está desactualizado respecto al `pyproject.toml`.
  Si el build se queja, corre `uv lock` y commitea los dos archivos.

## Desplegar

```bash
git clone … && cd unergy-operaciones-backend
mkdir -p ../logs uploads
cp .env.example .env && $EDITOR .env
docker compose up -d --build
docker compose logs -f
```

Dos servicios, del mismo `Dockerfile` (ancla `x-app-base` en el
`docker-compose.yml`):

| Servicio | Qué hace |
|---|---|
| `migrate` | One-shot: `alembic upgrade head && alembic current && python scripts/verificar_esquema.py`, y termina. Sin `\|\|`: si falla, sale con código ≠ 0 |
| `operaciones` | Solo `uvicorn`. Espera con `service_completed_successfully` a que `migrate` haya terminado bien |

O sea: **si la migración falla, el servicio no arranca**. Es deliberado — antes el
arranque toleraba el fallo y la app quedaba sirviendo 500 con el esquema atrasado
(ver `tests/test_modelo_vs_ddl.py`).

Desplegar un cambio, a mano:

```bash
git pull
docker compose up -d --build          # rebuild solo si cambió pyproject.toml/uv.lock/Dockerfile
docker compose restart operaciones    # si solo cambió código Python
```

El repo está montado en `/app`, así que un cambio de Python entra con un restart,
sin reconstruir la imagen.

### Deploy automático (runner self-hosted)

`.github/workflows/deploy.yml` corre en cada push a `master`, la rama de
producción. Primero llama a
`tests.yml` como reusable workflow en un runner de GitHub: **si un test falla, el
job `deploy` ni siquiera empieza** — no hay `git pull` ni build en el servidor.
Con la suite verde, el job `deploy` corre en un runner instalado en el mismo
servidor. No hace `checkout`: entra a `DEPLOY_DIR` (variable
de repo, hoy `/home/originabot/unergy-operations/unergy-operaciones-backend`), hace
`git reset --hard origin/<rama>` y usa el diff entre el HEAD viejo y el nuevo
para decidir.

**El `.env` del servidor se reescribe en cada deploy** desde el secret
`ENV_FILE`, así que la configuración se cambia en GitHub y no entrando por SSH.
Corolario: editarlo a mano en el servidor no sirve, el próximo deploy lo pisa.

Para crearlo o actualizarlo, con el `.env` bueno en la mano:

```bash
gh secret set ENV_FILE < .env.prod    # el archivo completo, en un solo secret
```

`.env.prod` es la copia de la configuración de producción; vive en local (o en el
gestor de secretos que usen), nunca en el repo — `.gitignore` bloquea todo
`.env.*` salvo `.env.example`. El `.env` de la raíz sigue siendo el de desarrollo.

Un solo secret en vez de 60 sueltos: agregar una variable no obliga a tocar el
workflow. Antes de escribirlo, el step exige que traiga `SECRET_KEY`, `IMAGE` y
alguna de `DATABASE_URL`/`POSTGRES_DB`, y aborta el deploy si no — con un `.env`
vacío la app arrancaría con los defaults de `app/core/config.py`, apuntando a
`postgres:postgres@localhost`, y `migrate` sembraría ahí. El `.env` anterior queda
en `.env.anterior` por si el secret quedó mal.

`migrate` **no** se levanta en todos los deploys. Corre si:

1. el diff toca `alembic/` — el único camino que aplica esquema desde que se
   retiraron `_PENDING_DDLS` e `init_db.py` (2026-08-31),
2. se lanzó a mano con `workflow_dispatch` y `migrar=siempre`, o
3. `operaciones` no estaba arriba (arranque en frío: no se sabe en qué revisión
   quedó la base).

Si no, el deploy es `docker compose build` + `up -d --no-deps operaciones`. El
`--no-deps` es deliberado: quien decide si se migra es el workflow, no el
`depends_on`.

La migración va con `docker compose run --rm migrate` antes de tocar el servicio:
si falla, el step falla y el contenedor que está sirviendo sigue con la versión
anterior. El último step espera hasta 120 s a que `operaciones` quede `healthy` y,
si no, imprime `ps` + las últimas 80 líneas de log y falla.

### Variables que consume el compose

| Variable | Default | Para qué |
|---|---|---|
| `IMAGE` | — | Tag de la imagen construida |
| `PORT` | 8000 | Puerto de uvicorn, el publicado en el host y el del healthcheck |
| `WORKERS` | 1 | Procesos de uvicorn. **>1 duplica los jobs del `BackgroundScheduler`**, que vive dentro del proceso web |

Las de la base (`POSTGRES_*`, `PG_*`, `DATABASE_URL`) no las usa el compose: van
por `env_file` a los dos servicios y las lee el código.

Puertos y red: `operaciones` publica `${PORT}` en todas las interfaces. Si el
servidor ya tiene nginx/Caddy con TLS, cambia el mapeo a
`"127.0.0.1:${PORT}:${PORT}"`.

Volúmenes: `.:/app` (código), `./uploads:/app/uploads`
(`STORAGE_BACKEND=local` escribe ahí) y `../logs:/home/app/logs`. Los logs de
Docker rotan a 3 × 10 MB (`logging:` en el compose); sin eso llenan el disco.

Zona horaria: el contenedor corre en **UTC** (`TZ=UTC`) porque el código compensa
Colombia (UTC−5) con `_hoy_col()`. No cambiarla.

## Pruebas

```bash
uv sync
uv run pytest -q
```

Deben pasar todas antes de subir. `tests.yml` las corre en cada PR a `master`, y
`deploy.yml` las vuelve a correr como gate antes de cada despliegue.

## Operación

```bash
docker compose ps                                    # estado + healthcheck
docker compose logs -f operaciones
docker compose exec operaciones alembic current      # revisión aplicada
docker compose run --rm migrate                      # re-correr migraciones a mano
docker compose down                                  # bajar todo
```

El healthcheck de `operaciones` abre un socket contra `localhost:${PORT}`; el
endpoint `/health` existe si quieres verificar desde fuera.
