"""Job de alertas de vencimiento de PPA + endpoint start_renewal.

Estilo del repo: sqlite en memoria con los modelos reales (ver
test_alertas_contratos_ppa). El notificador Slack se stubea para no tocar red.
"""
import asyncio
from datetime import date, timedelta

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models.base import Base
from app.models.proyectos import Proyecto
from app.models.contratos import PPAContrato, ppa_contrato_proyectos_table
from app.models.alerta import Alerta
from app.jobs import ppa_expiration_checker as checker
from app.jobs.ppa_expiration_checker import check_ppa_expirations, _parse_alert_days
from app.api.v1 import alertas as alertas_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


# En sqlite solo un INTEGER PRIMARY KEY autoincrementa (alias de rowid); BIGINT no.
# En Postgres las PK son BIGSERIAL. Mapear BigInteger→INTEGER solo para sqlite
# permite que el job inserte Alerta sin fijar el id a mano (como sí hace en prod).
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__,
            PPAContrato.__table__,
            ppa_contrato_proyectos_table,
            Alerta.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


class _FakeNotifier:
    """Notificador que registra los mensajes en vez de enviarlos."""
    def __init__(self):
        self.sent = []

    async def send_slack_notification(self, webhook_url, message):
        self.sent.append((webhook_url, message))
        return True


_ids = iter(range(1, 10_000))


def _ppa(db, fecha_fin, con_proyecto=True, **kw):
    ppa = PPAContrato(
        id=next(_ids),
        numero_codigo_contrato=kw.get("codigo", "UNERGY 001-2025"),
        nombre_interno=kw.get("nombre", "Contrato Demo"),
        comprador_nombre=kw.get("comprador", "Cliente ACME"),
        fecha_fin=fecha_fin,
        deleted_at=kw.get("deleted_at"),
    )
    db.add(ppa)
    db.flush()
    if con_proyecto:
        p = Proyecto(id=next(_ids), nombre_comercial="Planta Sol",
                     tipo_proyecto="minigranja", estado="en_operacion")
        db.add(p)
        db.flush()
        ppa.proyectos.append(p)
        db.flush()
    db.commit()
    return ppa


def _run(db, notifier, monkeypatch, dias="90,60,30", webhook="https://hooks.slack/x"):
    monkeypatch.setattr(checker.settings, "PPA_ALERT_DAYS", dias)
    monkeypatch.setattr(checker.settings, "SLACK_WEBHOOK_URL_OPERATIONS", webhook)
    return asyncio.run(check_ppa_expirations(db=db, notifier=notifier))


def test_parse_alert_days():
    assert _parse_alert_days("90,60,30") == [90, 60, 30]
    assert _parse_alert_days(" 90 , , 30 ") == [90, 30]
    assert _parse_alert_days("") == []


def test_crea_alerta_para_ppa_que_vence_en_90_dias(db, monkeypatch):
    ppa = _ppa(db, date.today() + timedelta(days=90))
    notifier = _FakeNotifier()

    created = _run(db, notifier, monkeypatch)

    assert len(created) == 1
    alerta = db.query(Alerta).one()
    assert alerta.ppa_id == ppa.id
    assert alerta.days_to_expiration == 90
    assert alerta.alert_type == "PPA_EXPIRING"
    assert alerta.project_id is not None   # tomó el proyecto vinculado
    assert alerta.status == "new"
    assert len(notifier.sent) == 1         # notificó a Slack


def test_no_alerta_si_no_coincide_ventana(db, monkeypatch):
    _ppa(db, date.today() + timedelta(days=45))  # 45 no está en 90/60/30
    notifier = _FakeNotifier()

    created = _run(db, notifier, monkeypatch)

    assert created == []
    assert db.query(Alerta).count() == 0


def test_ignora_ppa_borrado(db, monkeypatch):
    from datetime import datetime, timezone
    _ppa(db, date.today() + timedelta(days=90),
         deleted_at=datetime.now(timezone.utc))
    notifier = _FakeNotifier()

    created = _run(db, notifier, monkeypatch)

    assert created == []
    assert db.query(Alerta).count() == 0


def test_idempotente_corriendo_dos_veces(db, monkeypatch):
    _ppa(db, date.today() + timedelta(days=60))
    notifier = _FakeNotifier()

    first = _run(db, notifier, monkeypatch)
    second = _run(db, notifier, monkeypatch)

    assert len(first) == 1
    assert second == []                    # segunda corrida no crea nada
    assert db.query(Alerta).filter(Alerta.days_to_expiration == 60).count() == 1


def test_start_renewal_actualiza_estado(db, monkeypatch):
    _ppa(db, date.today() + timedelta(days=30))
    _run(db, _FakeNotifier(), monkeypatch)
    alerta = db.query(Alerta).one()
    assert alerta.status == "new"

    res = alertas_api.start_renewal(alert_id=alerta.id, db=db, _=None)

    assert res.status == "in_progress"
    db.refresh(alerta)
    assert alerta.status == "in_progress"


def test_start_renewal_404_si_no_existe(db):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        alertas_api.start_renewal(alert_id=999999, db=db, _=None)
    assert exc.value.status_code == 404
