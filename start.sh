#!/bin/sh
# Schema is owned by Alembic — see docs/MIGRATIONS.md.
# For an existing database migrating to the baseline for the first time, run
# `alembic stamp 000_baseline` ONCE before deploying this change.

echo "Running Alembic migrations (alembic upgrade head)..."
if ! alembic upgrade head; then
    echo "ERROR: Alembic migration failed — check logs above."
    echo "       If alembic_version points at a retired legacy revision, run"
    echo "       'alembic stamp 000_baseline' once, then redeploy."
fi

echo "Seeding reference data..."
if ! python init_db.py; then
    echo "WARNING: data seed failed — see logs above."
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
