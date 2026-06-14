"""Tests de notificaciones de alertas (contratos PPA).

Usan SQLite en memoria con los modelos reales y llaman a las funciones de
servicio/endpoint directamente (sin pasar por la capa de auth de FastAPI, que
requiere bcrypt y no está disponible en este entorno de tests).
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models  # registra todos los modelos en Base.metadata
from app.models import Base
from app.models.notificaciones import NotificacionAlerta
from app.models.usuarios import Usuario


# En producción los PK son BIGSERIAL (Postgres); SQLite no autoincrementa un
# BIGINT PK, así que para los tests lo compilamos como INTEGER.
@compiles(BigInteger, "sqlite")
def _compile_biginteger_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    # Solo las tablas relevantes: el resto del modelo usa tipos PG (JSONB) que
    # SQLite no compila.
    Base.metadata.create_all(
        bind=engine, tables=[Usuario.__table__, NotificacionAlerta.__table__],
    )
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


_next_id = [0]


def _usuario(db, rol="admin", email="u@unergy.io"):
    _next_id[0] += 1
    u = Usuario(id=_next_id[0], email=email, nombre="User", rol=rol, activo=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ── create_notificacion_alerta: despacho de email ────────────────────────────

def test_email_enviado_cuando_canal_ambos(db, monkeypatch):
    import app.api.v1.notificaciones as n
    llamadas = []
    monkeypatch.setattr(
        n, "send_alerta_email",
        lambda **kw: llamadas.append(kw) or True,
    )
    u = _usuario(db)

    row = n.create_notificacion_alerta(
        db, usuario_id=u.id, titulo="T", mensaje="M",
        severidad="critica", canal="ambos", email_to=u.email,
    )

    assert row.id is not None
    assert row.email_enviado is True
    assert len(llamadas) == 1 and llamadas[0]["to_email"] == u.email


def test_email_no_se_envia_en_canal_in_app(db, monkeypatch):
    import app.api.v1.notificaciones as n
    llamadas = []
    monkeypatch.setattr(n, "send_alerta_email", lambda **kw: llamadas.append(kw) or True)
    u = _usuario(db)

    row = n.create_notificacion_alerta(
        db, usuario_id=u.id, titulo="T", mensaje="M", canal="in_app", email_to=u.email,
    )

    assert row.email_enviado is False
    assert llamadas == []


def test_fallo_email_no_impide_persistencia(db, monkeypatch):
    import app.api.v1.notificaciones as n
    monkeypatch.setattr(n, "send_alerta_email", lambda **kw: False)  # transporte falla
    u = _usuario(db)

    row = n.create_notificacion_alerta(
        db, usuario_id=u.id, titulo="T", mensaje="M", canal="email", email_to=u.email,
    )

    assert row.id is not None          # la fila se guardó
    assert row.email_enviado is False  # pero el email no salió
    assert db.query(NotificacionAlerta).count() == 1


def test_excepcion_en_email_no_impide_persistencia(db, monkeypatch):
    import app.api.v1.notificaciones as n

    def _boom(**kw):
        raise RuntimeError("smtp caído")

    monkeypatch.setattr(n, "send_alerta_email", _boom)
    u = _usuario(db)

    row = n.create_notificacion_alerta(
        db, usuario_id=u.id, titulo="T", mensaje="M", canal="ambos", email_to=u.email,
    )

    assert row.id is not None
    assert row.email_enviado is False


# ── Endpoints: listado, conteo y mark-read (scoping) ──────────────────────────

def test_list_y_count_solo_no_leidas(db, monkeypatch):
    import app.api.v1.notificaciones as n
    monkeypatch.setattr(n, "send_alerta_email", lambda **kw: True)
    u = _usuario(db)
    n.create_notificacion_alerta(db, usuario_id=u.id, titulo="A", mensaje="m")
    n.create_notificacion_alerta(db, usuario_id=u.id, titulo="B", mensaje="m")

    items = n.list_alertas_me(solo_no_leidas=True, limit=50, db=db, current=u)
    assert len(items) == 2
    assert n.count_alertas_me(db=db, current=u) == {"no_leidas": 2}


def test_mark_read_actualiza_y_baja_el_conteo(db, monkeypatch):
    import app.api.v1.notificaciones as n
    from app.schemas.notificaciones import NotificacionAlertaMarkRead
    monkeypatch.setattr(n, "send_alerta_email", lambda **kw: True)
    u = _usuario(db)
    r1 = n.create_notificacion_alerta(db, usuario_id=u.id, titulo="A", mensaje="m")

    res = n.mark_alertas_read(NotificacionAlertaMarkRead(ids=[r1.id]), db=db, current=u)
    assert res == {"actualizadas": 1}

    db.refresh(r1)
    assert r1.leida is True
    assert r1.leida_at is not None
    assert n.count_alertas_me(db=db, current=u) == {"no_leidas": 0}


def test_usuario_no_puede_marcar_notificaciones_de_otro(db, monkeypatch):
    import app.api.v1.notificaciones as n
    from app.schemas.notificaciones import NotificacionAlertaMarkRead
    monkeypatch.setattr(n, "send_alerta_email", lambda **kw: True)
    a = _usuario(db, email="a@unergy.io")
    b = _usuario(db, email="b@unergy.io")
    rb = n.create_notificacion_alerta(db, usuario_id=b.id, titulo="de B", mensaje="m")

    # A intenta marcar la notificación de B
    res = n.mark_alertas_read(NotificacionAlertaMarkRead(ids=[rb.id]), db=db, current=a)
    assert res == {"actualizadas": 0}

    db.refresh(rb)
    assert rb.leida is False  # sigue sin leer


# ── Hook de alertas: creación y anti-duplicado ───────────────────────────────

def test_hook_crea_notificaciones_para_usuarios_elegibles(db, monkeypatch):
    import app.api.v1.alertas as al
    monkeypatch.setattr(
        "app.api.v1.notificaciones.send_alerta_email", lambda **kw: True
    )
    admin = _usuario(db, rol="admin", email="admin@unergy.io")
    ops = _usuario(db, rol="operaciones", email="ops@unergy.io")
    lectura = _usuario(db, rol="solo_lectura", email="ro@unergy.io")  # no elegible

    al._emitir_notificaciones_alerta(
        db, alerta_ref="cumplimiento_ppa:7:2026-06", titulo="Déficit", mensaje="m",
    )

    notifs = db.query(NotificacionAlerta).all()
    destinatarios = {x.usuario_id for x in notifs}
    assert admin.id in destinatarios and ops.id in destinatarios
    assert lectura.id not in destinatarios
    assert len(notifs) == 2


def test_hook_no_duplica_misma_alerta_ref(db, monkeypatch):
    import app.api.v1.alertas as al
    monkeypatch.setattr(
        "app.api.v1.notificaciones.send_alerta_email", lambda **kw: True
    )
    _usuario(db, rol="admin", email="admin@unergy.io")

    ref = "cumplimiento_ppa:7:2026-06"
    al._emitir_notificaciones_alerta(db, alerta_ref=ref, titulo="Déficit", mensaje="m")
    al._emitir_notificaciones_alerta(db, alerta_ref=ref, titulo="Déficit", mensaje="m")

    assert db.query(NotificacionAlerta).filter_by(alerta_ref=ref).count() == 1
