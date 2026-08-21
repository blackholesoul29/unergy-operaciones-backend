"""resumen_historico() (GET /reporte-energia/resumen-historico)

Patrones a través de varios días, por frontera -- distinto de /resumen
(un solo día). Cuatro agregaciones: distribución de fuente, datos
incompletos de medidor/inversores (solo Generación), intervención manual
recurrente, y éxito/fallo de recuperación activa por medidor (parseado de
recuperacion_datos, texto libre).
"""
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException

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


def _frontera(db, id_, nombre, tipo=TipoFronteraEnum.generacion):
    f = Frontera(id=id_, nombre_frontera=nombre, tipo_frontera=tipo, codigo_frontera=f"frt{id_}")
    db.add(f)
    return f


def _gen(db, id_, frontera_id, fecha, **kw):
    rep = ReporteEnergiaGeneracion(id=id_, frontera_id=frontera_id, fecha=fecha, caso=kw.pop("caso", 1), **kw)
    db.add(rep)
    return rep


def _con(db, id_, frontera_id, fecha, **kw):
    rep = ReporteEnergiaConsumo(id=id_, frontera_id=frontera_id, fecha=fecha, caso=kw.pop("caso", "CGM"), **kw)
    db.add(rep)
    return rep


def test_hasta_antes_de_desde_da_422(db):
    with pytest.raises(HTTPException) as exc:
        re_api.resumen_historico(desde=date(2026, 8, 10), hasta=date(2026, 8, 1), db=db, _=None)
    assert exc.value.status_code == 422


def test_distribucion_de_fuente_separa_generacion_y_consumo(db):
    _frontera(db, 1, "Planta A")
    _frontera(db, 2, "Planta B Consumo", tipo=TipoFronteraEnum.consumo_auxiliar)
    _gen(db, 1, 1, date(2026, 8, 1), medidor_usado="cgm")
    _gen(db, 2, 1, date(2026, 8, 2), medidor_usado="cgm")
    _gen(db, 3, 1, date(2026, 8, 3), medidor_usado="principal")
    _con(db, 1, 2, date(2026, 8, 1), caso="CGM")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    gen_map = {i.etiqueta: i.total for i in resp.distribucion_fuente_generacion}
    assert gen_map == {"cgm": 2, "principal": 1}
    con_map = {i.etiqueta: i.total for i in resp.distribucion_fuente_consumo}
    assert con_map == {"CGM": 1}


def test_fuera_del_rango_no_cuenta(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 7, 1), medidor_usado="cgm")
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 31), db=db, _=None)
    assert resp.distribucion_fuente_generacion == []


def test_incompletos_solo_cuenta_los_false_y_da_dias_con_fila(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), medidor_principal_completo=False, medidor_respaldo_completo=True, solenium_completo=True)
    _gen(db, 2, 1, date(2026, 8, 2), medidor_principal_completo=True, medidor_respaldo_completo=False, solenium_completo=None)
    _gen(db, 3, 1, date(2026, 8, 3), medidor_principal_completo=False, medidor_respaldo_completo=False, solenium_completo=False)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    assert len(resp.incompletos) == 1
    item = resp.incompletos[0]
    assert item.frontera_id == 1
    assert item.veces_medidor_principal_incompleto == 2
    assert item.veces_medidor_respaldo_incompleto == 2
    assert item.veces_solenium_incompleto == 1
    assert item.dias_con_fila == 3


def test_intervencion_manual_combina_generacion_y_consumo(db):
    _frontera(db, 1, "Planta A")
    _frontera(db, 2, "Planta A Consumo", tipo=TipoFronteraEnum.consumo_auxiliar)
    _gen(db, 1, 1, date(2026, 8, 1), revisar_manualmente=True, editado_manualmente=False)
    _gen(db, 2, 1, date(2026, 8, 2), revisar_manualmente=True, editado_manualmente=True)
    _con(db, 1, 2, date(2026, 8, 1), revisar_manualmente=False, editado_manualmente=True)
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 2), db=db, _=None)
    por_tipo = {i.tipo: i for i in resp.intervencion_manual}
    assert por_tipo["generacion"].veces_revisar_manualmente == 2
    assert por_tipo["generacion"].veces_editado_manualmente == 1
    assert por_tipo["consumo"].veces_revisar_manualmente == 0
    assert por_tipo["consumo"].veces_editado_manualmente == 1


def test_recuperacion_activa_parsea_principal_y_respaldo_por_separado(db):
    _frontera(db, 1, "Planta A")
    _gen(db, 1, 1, date(2026, 8, 1), recuperacion_datos="principal: éxito")
    _gen(db, 2, 1, date(2026, 8, 2), recuperacion_datos="principal: falló, respaldo: éxito")
    _gen(db, 3, 1, date(2026, 8, 3), recuperacion_datos=None)  # no cuenta -- sin intento
    db.commit()

    resp = re_api.resumen_historico(desde=date(2026, 8, 1), hasta=date(2026, 8, 3), db=db, _=None)
    assert len(resp.recuperacion_activa) == 1
    item = resp.recuperacion_activa[0]
    assert item.intentos_principal == 2
    assert item.exitos_principal == 1
    assert item.intentos_respaldo == 1
    assert item.exitos_respaldo == 1
