#!/bin/sh
echo "Running DB init + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init failed"
fi

# Adopción del esquema en Alembic.
# El esquema base lo crea init_db.py (Base.metadata.create_all) y, en BDs ya
# existentes, lo construyó históricamente _PENDING_DDLS. Las migraciones 001–025
# eran "solo de registro" y NO son idempotentes (op.add_column/create_table sin
# IF NOT EXISTS), así que reproducirlas sobre un esquema ya creado falla. Por eso,
# si la BD aún no está bajo control de Alembic, la marcamos (stamp) en la última
# revisión de registro (025) sin re-ejecutarla; a partir de ahí `upgrade head`
# aplica solo las migraciones nuevas e idempotentes (026 en adelante).
if [ -z "$(alembic current 2>/dev/null)" ]; then
    echo "BD sin historial Alembic — marcando baseline 025..."
    alembic stamp 025 || echo "WARNING: alembic stamp failed"
fi
echo "Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "WARNING: Alembic migration failed — check logs above"
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
