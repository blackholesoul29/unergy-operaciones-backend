import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.finanzas_mandatos import FinanzasMandato
from app.services.finanzas_mandatos_service import upsert_mandato


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    FinanzasMandato.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_upsert_crea_y_no_duplica(db_session):
    kw = dict(proyecto="Baraya", tercero="SOLENIUM", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU0521")
    m1, c1 = upsert_mandato(db_session, estado="sin_firma", **kw)
    m2, c2 = upsert_mandato(db_session, estado="firmado", **kw)
    assert c1 is True and c2 is False
    assert m1.id == m2.id
    assert m2.estado == "firmado"


def test_no_degrada_firmado(db_session):
    kw = dict(proyecto="X", tercero="Y", periodo=date(2026, 7, 1), tipo="ingreso", cmu="CMU1")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="sin_firma", **kw)
    assert m.estado == "firmado"


def test_cmu_corregido_guarda_anterior(db_session):
    base = dict(proyecto="X", tercero="Y", periodo=date(2026, 7, 1), tipo="costo")
    upsert_mandato(db_session, estado="sin_firma", cmu="CMU100", **base)
    m, _ = upsert_mandato(db_session, estado="firmado", cmu="CMU200", **base)
    assert m.cmu == "CMU200" and m.cmu_anterior == "CMU100"


def test_router_importa():
    from app.api.v1 import finanzas_mandatos
    assert finanzas_mandatos.router.prefix == "/finanzas/mandatos"
