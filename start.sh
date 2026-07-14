#!/bin/sh
echo "Running DB init + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init failed — lifespan will retry DDL"
fi
echo "Running Alembic migrations..."
# `heads` (plural), no `head`: varias ramas se forkean de master a la vez y cada
# una queda como head independiente. Con `head` singular Alembic aborta con
# "Multiple head revisions" y NINGUNA migración se aplica — el servidor arranca
# igual y las tablas nuevas simplemente no existen.
if ! alembic upgrade heads; then
    echo "WARNING: Alembic migration failed — check logs above"
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
