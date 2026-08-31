"""Helpers para escribir migraciones idempotentes y verificadas.

Vive en la raíz del repo (no dentro de `alembic/`) porque `alembic` como
nombre de import siempre resuelve al paquete real instalado (pip), nunca a
la carpeta local `alembic/` -- `from alembic._algo import ...` fallaría en
producción con ModuleNotFoundError. `alembic.ini` ya tiene
`prepend_sys_path = .`, que pone la raíz del repo en sys.path (es lo que
permite que `alembic/env.py` haga `from app.models import Base`), así que
un módulo a este nivel se importa igual desde cualquier migración.

Por qué existen estos helpers: `init_db.py` corre `Base.metadata.create_all()`
ANTES de Alembic en cada boot (ver el `command` de docker-compose.yml), y `app/main.py` tiene además
una lista paralela `_PENDING_DDLS` con `ALTER TABLE ... IF NOT EXISTS` que
corre en cada arranque de la app. Cualquiera de esos dos caminos puede crear
una tabla/columna/tipo que una migración de Alembic todavía no ha corrido --
si esa migración asume que el objeto no existe (`op.add_column`/
`op.create_table` sin guarda), truena con `Duplicate*Error`. Como
`run_migrations_online()` (alembic/env.py) envuelve TODO el
`alembic upgrade head` en una sola transacción, un solo error así hace
rollback de TODA la cadena de migraciones pendientes, no solo de la que
falló.

Regla para migraciones nuevas: si agrega una columna, tabla o tipo, usar
estos helpers en vez de las llamadas crudas `op.add_column`/`op.create_table`
-- así un objeto preexistente no tumba el deploy, y si existe con una forma
distinta a la esperada, se entera alguien aquí mismo en vez de fallar en
silencio más adelante.
"""
from alembic import op
from sqlalchemy import text


def columna_existe(bind, tabla: str, columna: str) -> bool:
    return bind.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"
    ), {"t": tabla, "c": columna}).first() is not None


def tabla_existe(bind, tabla: str) -> bool:
    return bind.execute(text("SELECT to_regclass(:t)"), {"t": tabla}).scalar() is not None


def constraint_existe(bind, tabla: str, constraint: str) -> bool:
    return bind.execute(text(
        "SELECT 1 FROM information_schema.table_constraints WHERE table_name = :t AND constraint_name = :c"
    ), {"t": tabla, "c": constraint}).first() is not None


def verificar_columnas(bind, tabla: str, esperadas: set[str], migracion: str) -> None:
    reales = {r[0] for r in bind.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
    ), {"t": tabla})}
    faltantes = esperadas - reales
    if faltantes:
        raise RuntimeError(
            f"Migración {migracion}: la tabla '{tabla}' ya existía (creada por "
            f"create_all()/_PENDING_DDLS antes de que Alembic pudiera correr) pero "
            f"le faltan columnas que se esperaban: {sorted(faltantes)}. Revisar a "
            f"mano antes de reintentar -- no se resuelve solo con IF NOT EXISTS."
        )


def agregar_columna_si_falta(bind, tabla: str, columna) -> None:
    """`columna`: una sa.Column ya construida, la misma que se le pasaría a op.add_column."""
    if columna_existe(bind, tabla, columna.name):
        return
    op.add_column(tabla, columna)


def crear_tabla_si_falta(bind, nombre: str, *columnas, migracion: str, **kw) -> bool:
    """Devuelve True si la creó, False si ya existía (y ya verificó columnas)."""
    if tabla_existe(bind, nombre):
        esperadas = {c.name for c in columnas if hasattr(c, "name")}
        verificar_columnas(bind, nombre, esperadas, migracion)
        return False
    op.create_table(nombre, *columnas, **kw)
    return True
