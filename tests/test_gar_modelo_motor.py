"""El motor de la réplica: el filtro anti-leakage y el modo de fallo silencioso.

El riesgo del motor no es que reviente, es que devuelva `0.0` sin quejarse porque un
concepto o una entidad no coinciden. Estos tests fijan los nombres verificados contra
archivos reales y comprueban que un dato publicado DESPUÉS del corte no entra.
"""
import datetime

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.base import Base
from app.models.garantias_modelo import GarCalculo, XMArchivo, XMMedida
from app.services.garantias_modelo.motor import exposicion_de_calculo


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_int(element, compiler, **kw):
    return "INTEGER"


DIA = datetime.date(2025, 1, 1)
UTC = datetime.timezone.utc


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[XMArchivo.__table__, XMMedida.__table__, GarCalculo.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _archivo(db, tipo, disponible):
    a = XMArchivo(
        tipo=tipo, nombre_archivo=f"{tipo}0101.tx2", version="tx2",
        periodo_ini=DIA, periodo_fin=DIA,
        disponible_desde=disponible, origen_disponibilidad="derivado",
        sha256=f"{tipo}-{disponible.isoformat()}", bytes_len=1,
        filas_ingeridas=0, esquema_ok=True,
    )
    db.add(a)
    db.flush()
    return a


def _medidas(db, archivo, tipo, entidad, concepto, serie):
    for h, v in enumerate(serie, start=1):
        db.add(XMMedida(archivo_id=archivo.id, tipo=tipo, fecha_documento=DIA,
                        hora=h, entidad=entidad, concepto=concepto,
                        valor=v, version="tx2"))


def _sembrar(db, *, disponible_bal, disponible_trsd, entidad="UNGG",
             concepto_compras="neto de compras en bolsa"):
    bal = _archivo(db, "balcttos", disponible_bal)
    _medidas(db, bal, "balcttos", entidad, concepto_compras, [10.0] * 24)
    _medidas(db, bal, "balcttos", entidad, "neto de ventas en bolsa", [4.0] * 24)
    trsd = _archivo(db, "trsd", disponible_trsd)
    _medidas(db, trsd, "trsd", "NACIONAL", "pbna", [100.0] * 24)
    db.flush()


def _calculo(db, fecha_calculo):
    c = GarCalculo(agente="UNGG", esquema="semanal",
                   fecha_vencimiento=datetime.date(2025, 1, 20),
                   fecha_calculo=fecha_calculo, periodo_ini=DIA, periodo_fin=DIA)
    db.add(c)
    db.flush()
    return c


def test_calcula_la_exposicion_cuando_todo_esta_disponible(db):
    disp = datetime.datetime(2025, 1, 8, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp)
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 13)))
    assert r["valor"] == pytest.approx((10.0 - 4.0) * 100.0 * 24)
    assert r["dias_usados"] == 1
    assert r["completo"] is True


def test_no_usa_datos_publicados_despues_del_corte(db):
    """El filtro anti-leakage. Publicado el 13, calculado el 8: no puede entrar."""
    disp = datetime.datetime(2025, 1, 13, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp)
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 8)))
    assert r["valor"] == 0.0
    assert r["dias_usados"] == 0
    assert r["completo"] is False


def test_precio_no_disponible_descarta_el_dia_entero(db):
    """Sin precio no hay exposición: el día no se cuenta a medias."""
    _sembrar(db,
             disponible_bal=datetime.datetime(2025, 1, 8, tzinfo=UTC),
             disponible_trsd=datetime.datetime(2025, 1, 20, tzinfo=UTC))
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 13)))
    assert r["dias_usados"] == 0


def test_archivo_con_esquema_invalido_no_entra(db):
    disp = datetime.datetime(2025, 1, 8, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp)
    db.query(XMArchivo).filter_by(tipo="balcttos").one().esquema_ok = False
    db.flush()
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 13)))
    assert r["dias_usados"] == 0


def test_otro_agente_no_contamina(db):
    """La entidad de BalCttos es el agente. UNGC no debe sumar a la garantía de UNGG."""
    disp = datetime.datetime(2025, 1, 8, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp, entidad="UNGC")
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 13)))
    assert r["dias_usados"] == 0


def test_concepto_que_no_coincide_da_cero_y_dias_en_cero(db):
    """El modo de fallo silencioso: si el nombre cambia, el valor es 0 pero
    `dias_usados` también — por eso se devuelve, para poder distinguirlo de una
    exposición legítimamente nula."""
    disp = datetime.datetime(2025, 1, 8, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp,
             concepto_compras="netos de compras en bolsa")
    r = exposicion_de_calculo(db, _calculo(db, datetime.date(2025, 1, 13)))
    assert r["valor"] == 0.0
    assert r["dias_usados"] == 0


def test_periodo_incompleto_se_marca(db):
    """Siete días esperados, uno disponible: el número es válido pero parcial."""
    disp = datetime.datetime(2025, 1, 8, tzinfo=UTC)
    _sembrar(db, disponible_bal=disp, disponible_trsd=disp)
    c = _calculo(db, datetime.date(2025, 1, 13))
    c.periodo_fin = datetime.date(2025, 1, 7)
    db.flush()
    r = exposicion_de_calculo(db, c)
    assert r["dias_usados"] == 1
    assert r["dias_esperados"] == 7
    assert r["completo"] is False
