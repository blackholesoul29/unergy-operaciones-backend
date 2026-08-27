"""`audit_log` para los tests que corren sobre SQLite.

La tabla no tiene modelo ORM --la crea `_PENDING_DDLS` en el arranque-- así que
`Base.metadata.create_all()` no la incluye. Cualquier test que ejercite un
camino que escribe auditoría necesita crearla a mano, y tenerlo en un solo sitio
evita que dos copias del DDL se separen.
"""
from sqlalchemy import text

# Misma forma que el DDL de producción (`app/main.py`, bloque "DB audit P0-2"),
# con los tipos que SQLite entiende: BIGSERIAL -> INTEGER AUTOINCREMENT,
# JSONB -> TEXT, TIMESTAMPTZ -> TEXT.
DDL_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tabla TEXT NOT NULL,
    registro_id INTEGER NOT NULL,
    accion TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nombre TEXT,
    cambios TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def crear_audit_log(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(DDL_AUDIT_LOG))
