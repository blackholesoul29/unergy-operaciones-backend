# Database migrations (Alembic)

Alembic is the **single source of truth** for the database schema. The
application no longer runs any `CREATE TABLE` / `ALTER TABLE` / `CREATE TYPE`
DDL at startup — schema creation and evolution happen exclusively through
Alembic migrations.

## TL;DR

| Situation | Command |
|-----------|---------|
| Fresh / empty database | `alembic upgrade head` |
| Existing database whose schema already matches (e.g. current production) | `alembic stamp 000_baseline` (run **once**) |
| Create a new migration after changing a model | `alembic revision --autogenerate -m "describe change"` |
| Apply pending migrations | `alembic upgrade head` |
| Inspect state | `alembic current`, `alembic history`, `alembic heads` |

The connection URL is taken from `DATABASE_URL` (or the `POSTGRES_*` /
`RAILWAY_TCP_PROXY_*` variables) — see `alembic/env.py`.

## Baseline migration

`alembic/versions/000_baseline_initial_schema.py` (`revision = 000_baseline`)
is the root migration. Its `upgrade()` reproduces the exact bootstrap the app
used to perform at runtime:

1. `Base.metadata.create_all()` — every ORM-mapped table (69) and the
   PostgreSQL ENUM types behind `Enum` columns.
2. A block of idempotent DDL (relocated verbatim from `app/main.py`) for the
   ~17 raw-SQL-only tables that have no ORM model (`audit_log`, `api_keys`,
   `clima_*`, `om_*`, `precios_bolsa_*`, `informes_guardados`, `alarma_estado`,
   `alarmas_monitoreo`, ...).

Every statement is `IF [NOT] EXISTS` / try-excepted, so applying the baseline to
a database that already has (some of) the schema is a safe no-op.

The previous, non-functional migration chain is archived under
`alembic/versions/legacy_pre_baseline/` (not loaded by Alembic).

## Deploying

`alembic upgrade head` **must run before the application process starts**. It is
already wired into `start.sh` (which the Docker image runs as its `CMD`):

```sh
alembic upgrade head        # bring schema to latest
python init_db.py           # seed catalog/reference data (no DDL)
uvicorn app.main:app ...
```

### One-time step for the existing production database

Production was built by the old runtime DDL, so its schema already matches
`000_baseline`, but its `alembic_version` table may be empty or point at a
retired legacy revision. Run **once**, before the first deploy of this change:

```sh
alembic stamp 000_baseline
```

`stamp` overwrites `alembic_version` without executing the migration, marking
the database as already at the baseline. After that, normal
`alembic upgrade head` works for all future migrations.

> If you skip the stamp, `start.sh`'s `alembic upgrade head` will simply
> re-run the idempotent baseline — harmless because every statement is
> `IF [NOT] EXISTS` — unless `alembic_version` still references an unknown
> legacy revision, in which case Alembic errors. Stamping avoids that.

## Adding a future schema change

1. Edit the relevant model under `app/models/`.
2. Generate a migration:
   ```sh
   alembic revision --autogenerate -m "add proyectos.nueva_columna"
   ```
3. **Review** the generated script in `alembic/versions/`. Autogenerate does not
   detect everything (enum value additions, server defaults, some constraints) —
   add those by hand if needed.
4. Apply it:
   ```sh
   alembic upgrade head
   ```

## Known autogenerate drift (review carefully)

The ORM models are a *subset* of the real schema: years of raw `ALTER TABLE`
DDL added partial indexes and a couple of columns that were never declared on
the models. Because `--autogenerate` only compares against `Base.metadata`, it
will propose **spurious `op.drop_index(...)` / `op.drop_column(...)`** for these
raw-DDL-only objects. As of this baseline that is:

* ~40 partial indexes (those with a `postgresql_where=...`, e.g.
  `ix_clientes_nit`, `ix_fallas_codigo_legado_unique`, `ix_asic_*`).
* `proyectos.requestsdb_supply_id` and `proyectos.quoia_node_name`
  (cross-database correlation columns used via raw SQL).

These objects are real and intentional — they are created by the baseline
migration and must **not** be dropped. When you run `--autogenerate`, delete
those spurious drop operations from the generated script before applying it.

Whole-table drops are already prevented: the 17 raw-SQL-only tables are excluded
via `include_object` in `alembic/env.py` (`RAW_SQL_TABLES`).

A future cleanup could declare those indexes/columns on the models (and add the
raw tables as ORM models) to make autogenerate diffs clean; that is out of scope
for the Alembic adoption itself.

## Local development from scratch

```sh
createdb operaciones
alembic upgrade head        # build the full schema
CREATE_ALL_ON_STARTUP=true python init_db.py   # optional: create_all + seed
```

`init_db.py` only runs `Base.metadata.create_all()` when
`CREATE_ALL_ON_STARTUP=true`; otherwise it just seeds data and leaves schema
management to Alembic.
