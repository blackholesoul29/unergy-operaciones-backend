# Legacy pre-baseline migrations (ARCHIVED — do not run)

These files are the migration scripts that existed **before** Alembic was
adopted as the single source of truth for the schema.

They are kept here only for historical reference. They are intentionally placed
in this subdirectory so that Alembic does **not** load them: Alembic does not
recurse into subdirectories of `version_locations` by default, and
`recursive_version_locations` is not enabled in `alembic.ini`.

## Why they were retired

* The chain was **non-functional**: it contained duplicate revision ids
  (`020` appears twice, `024` appears twice) and multiple heads, so
  `alembic history` / `alembic upgrade head` failed outright.
* There was **no base-table-creating migration**. The core schema was created
  at runtime by `Base.metadata.create_all()` plus a large block of idempotent
  `ALTER TABLE ... IF NOT EXISTS` DDL in `app/main.py` and `init_db.py`.
  Alembic was therefore never the real source of truth.

## What replaced them

A single baseline migration — `../000_baseline_initial_schema.py`
(`revision = 000_baseline`) — now materializes the complete current schema by
reproducing exactly what the application used to do at boot:
`create_all()` for the 69 ORM-mapped tables, followed by the relocated
idempotent DDL block for the ~17 raw-SQL-only tables.

See `docs/MIGRATIONS.md` for how to create and apply future migrations.
