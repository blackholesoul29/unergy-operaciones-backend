"""Job de alertas proactivas de vencimiento de PPA
(app/jobs/ppa_expiration_checker.py).

Rescate de una feature que solo vivia en una rama abandonada
(nightwatch/contratos-fronteras-hardening-20260714 / fable/alembic-train-
renumber-083-20260825), confirmada como un hueco real en la auditoria de
integridad de Fronteras: no habia nada que avisara PROACTIVAMENTE cuando
un PPA esta por vencer (solo alertas "pull" en app/api/v1/alertas.py).
Canal de notificacion: correo (mismo patron que
_scheduled_representacion_alertas en app/main.py), no Slack."""
import datetime as dt

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.contratos import PPAContrato
from app.models.alerta import Alerta
from app.jobs import ppa_expiration_checker as job
from app.crud import crud_alertas


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


_next_id = iter(range(1, 100000))


def _ppa(db, dias_para_vencer=None, fecha_fin=None, deleted_at=None, **kw):
    kw.setdefault("id", next(_next_id))
    kw.setdefault("nombre_interno", "PPA de prueba")
    if fecha_fin is None and dias_para_vencer is not None:
        fecha_fin = dt.date.today() + dt.timedelta(days=dias_para_vencer)
    p = PPAContrato(fecha_fin=fecha_fin, deleted_at=deleted_at, **kw)
    db.add(p)
    db.flush()
    return p


@pytest.fixture(autouse=True)
def _sin_smtp(monkeypatch):
    """SMTP_HOST vacio por defecto en todos los tests -- el envio de correo
    se prueba aparte, monkeypatcheando settings.SMTP_HOST puntualmente."""
    monkeypatch.setattr(job.settings, "SMTP_HOST", "")


def test_crea_alerta_para_el_umbral_mas_ajustado_ya_cruzado(db):
    """Un PPA a 45 dias esta DENTRO de la ventana de 60 pero fuera de la de
    30 -- debe alertar con days_to_expiration=60, no 90 ni 30."""
    ppa = _ppa(db, dias_para_vencer=45)

    creadas = job.check_ppa_expirations(db)

    assert len(creadas) == 1
    alerta = db.query(Alerta).filter(Alerta.id == creadas[0]).first()
    assert alerta.ppa_id == ppa.id
    assert alerta.days_to_expiration == 60


def test_correr_el_job_dos_veces_no_duplica_la_alerta(db):
    _ppa(db, dias_para_vencer=45)

    primera = job.check_ppa_expirations(db)
    segunda = job.check_ppa_expirations(db)

    assert len(primera) == 1
    assert segunda == []
    assert db.query(Alerta).count() == 1


def test_escalada_de_ventana_crea_una_alerta_nueva_por_umbral(db):
    """El mismo contrato, corrido el job en dos momentos distintos (60 dias
    y despues 25 dias), genera DOS alertas -- una por cada ventana cruzada."""
    ppa = _ppa(db, dias_para_vencer=55)
    job.check_ppa_expirations(db)  # cruza 60

    ppa.fecha_fin = dt.date.today() + dt.timedelta(days=25)
    db.commit()
    job.check_ppa_expirations(db)  # cruza 30

    alertas = db.query(Alerta).filter(Alerta.ppa_id == ppa.id).all()
    assert sorted(a.days_to_expiration for a in alertas) == [30, 60]


def test_contrato_ya_vencido_no_alerta(db):
    _ppa(db, dias_para_vencer=-5)
    assert job.check_ppa_expirations(db) == []


def test_contrato_fuera_del_horizonte_no_alerta(db):
    _ppa(db, dias_para_vencer=120)  # mayor que el umbral mas alto (90)
    assert job.check_ppa_expirations(db) == []


def test_ppa_borrado_se_excluye(db):
    _ppa(db, dias_para_vencer=20, deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    assert job.check_ppa_expirations(db) == []


def test_sin_fecha_fin_no_alerta(db):
    _ppa(db, fecha_fin=None)
    assert job.check_ppa_expirations(db) == []


def test_pick_threshold_umbral_mas_ajustado():
    assert job._pick_threshold(45, [90, 60, 30]) == 60
    assert job._pick_threshold(75, [90, 60, 30]) == 90
    assert job._pick_threshold(30, [90, 60, 30]) == 30
    assert job._pick_threshold(0, [90, 60, 30]) == 30
    assert job._pick_threshold(-1, [90, 60, 30]) is None
    assert job._pick_threshold(120, [90, 60, 30]) is None


def test_envio_de_correo_best_effort_no_pierde_la_alerta_persistida(db, monkeypatch):
    """Si el envio de correo falla, la alerta ya persistida sigue ahi -- el
    job no debe revertir ni relanzar la excepcion."""
    monkeypatch.setattr(job.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(job.settings, "SMTP_FROM", "operaciones@unergy.io")

    def _falla(*a, **kw):
        raise RuntimeError("SMTP no disponible")
    monkeypatch.setattr(job, "_smtp_send", _falla)
    monkeypatch.setattr(job, "_log_send", lambda **kw: None)

    _ppa(db, dias_para_vencer=45)
    creadas = job.check_ppa_expirations(db)

    assert len(creadas) == 1
    assert db.query(Alerta).count() == 1


def test_envio_de_correo_exitoso_llama_a_smtp_send(db, monkeypatch):
    monkeypatch.setattr(job.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(job.settings, "SMTP_FROM", "operaciones@unergy.io")

    llamadas = []
    monkeypatch.setattr(job, "_smtp_send", lambda msg, dest: llamadas.append((msg, dest)))
    monkeypatch.setattr(job, "_log_send", lambda **kw: None)

    _ppa(db, dias_para_vencer=45)
    job.check_ppa_expirations(db)

    assert len(llamadas) == 1
    _, destinatarios = llamadas[0]
    assert destinatarios == job._ALERTA_EMAILS_PPA


def test_get_alerta_by_ppa_and_days_es_el_chequeo_de_idempotencia(db):
    ppa = _ppa(db, dias_para_vencer=45)
    assert crud_alertas.get_alerta_by_ppa_and_days(db, ppa.id, 60) is None

    job.check_ppa_expirations(db)

    encontrada = crud_alertas.get_alerta_by_ppa_and_days(db, ppa.id, 60)
    assert encontrada is not None
    assert encontrada.days_to_expiration == 60
