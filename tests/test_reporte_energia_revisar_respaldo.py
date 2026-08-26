"""revisar_respaldo() (POST /reporte-energia/fronteras/{id}/revisar-respaldo)

Botón "Usar" del banner "el medidor de respaldo ya muestra un valor
distinto en Quoia" -- acción explícita y liviana (sin la interrogación
activa de hasta 90s de "Recuperar medidor", sin tocar Principal) para
adoptar ese valor cuando ya está disponible pasivamente en el banner (ver
MGS Agustín 1 2026-08-26: Principal ya correcto y automático, nunca pasa
por editar_curva(); el banner ya mostraba el respaldo nuevo, pero no
había ninguna acción liviana para adoptarlo).
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
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.api.v1 import reporte_energia as re_api
from app.services.reporte_energia import curvas


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
    monkeypatch.setattr(curvas, "construir_mapa_medidor_nodo", lambda gaia: {})


def test_respaldo_dentro_de_tolerancia_se_adopta(db, monkeypatch):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    principal = [100.0] * 24
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=2, medidor_usado="principal",
        curva_final=principal, curva_medidor_principal=principal, curva_medidor_respaldo=[999.0] * 24,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    respaldo_vivo = [100.0] * 23 + [101.0]
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    detalle = re_api.revisar_respaldo(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == respaldo_vivo
    assert detalle.respaldo_reportado_origen == "medidor"


def test_respaldo_fuera_de_tolerancia_no_se_adopta(db, monkeypatch):
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.generacion, codigo_frontera="frt001")
    db.add(front)
    principal = [100.0] * 24
    viejo_respaldo = [999.0] * 24
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso=2, medidor_usado="principal",
        curva_final=principal, curva_medidor_principal=principal, curva_medidor_respaldo=viejo_respaldo,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    respaldo_vivo = [50.0] * 24
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    detalle = re_api.revisar_respaldo(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_medidor_respaldo == viejo_respaldo
    assert detalle.respaldo_reportado_origen == "estimado"


def test_no_toca_curva_final_ni_medidor_usado(db, monkeypatch):
    """Acción liviana -- no reclasifica ni edita Principal, solo el
    snapshot de respaldo (si pasa)."""
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
    respaldo_vivo = [100.0] * 23 + [101.0]
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)))

    detalle = re_api.revisar_respaldo(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    assert detalle.curva_final == principal
    assert detalle.medidor_usado == "principal"
    assert detalle.editado_manualmente is False


def test_consumo_dentro_de_tolerancia_se_adopta(db, monkeypatch):
    """Extendido a Consumo 2026-08-26 -- mismo criterio que Generación,
    pero usa 'iae' en vez de 'eae' y no aplica el filtro de plausibilidad
    (Consumo no tiene capacidad efectiva definida)."""
    front = Frontera(id=1, nombre_frontera="Test", tipo_frontera=TipoFronteraEnum.consumo_auxiliar, codigo_frontera="frt001")
    db.add(front)
    principal = [10.0] * 24
    rep = ReporteEnergiaConsumo(
        id=1, frontera_id=1, fecha=date(2026, 8, 20), caso="Medidor", medidor_usado="principal",
        curva_final=principal, curva_medidor_principal=principal, curva_medidor_respaldo=[999.0] * 24,
    )
    db.add(rep)
    db.commit()

    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 111, "backup_meter": 222}})
    respaldo_vivo = [10.0] * 23 + [11.0]
    var_usada = []
    def _curva_en_vivo(gaia, mapa_nodo, main_id, backup_id, fecha_str, frt_code, var_name, capacidad_efectiva_mw=None):
        var_usada.append(var_name)
        return pd.Series(principal, dtype=float), pd.Series(respaldo_vivo, dtype=float)
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", _curva_en_vivo)

    detalle = re_api.revisar_respaldo(frontera_id=1, fecha=date(2026, 8, 20), db=db, _=None)

    # _construir_detalle() al final del endpoint hace su propia consulta en
    # vivo (para el banner "el medidor cambió", sin relación con
    # _revisar_respaldo_en_vivo) -- puede sumar una llamada más, siempre
    # con "iae" (nunca "eae", que sería el error real a detectar acá).
    assert var_usada and all(v == "iae" for v in var_usada)
    assert detalle.curva_medidor_respaldo == respaldo_vivo
    assert detalle.respaldo_reportado_origen == "medidor"
