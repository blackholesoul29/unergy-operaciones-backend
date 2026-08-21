"""reportar_manual() (POST /reporte-energia/reportar-manual)

Para fronteras que el clasificador nunca toca (proyecto en_desarrollo o sin
srv_cgm) pero que igual deben quedar reportadas con matriz de ceros ante
Quoia/ASIC (ej. GD Isabela, Los Taurus... 2026-08-21). Crea la fila del día
si no existe y la envía de inmediato, SOLO para los códigos dados -- sin
tocar ninguna otra frontera del día (a diferencia de /enviar).
"""
from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.schemas.reporte_energia import ReportarManualRequest
from app.api.v1 import reporte_energia as re_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_int(element, compiler, **kw):
    # SQLite solo autoincrementa una PK declarada como INTEGER -- BigInteger
    # compila a BIGINT, que no dispara el autoincremento (el endpoint bajo
    # prueba inserta filas sin id explícito, confiando en el auto de la BD).
    return "INTEGER"


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
    # Sin borders reales -- _enviar_a_quoia debe fallar limpio (sin border_id)
    # en vez de intentar red; eso es justo lo que queremos verificar: se
    # intenta el envío, no que se "salte" silenciosamente.
    monkeypatch.setattr(re_api, "resolver_borders", lambda gaia, codes: {})


def _frontera(db, id_, codigo, tipo):
    front = Frontera(id=id_, nombre_frontera=f"Test {codigo}", tipo_frontera=tipo, codigo_frontera=codigo)
    db.add(front)
    db.commit()
    return front


def test_crea_y_envia_fronteras_sin_fila_previa(db):
    _frontera(db, 1, "frt111", TipoFronteraEnum.generacion)
    _frontera(db, 2, "frt222", TipoFronteraEnum.consumo_auxiliar)

    body = ReportarManualRequest(frontera_codigos=["frt111", "frt222"])
    resp = re_api.reportar_manual(body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert set(resp.creadas) == {"frt111", "frt222"}
    assert resp.ya_existian == []
    assert resp.no_encontrados == []
    # Sin border_id (resolver_borders vacío) -> falla el envío, pero se intentó.
    assert resp.enviados == 0
    assert len(resp.fallidos) == 2

    from sqlalchemy import select
    fila_gen = db.execute(select(ReporteEnergiaGeneracion).where(ReporteEnergiaGeneracion.frontera_id == 1)).scalar_one()
    assert fila_gen.curva_final == [0.0] * 24
    assert fila_gen.medidor_usado == "editado_manualmente"
    assert fila_gen.caso == 6
    assert fila_gen.revisar_manualmente is False
    assert fila_gen.editado_manualmente is True

    fila_con = db.execute(select(ReporteEnergiaConsumo).where(ReporteEnergiaConsumo.frontera_id == 2)).scalar_one()
    assert fila_con.caso == "Editado manualmente"


def test_no_crea_si_ya_existia_fila(db):
    front = _frontera(db, 3, "frt333", TipoFronteraEnum.generacion)
    existente = ReporteEnergiaGeneracion(
        frontera_id=front.id, fecha=date(2026, 8, 20), caso=1, medidor_usado="cgm",
        curva_final=[10.0] * 24, energia_final_kwh=240,
    )
    db.add(existente)
    db.commit()

    body = ReportarManualRequest(frontera_codigos=["frt333"])
    resp = re_api.reportar_manual(body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert resp.creadas == []
    assert resp.ya_existian == ["frt333"]
    from sqlalchemy import select
    fila = db.execute(select(ReporteEnergiaGeneracion).where(ReporteEnergiaGeneracion.frontera_id == front.id)).scalar_one()
    assert fila.curva_final == [10.0] * 24  # no se pisó lo que ya había


def test_codigo_sin_match_se_reporta(db):
    body = ReportarManualRequest(frontera_codigos=["frt_no_existe"])
    resp = re_api.reportar_manual(body=body, fecha=date(2026, 8, 20), db=db, _=None)

    assert resp.no_encontrados == ["frt_no_existe"]
    assert resp.creadas == []
    assert resp.enviados == 0
