#!/bin/sh
# Arranque del ops backend: init de esquema → migraciones Alembic → servidor.
#
# init_db.py se tolera (solo WARNING): si falla, el lifespan de la app reintenta
# el DDL pendiente, así que el esquema runtime se autorrepara.
#
# Alembic NO tiene ese fallback: si `alembic upgrade head` falla (p.ej. múltiples
# heads por ids de revisión duplicados), las migraciones simplemente NO corren.
# Tragarse ese fallo con un WARNING arranca el servidor contra un esquema
# desincronizado de forma silenciosa. Por eso aquí Alembic falla en voz alta
# (exit != 0) y el orquestador (Docker/k8s) reinicia y lo hace visible.
echo "Running DB init + seed..."
if ! python init_db.py; then
    echo "WARNING: DB init failed — lifespan will retry DDL"
fi

# Precheck: 'alembic upgrade head' exige exactamente un head. Con varios heads
# falla con "Multiple head revisions are present"; lo detectamos antes para dar
# un diagnóstico claro en lugar de un stacktrace.
echo "Verificando heads de Alembic..."
HEAD_COUNT=$(alembic heads 2>/dev/null | grep -c '(head)')
if [ "$HEAD_COUNT" != "1" ]; then
    echo "ERROR: Alembic tiene $HEAD_COUNT head(s); se requiere exactamente 1." >&2
    echo "Varios heads → 'alembic upgrade head' falla y NINGUNA migración se aplica." >&2
    echo "Para arreglarlo: inspecciona los heads abajo y relinealiza la cadena a UNO solo" >&2
    echo "  (re-apunta el 'down_revision' de las ramas divergentes para encadenarlas)," >&2
    echo "  luego valida con: pytest tests/test_alembic_chain_integrity.py" >&2
    echo "Heads actuales:" >&2
    alembic heads >&2
    exit 1
fi

echo "Running Alembic migrations..."
if ! alembic upgrade head; then
    echo "ERROR: Alembic migration failed — abortando arranque (esquema desincronizado)." >&2
    echo "Revisa los logs de arriba; el servidor NO se inicia con migraciones pendientes." >&2
    exit 1
fi

echo "Starting server..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
