"""recuperar_medidor() (POST /reporte-energia/fronteras/{id}/recuperar-medidor)

Botón "Recuperar medidor" -- dispara a demanda la misma recuperación
activa que la corrida diaria dispara sola bajo ciertas condiciones, pero
para AMBOS medidores y sin ese filtro. Alternativa más chica a
"reclasificar la frontera completa" (descartada 2026-08-20 por el riesgo
de pisar ediciones/validaciones manuales): esto solo registra el
resultado en `recuperacion_datos`, sin tocar curva_final/medidor_usado/
caso/editado_manualmente.
"""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.api.v1 import reporte_energia as re_api
from app.services.reporte_energia import curvas, recuperacion


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Frontera.__table__, ReporteEnergiaGeneracion.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _sin_gaia_real(monkeypatch):
    monkeypatch.setattr(re_api, "GaiaClient", lambda: object())


def _frontera_y_reporte(db, codigo_frontera="frt001"):
    front = Frontera(
        id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion,
        codigo_frontera=codigo_frontera,
    )
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=5,
        medidor_usado="historico", curva_final=[1.0] * 24,
        editado_manualmente=False,
    )
    db.add(rep)
    db.commit()
    return front, rep


def test_recupera_ambos_medidores_y_registra_el_resultado(db, monkeypatch):
    _frontera_y_reporte(db)
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})

    def _fake_recuperar(meter_id, init_date, end_date):
        return {"status": "success"} if meter_id == 111 else {"status": "failed"}
    monkeypatch.setattr(recuperacion, "recuperar_datos_medidor", _fake_recuperar)

    detalle = re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.recuperacion_datos in (
        "principal: éxito, respaldo: falló", "respaldo: falló, principal: éxito",
    )
    # No toca nada de la clasificación/curva ya guardada.
    assert detalle.curva_final == [1.0] * 24
    assert detalle.medidor_usado == "historico"
    assert detalle.caso == "5"
    assert detalle.editado_manualmente is False


def test_sin_medidores_configurados_da_400(db, monkeypatch):
    _frontera_y_reporte(db, codigo_frontera="sin_match")
    monkeypatch.setattr(curvas, "construir_mapa_borders", lambda gaia: {})

    with pytest.raises(Exception) as exc:
        re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)
    assert "400" in str(exc.value) or getattr(exc.value, "status_code", None) == 400


def test_solo_respaldo_configurado_no_pide_principal(db, monkeypatch):
    _frontera_y_reporte(db, codigo_frontera="frt002")
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt002": {"main_meter": None, "backup_meter": 333}})

    llamados = []

    def _fake_recuperar(meter_id, init_date, end_date):
        llamados.append(meter_id)
        return {"status": "success"}
    monkeypatch.setattr(recuperacion, "recuperar_datos_medidor", _fake_recuperar)

    detalle = re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert llamados == [333]
    assert detalle.recuperacion_datos == "respaldo: éxito"


def test_principal_ya_automatico_revisa_respaldo_en_vivo_y_lo_adopta_si_pasa(db, monkeypatch):
    """MGS Agustín 1 2026-08-26: Principal ya correcto y automático (nunca
    pasa por editar_curva()), pero el respaldo cambió en Quoia -- 'Recuperar
    medidor' debe re-evaluarlo y adoptarlo si pasa la tolerancia."""
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    principal = [100.0] * 24
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=2, medidor_usado="principal",
        curva_final=principal, curva_medidor_principal=principal, curva_medidor_respaldo=[999.0] * 24,
        editado_manualmente=False,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    monkeypatch.setattr(curvas, "construir_mapa_medidor_nodo", lambda gaia: {})
    monkeypatch.setattr(recuperacion, "recuperar_datos_medidor", lambda *a, **kw: {"status": "success"})
    respaldo_vivo = [100.0] * 23 + [101.0]  # +1 kWh -- dentro de tolerancia
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    detalle = re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == respaldo_vivo
    assert detalle.respaldo_reportado_origen == "medidor"


def test_principal_ya_automatico_respaldo_fuera_de_tolerancia_no_lo_adopta(db, monkeypatch):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    principal = [100.0] * 24
    viejo_respaldo = [999.0] * 24
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=2, medidor_usado="principal",
        curva_final=principal, curva_medidor_principal=principal, curva_medidor_respaldo=viejo_respaldo,
        editado_manualmente=False,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    monkeypatch.setattr(curvas, "construir_mapa_medidor_nodo", lambda gaia: {})
    monkeypatch.setattr(recuperacion, "recuperar_datos_medidor", lambda *a, **kw: {"status": "success"})
    respaldo_vivo = [75.93] * 24  # bien lejos de tolerancia (caso real Agustín 1)
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    detalle = re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == viejo_respaldo
    assert detalle.respaldo_reportado_origen == "estimado"


def test_medidor_usado_no_principal_no_revisa_respaldo(db, monkeypatch):
    """Si curva_final no vino del medidor principal, no tiene sentido
    revisar el respaldo -- no debe consultarse Quoia para eso."""
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=5, medidor_usado="historico",
        curva_final=[1.0] * 24, curva_medidor_principal=None, curva_medidor_respaldo=None,
        editado_manualmente=False,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    monkeypatch.setattr(recuperacion, "recuperar_datos_medidor", lambda *a, **kw: {"status": "success"})

    detalle = re_api.recuperar_medidor(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    # El guard de _revisar_respaldo_en_vivo() debe cortar ANTES de tocar
    # nada -- curva_medidor_respaldo se queda exactamente como estaba.
    assert detalle.curva_medidor_respaldo is None
