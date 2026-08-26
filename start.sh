#!/bin/sh
echo "Running DB init + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init failed — lifespan will retry DDL"
fi
echo "Running Alembic migrations..."
# Se conserva la forma `if ! ...` a proposito: el arranque NO debe abortar si una
# migracion falla (la app tiene que quedar arriba), pero el fallo tampoco puede
# pasar desapercibido como un WARNING de una linea. tests/test_modelo_vs_ddl.py
# vigila justamente este literal: si algun dia esto pasa a abortar, esa prueba
# falla y hay que revisar si el DDL de _PENDING_DDLS sigue siendo la garantia.
if ! alembic upgrade head; then
    echo "############################################################"
    echo "## ALEMBIC FALLO -- el esquema quedo atrasado"
    echo "## La app arranca igual, pero las migraciones NO se"
    echo "## aplicaron. Revisa el error de arriba antes de seguir."
    echo "## Ojo: create_all y _PENDING_DDLS corren ANTES que Alembic"
    echo "## y pueden crear objetos que hagan fallar una revision."
    echo "## Ver alembic_idempotencia.py y docs/refactor/06-plan-migracion.md"
    echo "############################################################"
else
    echo "Alembic OK -- revision aplicada: $(alembic current 2>/dev/null | tail -1)"
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
