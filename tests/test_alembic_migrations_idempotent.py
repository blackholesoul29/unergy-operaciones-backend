"""Las migraciones 026–030 deben ser IDEMPOTENTES.

Contexto del deploy (start.sh):

    python init_db.py        # -> Base.metadata.create_all(...) crea TODAS las
                             #    tablas de los modelos (om_documento_proyecto,
                             #    arr_documento, columnas e índices incluidos),
                             #    en su forma FINAL (la del modelo de hoy)
    alembic upgrade head     # corre 026..030

Como ``create_all`` ya construyó esas tablas/columnas/índices, una migración
que use ``op.create_table`` / ``op.add_column`` / ``op.create_index`` "a secas"
revienta con *"already exists"*. Hoy ese error lo traga ``start.sh`` (WARNING)
=> el canal de migraciones queda MUERTO en silencio; y si se mergea el branch
"fail-loud", el deploy crashea. La cadena quedó *resoluble* (un solo head) pero
*no ejecutable*.

Estas pruebas reconstruyen el escenario real: primero crean las tablas en su
forma FINAL (simulando ``create_all``) y luego corren la cadena 026..030,
exigiendo que NO lance — la migración debe detectar lo ya presente y saltarlo.
Corren sobre SQLite en memoria, sin Postgres, aptas para el CI sin base de datos.
"""
import importlib.util
import os

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic",
    "versions",
)

MIGRATIONS = [
    "026_om_documento_proyecto.py",
    "027_om_doc_factura_metadata.py",
    "028_arr_documento.py",
    "029_arr_doc_cuenta_cobro_metadata.py",
    "030_arr_doc_copia_por_predio.py",
]

# Forma FINAL de las tablas tal como las construye Base.metadata.create_all
# (== estado de los modelos de hoy). Si los modelos cambian, este DDL debe
# reflejar el resultado de create_all para que la prueba siga siendo fiel.
_CREATE_ALL_SQL = {
    "om_documento_proyecto": """
        CREATE TABLE om_documento_proyecto (
            id INTEGER PRIMARY KEY,
            contrato_id BIGINT NOT NULL,
            periodo VARCHAR(7) NOT NULL,
            nombre_archivo VARCHAR(500) NOT NULL,
            ruta_local VARCHAR(1000) NOT NULL,
            procesado_en TIMESTAMP,
            numero_factura VARCHAR(30),
            total_sin_impuestos NUMERIC(15,2),
            iva NUMERIC(15,2),
            total_pagar NUMERIC(15,2),
            fecha_facturacion DATE,
            cufe VARCHAR(200),
            CONSTRAINT uq_om_doc_contrato_periodo UNIQUE (contrato_id, periodo)
        )
    """,
    "arr_documento": """
        CREATE TABLE arr_documento (
            id INTEGER PRIMARY KEY,
            arr_proyecto_id BIGINT,
            periodo VARCHAR(7) NOT NULL,
            pago_id INTEGER NOT NULL,
            codigo_contrato VARCHAR(120) NOT NULL,
            tipo_documento VARCHAR(30) NOT NULL,
            nombre_archivo VARCHAR(500) NOT NULL,
            ruta_local VARCHAR(1000) NOT NULL,
            ruta_original VARCHAR(1000),
            nombre_secundario VARCHAR(500),
            ruta_secundario VARCHAR(1000),
            codigo_predio VARCHAR(120),
            numero_cuenta_cobro VARCHAR(60),
            nombre_arrendatario VARCHAR(255),
            valor_individual NUMERIC(15,2),
            fecha_subida TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            CONSTRAINT uq_arr_doc_proyecto_periodo_pago
                UNIQUE (arr_proyecto_id, periodo, pago_id)
        )
    """,
}
# Índices que create_all genera por `index=True` en los modelos.
_CREATE_ALL_INDEXES = [
    "CREATE INDEX ix_arr_documento_periodo ON arr_documento (periodo)",
    "CREATE INDEX ix_arr_documento_arr_proyecto_id ON arr_documento (arr_proyecto_id)",
]


def _load(fname):
    path = os.path.join(VERSIONS_DIR, fname)
    spec = importlib.util.spec_from_file_location(fname.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ops(conn):
    return Operations(MigrationContext.configure(conn))


def _create_fk_parents(conn):
    """Tablas padre referenciadas por las FK (existen en Postgres vía create_all).

    SQLite no valida FK a tablas inexistentes al crear, pero la reflexión de
    ``batch_alter_table`` sí necesita resolverlas; las creamos como stubs.
    """
    conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS arr_proyectos (id INTEGER PRIMARY KEY)")
    conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS contratos_servicio (id INTEGER PRIMARY KEY)")


def _simulate_create_all(conn):
    _create_fk_parents(conn)
    for ddl in _CREATE_ALL_SQL.values():
        conn.exec_driver_sql(ddl)
    for ddl in _CREATE_ALL_INDEXES:
        conn.exec_driver_sql(ddl)


def _run_chain(conn):
    op = _ops(conn)
    for fname in MIGRATIONS:
        mod = _load(fname)
        mod.op = op  # evita el proxy global; opera sobre esta conexión
        mod.upgrade()


def test_chain_runs_clean_after_create_all():
    """``alembic upgrade head`` tras ``create_all`` no debe lanzar.

    Este ES el deploy: create_all ya armó el esquema final, las migraciones
    026..030 deben ser no-ops idempotentes en vez de reventar con
    "already exists".
    """
    eng = create_engine("sqlite://")
    with eng.connect() as conn:
        _simulate_create_all(conn)
        _run_chain(conn)  # <- RED en código no idempotente
        insp = sa.inspect(conn)
        cols = {c["name"] for c in insp.get_columns("arr_documento")}
        # ni se duplicaron columnas ni se perdieron.
        assert {"codigo_predio", "valor_individual", "ruta_original"} <= cols


def test_chain_runs_clean_on_fresh_db():
    """En una BD vacía la cadena construye todo de cero sin lanzar."""
    eng = create_engine("sqlite://")
    with eng.connect() as conn:
        _create_fk_parents(conn)
        _run_chain(conn)
        insp = sa.inspect(conn)
        assert insp.has_table("om_documento_proyecto")
        assert insp.has_table("arr_documento")


def test_chain_idempotent_run_twice():
    """Correr la cadena dos veces seguidas tampoco debe lanzar."""
    eng = create_engine("sqlite://")
    with eng.connect() as conn:
        _create_fk_parents(conn)
        _run_chain(conn)
        _run_chain(conn)
        insp = sa.inspect(conn)
        cols = {c["name"] for c in insp.get_columns("om_documento_proyecto")}
        assert {"numero_factura", "cufe"} <= cols
