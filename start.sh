#!/bin/sh
echo "Creating base tables + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init/seed failed — schema may be incomplete (the app lifespan no longer runs DDL); check logs above"
fi
echo "Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "WARNING: Alembic migration failed — check logs above"
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
