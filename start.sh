#!/bin/sh
set -e
echo "Running DB init + seed..."
python init_db.py
echo "Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "WARNING: Alembic migration failed — check logs above"
fi
echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
