"""getAllContratos/getFMOData (monitoreo._legacy) filtraban por
servicio_aplica == "operacion", un valor que nunca se usa en produccion (el
contrato real de Operacion y Mantenimiento vive con servicio_aplica ==
"mantenimiento" -- ver ServiciosUnificadoView.vue en el frontend, mismo
hallazgo). Consumido hoy por InformesMensualesPanel.vue (informe FMO O&M):
sin este fix, ese informe siempre reportaba 97%/"Unergy S.A.S." por
defecto para todos los proyectos, nunca los datos reales del contrato.
"""
import asyncio
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.proyectos import Proyecto
from app.models.contratos import ContratoServicio
from app.api.v1.monitoreo import _action_get_all_contratos, _action_get_fmo_data


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto_con_mantenimiento(db):
    p = Proyecto(id=1, nombre_comercial="Planta X", sub_project="planta-x")
    db.add(p)
    db.flush()
    cs = ContratoServicio(
        id=1, proyecto_id=p.id, servicio_aplica="mantenimiento", estado="vigente",
        prestador_nombre="Mantenimientos ABC S.A.S.", numero_contrato="MT-001",
    )
    db.add(cs)
    db.flush()
    return p, cs


def test_get_all_contratos_encuentra_contrato_de_mantenimiento(db):
    _proyecto_con_mantenimiento(db)
    resultado = _action_get_all_contratos(db)
    assert resultado["ok"] is True
    assert len(resultado["contratos"]) == 1
    c = resultado["contratos"][0]
    assert c["sub_project"] == "planta-x"
    assert c["contratista"] == "Mantenimientos ABC S.A.S."


def test_get_fmo_data_encuentra_contrato_de_mantenimiento(db):
    _proyecto_con_mantenimiento(db)
    resultado = asyncio.run(_action_get_fmo_data("planta-x", None, None, db))
    assert resultado["ok"] is True
    assert resultado["contrato"]["contratista"] == "Mantenimientos ABC S.A.S."
