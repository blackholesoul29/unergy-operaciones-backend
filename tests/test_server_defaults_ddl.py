"""Guarda contra `server_default` mal escrito, en TODOS los modelos.

Origen (2026-08-19, producción): `mandato_correos` no se pudo crear porque su
modelo declaraba

    server_default="'{}'::jsonb"

Como es un str plano, SQLAlchemy lo trata como literal y lo re-entrecomilla al
compilar, generando `DEFAULT '''{}''::jsonb'`, que Postgres rechaza con
"invalid input syntax for type json". Lo correcto es envolverlo en `text()`,
que le dice a SQLAlchemy que ya es una expresión SQL.

Lo insidioso del caso: el mismo error llevaba meses en `mandato_inversionistas`
sin dar la cara, porque `create_all` solo crea tablas que faltan y esa ya
existía en producción. Solo apareció cuando se agregó una tabla NUEVA que
además usaba el patrón. Un modelo que hoy funciona puede estar roto para el día
que alguien levante una base desde cero.

Por eso este test barre todos los modelos, no solo los de mandatos.
"""
import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401  -- registra todos los modelos en Base.metadata
from app.models.base import Base


def _tablas():
    return sorted(Base.metadata.tables.values(), key=lambda t: t.name)


@pytest.mark.parametrize("tabla", _tablas(), ids=lambda t: t.name)
def test_el_ddl_no_lleva_comillas_duplicadas(tabla):
    """`'''` en el DDL significa que un server_default se re-entrecomilló."""
    ddl = str(CreateTable(tabla).compile(dialect=postgresql.dialect()))
    assert "'''" not in ddl, (
        f"El DDL de {tabla.name} trae comillas duplicadas -- casi seguro un "
        f"server_default declarado como str en vez de text(). DDL:\n{ddl}"
    )


def test_los_defaults_jsonb_compilan_a_sql_valido():
    """Caso concreto que rompió producción, fijado aparte para que se lea.

    El literal va SIN el cast `::jsonb` a propósito. Postgres convierte solo un
    `DEFAULT '{}'` sobre una columna JSONB, y omitir el cast mantiene el DDL
    válido también en SQLite, donde corren varios tests que crean las tablas con
    un `@compiles(JSONB, "sqlite")` propio. Con `::jsonb` el `::` se emite tal
    cual y SQLite lo rechaza con "unrecognized token".
    """
    from app.models.mandatos import MandatoCorreo

    for modelo, esperado in (
        (MandatoCorreo, "detalle JSONB DEFAULT '{}' NOT NULL"),
    ):
        ddl = str(CreateTable(modelo.__table__).compile(dialect=postgresql.dialect()))
        assert esperado in ddl, f"esperaba {esperado!r} en el DDL de {modelo.__tablename__}"
        assert "::jsonb" not in ddl, (
            f"{modelo.__tablename__} volvió a usar el cast ::jsonb, que rompe SQLite")
