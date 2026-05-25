#!/bin/sh
echo "Running DB init + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init failed — lifespan will retry DDL"
fi
echo "Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "WARNING: Alembic migration failed — check logs above"
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
