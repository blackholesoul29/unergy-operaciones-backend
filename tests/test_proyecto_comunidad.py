"""Etiqueta de comunidad energética en Proyecto: columnas nuevas persisten y el
schema las expone. (El endpoint PATCH aplica model_dump(exclude_unset)+setattr
sobre estos mismos campos; aquí se ejercita ese núcleo sin el selectinload pesado
de _get_proyecto_or_404, que requeriría muchas tablas en sqlite.)"""
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto
from app.schemas.proyectos import ProyectoUpdate, ProyectoOut


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_schema_expone_campos():
    assert "es_comunidad_energetica" in ProyectoUpdate.model_fields
    assert "nombre_comunidad" in ProyectoUpdate.model_fields
    assert "es_comunidad_energetica" in ProyectoOut.model_fields


def test_default_es_falso(db):
    p = Proyecto(nombre_comercial="Planta X")
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.es_comunidad_energetica is False
    assert p.nombre_comunidad is None


def test_patch_marca_comunidad(db):
    p = Proyecto(nombre_comercial="Planta Y")
    db.add(p)
    db.commit()
    # núcleo del endpoint PATCH
    payload = ProyectoUpdate(es_comunidad_energetica=True,
                             nombre_comunidad="Comunidad Norte").model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    assert p.es_comunidad_energetica is True
    assert p.nombre_comunidad == "Comunidad Norte"
