"""estado_quoia_actual()/estado_quoia_revisar() -- estado de aprobación de
XM sobre reportes YA enviados a Quoia.

Distinto de EnviarReporteEnergiaResponse (¿el POST a Quoia salió bien?) y de
`estado_reporte` (¿el CGM automático, antes de enviar, es válido?). Quoia
pone cada envío en "En espera" y XM lo resuelve después a "Exitoso"/"Error"
-- get_border_report_status() trae ese detalle (accepted/validated/success,
xm_process_id, status) al volver a consultarlo.
"""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.api.v1 import reporte_energia as re_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Frontera.__table__, ReporteEnergiaGeneracion.__table__, ReporteEnergiaConsumo.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _sin_gaia_real(monkeypatch):
    monkeypatch.setattr(re_api, "GaiaClient", lambda: object())


FECHA = date(2026, 8, 20)


def _frontera(db, id_, codigo, tipo=TipoFronteraEnum.generacion):
    f = Frontera(id=id_, nombre_frontera=f"Test {codigo}", tipo_frontera=tipo, codigo_frontera=codigo)
    db.add(f)
    return f


def _enviado(db, id_, frontera_id, xm_exitoso=None, xm_estado=None, Modelo=ReporteEnergiaGeneracion, caso=1):
    rep = Modelo(
        id=id_, frontera_id=frontera_id, fecha=FECHA, caso=caso, medidor_usado="cgm",
        enviado_quoia_en=datetime.now(timezone.utc), enviado_quoia_ok=True,
        xm_exitoso=xm_exitoso, xm_estado=xm_estado,
    )
    db.add(rep)
    return rep


def test_no_incluye_filas_sin_enviar(db):
    _frontera(db, 1, "frt001")
    db.add(ReporteEnergiaGeneracion(id=1, frontera_id=1, fecha=FECHA, caso=1, medidor_usado="cgm"))
    db.commit()

    resp = re_api.estado_quoia_actual(fecha=FECHA, db=db, _=None)
    assert resp.total == 0


def test_get_sin_verificar_todavia_muestra_en_espera(db):
    _frontera(db, 1, "frt001")
    _enviado(db, 1, 1)
    db.commit()

    resp = re_api.estado_quoia_actual(fecha=FECHA, db=db, _=None)
    assert resp.total == 1
    assert resp.en_espera == 1
    assert resp.exitoso == 0


def test_get_ya_verificadas_se_clasifican_por_xm_exitoso_y_estado(db):
    _frontera(db, 1, "frt001")
    _frontera(db, 2, "frt002")
    _frontera(db, 3, "frt003")
    _enviado(db, 1, 1, xm_exitoso=True, xm_estado="OK")
    _enviado(db, 2, 2, xm_exitoso=True, xm_estado="WARNING")
    _enviado(db, 3, 3, xm_exitoso=False, xm_estado="ERROR2")
    db.commit()

    resp = re_api.estado_quoia_actual(fecha=FECHA, db=db, _=None)
    assert resp.exitoso == 1
    assert resp.exitoso_con_alerta == 1
    assert resp.error == 1
    assert len(resp.fallidas) == 1
    assert resp.fallidas[0].frontera_id == 3


def test_post_solo_revisa_pendientes_no_las_ya_resueltas(db, monkeypatch):
    _frontera(db, 1, "frt001")  # pendiente
    _frontera(db, 2, "frt002")  # ya resuelta
    _enviado(db, 1, 1)  # xm_exitoso None -> pendiente
    _enviado(db, 2, 2, xm_exitoso=True, xm_estado="OK")  # ya resuelta
    db.commit()

    monkeypatch.setattr(re_api, "resolver_borders",
                         lambda gaia, codes: {"frt001": {"id": 111}, "frt002": {"id": 222}})

    llamados = []

    def _fake_status(border_id, fecha_str):
        llamados.append(border_id)
        return {"xm_process_id": "abc-123", "status": "OK", "success": True}
    monkeypatch.setattr(re_api, "GaiaClient", lambda: type("G", (), {"get_border_report_status": staticmethod(_fake_status)})())

    resp = re_api.estado_quoia_revisar(fecha=FECHA, db=db, _=None)

    assert llamados == [111]  # solo la pendiente (frt001 -> border 111), no la 222 ya resuelta
    assert resp.exitoso == 2  # las dos terminan exitosas
    assert resp.en_espera == 0


def test_post_marca_en_espera_si_quoia_no_tiene_respuesta_todavia(db, monkeypatch):
    _frontera(db, 1, "frt001")
    _enviado(db, 1, 1)
    db.commit()

    monkeypatch.setattr(re_api, "resolver_borders", lambda gaia, codes: {"frt001": {"id": 111}})
    monkeypatch.setattr(re_api, "GaiaClient", lambda: type("G", (), {"get_border_report_status": staticmethod(lambda bid, f: None)})())

    resp = re_api.estado_quoia_revisar(fecha=FECHA, db=db, _=None)
    assert resp.en_espera == 1
    assert resp.exitoso == 0
