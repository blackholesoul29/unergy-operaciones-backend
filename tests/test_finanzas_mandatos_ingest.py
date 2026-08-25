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


def test_empareja_por_cmu_aunque_varie_el_nombre(db_session):
    # El escenario que inflaba 298: mismo CMU, proyecto con nombre distinto
    upsert_mandato(db_session, proyecto="El Llano Sas Bic (1)", tercero="Ayura",
                   periodo=date(2026, 3, 1), tipo="ingreso", cmu="CMU0642", estado="sin_firma")
    m, creado = upsert_mandato(db_session, proyecto="El Llano Sas Bic", tercero="Ayura X",
                               periodo=date(2026, 3, 1), tipo="ingreso", cmu="CMU0642", estado="firmado")
    assert creado is False           # NO crea duplicado
    assert m.estado == "firmado"     # se marca firmado el mismo registro


def test_respaldo_por_proyecto_cuando_cmu_corregido(db_session):
    # Consecutivo corregido: mismo proyecto+tercero, CMU distinto -> mismo mandato
    upsert_mandato(db_session, proyecto="Baraya", tercero="SOLENIUM",
                   periodo=date(2026, 2, 1), tipo="costo", cmu="CMU0617", estado="sin_firma")
    m, creado = upsert_mandato(db_session, proyecto="Baraya", tercero="SOLENIUM",
                               periodo=date(2026, 2, 1), tipo="costo", cmu="CMU0619", estado="firmado")
    assert creado is False
    assert m.cmu == "CMU0619" and m.cmu_anterior == "CMU0617"


def test_upsert_asigna_corregido(db_session):
    kw = dict(proyecto="P", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU1")
    upsert_mandato(db_session, estado="con_comentarios", comentario="ajustar", **kw)
    m, _ = upsert_mandato(db_session, estado="corregido", **kw)
    assert m.estado == "corregido"
    assert m.comentario is None


def test_upsert_asigna_enviado_inversionista_y_su_fecha(db_session):
    kw = dict(proyecto="P2", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU2")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="enviado_inversionista",
                          fecha=date(2026, 8, 1), **kw)
    assert m.estado == "enviado_inversionista"
    assert m.fecha_envio_inversionista == date(2026, 8, 1)


def test_upsert_sigue_sin_degradar_un_firmado(db_session):
    """Comportamiento existente que NO debe cambiar."""
    kw = dict(proyecto="P3", tercero="T", periodo=date(2026, 7, 1),
              tipo="costo", cmu="CMU3")
    upsert_mandato(db_session, estado="firmado", **kw)
    m, _ = upsert_mandato(db_session, estado="sin_firma", **kw)
    assert m.estado == "firmado"


def test_registrar_envio_no_degrada_un_mandato_ya_entregado(db_session):
    """Caso real (CMU1180, corrida del 2026-08-20): un mandato ya entregado al
    inversionista vuelve a aparecer en el correo de lote que lo mandó a
    revisión. Registrar ese envío estampa fecha_envio y nada más: el estado NO
    retrocede. La bitácora debe reportar el estado que quedó, no el que se pidió
    -- reportar 'sin_firma' ahí hacía ver un retroceso que nunca ocurrió.
    """
    kw = dict(proyecto="Iml Empaques", tercero="Ayurá S.A.S",
              periodo=date(2026, 7, 1), tipo="ingreso", cmu="CMU1180")
    upsert_mandato(db_session, estado="enviado_inversionista", **kw)
    m, creado = upsert_mandato(db_session, estado="sin_firma", **kw)
    assert creado is False
    assert m.estado == "enviado_inversionista"
    assert m.fecha_envio is not None
