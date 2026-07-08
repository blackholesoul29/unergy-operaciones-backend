"""Guarda contra el footgun de ``server_default`` con SQL crudo mal escapado.

Pasar una expresión SQL como str plano a ``server_default`` (p.ej.
``server_default="'[]'::jsonb"``) hace que SQLAlchemy la trate como un LITERAL
y la re-escape a ``DEFAULT '''[]''::jsonb'`` — JSON inválido que revienta
``create_all`` en un deploy desde cero (DR / CI / entorno nuevo) con
``invalid input syntax for type json``. Lo correcto para JSONB vacío es el
literal simple ``server_default="[]"`` (o ``text("'[]'::jsonb")``).

Estos tests compilan el DDL real y fallan si vuelve a colarse el patrón.
"""
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models import Base


def _table_ddls():
    dialect = postgresql.dialect()
    return {
        name: str(CreateTable(table).compile(dialect=dialect))
        for name, table in Base.metadata.tables.items()
    }


def test_ningun_default_tiene_comillas_triples():
    """El triple-quote ``'''`` es la firma del str-SQL doble-escapado."""
    offenders = [name for name, ddl in _table_ddls().items() if "'''" in ddl]
    assert not offenders, (
        "server_default con SQL crudo doble-escapado (usar text(...) o literal "
        f"simple) en tablas: {offenders}"
    )


def test_defaults_jsonb_de_arreglo_vacio_son_validos():
    """Las columnas conocidas de arreglo JSON deben rendir ``DEFAULT '[]'``."""
    ddls = _table_ddls()
    esperado = {
        "clientes": ("correos_operacionales", "correos_cgm"),
        "mandato_inversionistas": ("correos", "proyectos"),
    }
    for tabla, columnas in esperado.items():
        ddl = ddls[tabla]
        for col in columnas:
            linea = next(l for l in ddl.splitlines() if f"{col} " in l)
            assert "DEFAULT '[]'" in linea, f"{tabla}.{col} default inválido: {linea.strip()}"
            assert "'''" not in linea
