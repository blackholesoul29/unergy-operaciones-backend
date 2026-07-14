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
#
# Seguimos arrancando el servidor si fallan (un deploy que crash-loopea por una
# migración mala es peor que uno degradado), pero el fallo NO puede ser silencioso:
# dejamos una marca que /health lee y reporta como status=degraded.
MIGRACIONES_FALLIDAS="${MIGRACIONES_FALLIDAS_FILE:-/tmp/migraciones_fallidas}"
rm -f "$MIGRACIONES_FALLIDAS"
if ! alembic upgrade heads; then
    echo "ERROR: MIGRACIONES NO APLICADAS — el servidor arranca con el esquema VIEJO."
    echo "       Si el error de arriba dice 'Multiple head revisions': alembic merge heads"
    echo "       /health reportará status=degraded hasta que se apliquen."
    date -u +%Y-%m-%dT%H:%M:%SZ > "$MIGRACIONES_FALLIDAS" 2>/dev/null || true
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
