"""merge_proyectos() -- auditoría de Proyectos 2026-08-27, actualizado 2026-08-31
tras fusionar proyecto_inicio_operacion en proyecto_informe_om.

`proyecto_informe_om` está en `_MERGE_ONE_TO_ONE`: si un proyecto con ficha
de Puesta en Marcha se fusiona con otro, el informe se mueve al ganador en
vez de reventar el DELETE final del perdedor contra el FK (NO ACTION).
"""
import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.informe_om import ProyectoInformeOM
from app.api.v1 import proyectos as proyectos_api
from audit_sqlite import crear_audit_log


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn, rec):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    # El merge audita el borrado del perdedor, y `audit_log` no tiene modelo
    # ORM: create_all() no la crea. Ver `registrar_borrado`.
    crear_audit_log(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_fusionar_mueve_el_informe_om_del_perdedor_al_ganador(db):
    ganador = Proyecto(id=1, nombre_comercial="Ganador")
    perdedor = Proyecto(id=2, nombre_comercial="Perdedor")
    db.add_all([ganador, perdedor])
    db.commit()

    db.add(ProyectoInformeOM(proyecto_id=2, version="v1", conclusion="Operativo"))
    db.commit()

    proyectos_api.merge_proyectos(ganador_id=1, perdedor_id=2, dry_run=False, db=db, _=None)

    assert db.get(Proyecto, 2) is None
    informe = db.query(ProyectoInformeOM).filter_by(proyecto_id=1).first()
    assert informe is not None
    assert informe.version == "v1"
    assert informe.conclusion == "Operativo"
