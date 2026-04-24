#!/bin/sh
set -e
echo "Running DB init + seed..."
python init_db.py
echo "Running Alembic migrations..."
alembic upgrade head
echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
