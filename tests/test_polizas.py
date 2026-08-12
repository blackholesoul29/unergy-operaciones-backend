# unergy-operaciones-backend/tests/test_polizas.py
"""Pólizas: cálculo de derivados (presupuesto/IPP) y upsert conectado a un
proyecto real, con sesión sqlite en memoria (mismo patrón que
test_arr_arrendadores_crud.py: se llaman las funciones del router
directamente, sin pasar por FastAPI)."""
from app.api.v1.polizas import calcular_derivados


def test_calcular_derivados_suma_presupuesto():
    total, lucro = calcular_derivados(
        mano_obra=1_000_000, estructura=2_000_000, paneles=3_000_000,
        inversores=1_500_000, otros=500_000,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total == 8_000_000
    assert lucro is None


def test_calcular_derivados_presupuesto_vacio_da_none():
    total, _ = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total is None


def test_calcular_derivados_presupuesto_parcial_suma_lo_disponible():
    total, _ = calcular_derivados(
        mano_obra=1_000_000, estructura=None, paneles=None, inversores=None, otros=0,
        ipp_base=None, ipp_provisional=None, tarifa_base=None, generacion_anual_p90_kwh=None,
    )
    assert total == 1_000_000


def test_calcular_derivados_lucro_cesante():
    # % indexación = 110/100 = 1.1 -> tarifa indexada = 200*1.1=220 -> lucro = 220*1000
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=100, ipp_provisional=110, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro == 220_000


def test_calcular_derivados_ipp_base_cero_no_divide():
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=0, ipp_provisional=110, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro is None


def test_calcular_derivados_ipp_incompleto_no_calcula():
    _, lucro = calcular_derivados(
        mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
        ipp_base=100, ipp_provisional=None, tarifa_base=200, generacion_anual_p90_kwh=1000,
    )
    assert lucro is None


from datetime import date
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.proyectos import Proyecto, ProyectoInfoTecnica
from app.models.polizas import Poliza
from app.schemas.polizas import PolizaUpsert
from app.api.v1.polizas import listar, guardar


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Proyecto.__table__, ProyectoInfoTecnica.__table__, Poliza.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto(db, **kwargs):
    p = Proyecto(
        nombre_comercial=kwargs.pop("nombre_comercial", "Planta Test"),
        tipo_proyecto=kwargs.pop("tipo_proyecto", "minigranja"),
        municipio=kwargs.pop("municipio", "Yumbo"),
        departamento=kwargs.pop("departamento", "Valle del Cauca"),
        estado="en_desarrollo",
        **kwargs,
    )
    db.add(p)
    db.flush()
    return p


def test_listar_incluye_proyectos_sin_poliza(db):
    _proyecto(db, nombre_comercial="Sin póliza")

    resultado = listar(search=None, tipo_proyecto=None, poliza_om=None, db=db, _=None)

    assert len(resultado) == 1
    assert resultado[0].numero_poliza is None
    assert resultado[0].fecha_vencimiento is None


def test_listar_filtra_por_busqueda(db):
    _proyecto(db, nombre_comercial="Planta Yumbo")
    _proyecto(db, nombre_comercial="Planta Cali", municipio="Cali")

    resultado = listar(search="Cali", tipo_proyecto=None, poliza_om=None, db=db, _=None)

    assert len(resultado) == 1
    assert resultado[0].nombre_comercial == "Planta Cali"


def test_guardar_crea_poliza_conectada_al_proyecto(db):
    p = _proyecto(db)

    resultado = guardar(
        p.id,
        PolizaUpsert(
            numero_poliza="POL-001", poliza_om=True,
            fecha_vencimiento=date(2027, 1, 1), valor_poliza=5_000_000,
            mano_obra=1_000_000, estructura=1_000_000, paneles=1_000_000,
            inversores=1_000_000, otros=1_000_000,
        ),
        db=db, _=None,
    )

    assert resultado.proyecto_id == p.id
    assert resultado.numero_poliza == "POL-001"
    assert resultado.valor_total_proyecto == 5_000_000

    fila = db.query(Poliza).filter(Poliza.proyecto_id == p.id).first()
    assert fila is not None and fila.proyecto_id == p.id


def test_guardar_actualiza_si_ya_existe_en_vez_de_duplicar(db):
    p = _proyecto(db)
    guardar(p.id, PolizaUpsert(numero_poliza="POL-001"), db=db, _=None)

    resultado = guardar(p.id, PolizaUpsert(numero_poliza="POL-002"), db=db, _=None)

    assert resultado.numero_poliza == "POL-002"
    assert db.query(Poliza).filter(Poliza.proyecto_id == p.id).count() == 1


def test_guardar_404_si_proyecto_no_existe(db):
    with pytest.raises(HTTPException) as exc_info:
        guardar(999, PolizaUpsert(numero_poliza="X"), db=db, _=None)
    assert exc_info.value.status_code == 404
