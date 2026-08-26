"""get_mediana_consumo() / get_forma_consumo() (historial.py) -- qué días
alimentan el histórico de Consumo.

Quitado el filtro por revisar_manualmente (2026-08-26, pedido de Sara): lo
que importa es si la FUENTE fue real (caso 'Medidor'/'CGM'), no si ese día
puntual quedó marcado para revisar por otro motivo (ej. alejarse de la
mediana, o -- antes -- pertenecer a FRONTERAS_VALIDAR_CGM_VS_MEDIDOR, que
siempre queda revisar_manualmente=True)."""
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaConsumo
from app.services.reporte_energia import historial


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Frontera.__table__, ReporteEnergiaConsumo.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _frontera(db, id_=1):
    front = Frontera(id=id_, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.consumo_auxiliar, codigo_frontera="frt001")
    db.add(front)


def _fila(db, id_, frontera_id, fecha, caso, energia, revisar, curva=None):
    db.add(ReporteEnergiaConsumo(
        id=id_, frontera_id=frontera_id, fecha=fecha, caso=caso,
        energia_final_kwh=energia, curva_final=curva or [energia / 24] * 24,
        revisar_manualmente=revisar,
    ))


def test_dia_marcado_revisar_igual_alimenta_la_mediana(db):
    """MIN_DIAS_CONSUMO = 3 -- con 3 días 'CGM', uno de ellos marcado para
    revisar, la mediana ya se puede calcular (antes ese día quedaba
    excluido y hacían falta más días sin marcar)."""
    _frontera(db)
    _fila(db, 1, 1, date(2026, 8, 20), "CGM", 30.0, revisar=False)
    _fila(db, 2, 1, date(2026, 8, 21), "CGM", 32.0, revisar=False)
    _fila(db, 3, 1, date(2026, 8, 22), "CGM", 15.0, revisar=True)  # outlier, marcado
    db.commit()

    mediana, dias = historial.get_mediana_consumo(db, 1, date(2026, 8, 23))

    assert dias == 3
    assert mediana == 30.0  # mediana de [30, 32, 15]


def test_caso_historico_sigue_excluido_aunque_no_este_marcado(db):
    """'Histórico' es ya una estimación -- no debe alimentar el histórico
    sin importar revisar_manualmente."""
    _frontera(db)
    _fila(db, 1, 1, date(2026, 8, 20), "CGM", 30.0, revisar=False)
    _fila(db, 2, 1, date(2026, 8, 21), "CGM", 32.0, revisar=False)
    _fila(db, 3, 1, date(2026, 8, 22), "Histórico", 999.0, revisar=False)
    db.commit()

    mediana, dias = historial.get_mediana_consumo(db, 1, date(2026, 8, 23))

    assert dias == 2  # 'Histórico' no cuenta -- no llega al mínimo de 3
    assert mediana is None


def test_forma_consumo_tambien_incluye_dias_marcados_revisar(db):
    _frontera(db)
    curva_a = [1.0] * 24
    curva_b = [2.0] * 24
    curva_c = [0.5] * 24  # marcado para revisar, igual cuenta
    _fila(db, 1, 1, date(2026, 8, 20), "CGM", 24.0, revisar=False, curva=curva_a)
    _fila(db, 2, 1, date(2026, 8, 21), "CGM", 48.0, revisar=False, curva=curva_b)
    _fila(db, 3, 1, date(2026, 8, 22), "CGM", 12.0, revisar=True, curva=curva_c)
    db.commit()

    forma, dias = historial.get_forma_consumo(db, 1, date(2026, 8, 23))

    assert dias == 3
    assert forma is not None
