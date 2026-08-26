"""verificar_drift_medidores() (drift_medidores.py)

Corre encadenado justo después de clasificar (ver _scheduled_reporte_energia
en main.py): vuelve a consultar Quoia en vivo para cada fila SIN
revisar_manualmente y, si el medidor ya cambió desde que se clasificó (ver
MGS 0032 El Paso Norte 2026-08-05), marca revisar_manualmente=True -- para
que aparezca en la lista "Revisión de hoy" sin que alguien tenga que abrir
esa frontera puntual (pedido de Sara 2026-08-26).
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
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.services.reporte_energia import curvas, drift_medidores


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Frontera.__table__, Proyecto.__table__, ReporteEnergiaGeneracion.__table__, ReporteEnergiaConsumo.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _sin_gaia_real(monkeypatch):
    monkeypatch.setattr(drift_medidores, "GaiaClient", lambda: object())
    monkeypatch.setattr(curvas, "construir_mapa_medidor_nodo", lambda gaia: {})


def _frontera(db, id_=1, codigo="frt001", tipo=TipoFronteraEnum.generacion, proyecto_id=None):
    front = Frontera(
        id=id_, nombre_frontera="Test", tipo_frontera=tipo, codigo_frontera=codigo, proyecto_id=proyecto_id,
    )
    db.add(front)
    return front


def _curva_serie(valores):
    return pd.Series({h: valores[h] for h in range(24)}, dtype=float)


def test_medidor_sin_cambio_no_marca(db, monkeypatch):
    _frontera(db)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (_curva_serie([100.0] * 24), _curva_serie([100.0] * 24)))

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert resultado == {"generacion": 0, "consumo": 0}
    assert rep.revisar_manualmente is False


def test_medidor_principal_cambio_marca_revisar(db, monkeypatch):
    _frontera(db)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})
    # Principal ahora reporta el doble (mismo glitch de MGS 0032) -- >1% de diferencia.
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (_curva_serie([200.0] * 24), _curva_serie([100.0] * 24)))

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert resultado == {"generacion": 1, "consumo": 0}
    assert rep.revisar_manualmente is True


def test_medidor_respaldo_cambio_tambien_marca_aunque_no_se_haya_usado(db, monkeypatch):
    """Escopado a ambos medidores, no solo medidor_usado -- mismo criterio
    que ya usa _construir_detalle() (2026-08-20): un medidor que se
    recupera aunque no haya ganado como fuente igual debe avisar."""
    _frontera(db)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=5, medidor_usado="historico",
        curva_medidor_principal=[0.0] * 24, curva_medidor_respaldo=[50.0] * 24,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo",
                         lambda *a, **kw: (_curva_serie([0.0] * 24), _curva_serie([120.0] * 24)))

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert resultado == {"generacion": 1, "consumo": 0}
    assert rep.revisar_manualmente is True


def test_fila_ya_marcada_revisar_no_se_vuelve_a_consultar(db, monkeypatch):
    _frontera(db)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=3, medidor_usado="revisar",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=None,
        revisar_manualmente=True,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})

    llamado = []
    def _falla_si_se_llama(*a, **kw):
        llamado.append(True)
        raise AssertionError("no debería consultar una fila ya marcada revisar_manualmente")
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", _falla_si_se_llama)

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert not llamado
    assert resultado == {"generacion": 0, "consumo": 0}


def test_sin_curva_medidor_persistida_no_se_consulta(db, monkeypatch):
    """Caso CGM u otra fila sin curva de medidor persistida -- nada con qué
    comparar, no tiene sentido pagar la consulta a Quoia."""
    _frontera(db)
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=1, medidor_usado="cgm",
        curva_medidor_principal=None, curva_medidor_respaldo=None,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})

    llamado = []
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", lambda *a, **kw: llamado.append(True))

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert not llamado
    assert resultado == {"generacion": 0, "consumo": 0}


def test_sin_match_en_borders_no_se_consulta(db, monkeypatch):
    _frontera(db, codigo="sin_match")
    rep = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders", lambda gaia: {})

    llamado = []
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", lambda *a, **kw: llamado.append(True))

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert not llamado
    assert resultado == {"generacion": 0, "consumo": 0}


def test_error_de_quoia_en_una_frontera_no_tumba_las_demas(db, monkeypatch):
    _frontera(db, id_=1, codigo="frt001")
    _frontera(db, id_=2, codigo="frt002")
    rep1 = ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24,
        revisar_manualmente=False,
    )
    rep2 = ReporteEnergiaGeneracion(
        id=2, frontera_id=2, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[50.0] * 24, curva_medidor_respaldo=[50.0] * 24,
        revisar_manualmente=False,
    )
    db.add_all([rep1, rep2])
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders", lambda gaia: {
        "frt001": {"main_meter": 1, "backup_meter": 2},
        "frt002": {"main_meter": 3, "backup_meter": 4},
    })

    def _curva_en_vivo(gaia, mapa_nodo, main_id, backup_id, fecha_str, frt_code, var_name, capacidad_efectiva_mw=None):
        if main_id == 1:
            raise RuntimeError("Quoia caído para frt001")
        return _curva_serie([200.0] * 24), _curva_serie([50.0] * 24)
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", _curva_en_vivo)

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert resultado == {"generacion": 1, "consumo": 0}
    assert rep1.revisar_manualmente is False  # falló la consulta -- no se pudo evaluar
    assert rep2.revisar_manualmente is True   # frt002 sí se evaluó y cambió


def test_consumo_usa_iae_y_es_independiente_de_generacion(db, monkeypatch):
    _frontera(db, id_=1, codigo="frt001", tipo=TipoFronteraEnum.consumo_auxiliar)
    rep = ReporteEnergiaConsumo(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso="Histórico", medidor_usado="principal",
        curva_medidor_principal=[80.0] * 24, curva_medidor_respaldo=None,
        revisar_manualmente=False,
    )
    db.add(rep)
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders",
                         lambda gaia: {"frt001": {"main_meter": 1, "backup_meter": 2}})

    vars_usadas = []
    def _curva_en_vivo(gaia, mapa_nodo, main_id, backup_id, fecha_str, frt_code, var_name, capacidad_efectiva_mw=None):
        vars_usadas.append(var_name)
        return _curva_serie([160.0] * 24), _curva_serie([0.0] * 24)
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", _curva_en_vivo)

    resultado = drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    assert vars_usadas == ["iae"]
    assert resultado == {"generacion": 0, "consumo": 1}
    assert rep.revisar_manualmente is True


def test_capacidad_efectiva_se_propaga_solo_para_generacion(db, monkeypatch):
    """Villanueva 2026-08-26: el mismo criterio de plausibilidad de la
    clasificación debe aplicarse a esta consulta en vivo -- pero solo para
    Generación (Consumo no tiene capacidad efectiva definida, decidido con
    Sara 2026-08-26)."""
    db.add(Proyecto(id=1, nombre_comercial="Planta Test", potencia_instalada_kwp=990))
    _frontera(db, id_=1, codigo="frt001", tipo=TipoFronteraEnum.generacion, proyecto_id=1)
    _frontera(db, id_=2, codigo="frt002", tipo=TipoFronteraEnum.consumo_auxiliar, proyecto_id=1)
    db.add(ReporteEnergiaGeneracion(
        id=1, frontera_id=1, fecha=date(2026, 8, 25), caso=2, medidor_usado="principal",
        curva_medidor_principal=[100.0] * 24, curva_medidor_respaldo=None, revisar_manualmente=False,
    ))
    db.add(ReporteEnergiaConsumo(
        id=1, frontera_id=2, fecha=date(2026, 8, 25), caso="Histórico", medidor_usado="principal",
        curva_medidor_principal=[80.0] * 24, curva_medidor_respaldo=None, revisar_manualmente=False,
    ))
    db.commit()
    monkeypatch.setattr(curvas, "construir_mapa_borders", lambda gaia: {
        "frt001": {"main_meter": 1, "backup_meter": 2},
        "frt002": {"main_meter": 3, "backup_meter": 4},
    })

    capacidades = []
    def _curva_en_vivo(gaia, mapa_nodo, main_id, backup_id, fecha_str, frt_code, var_name, capacidad_efectiva_mw=None):
        capacidades.append((frt_code, capacidad_efectiva_mw))
        return _curva_serie([100.0] * 24), _curva_serie([0.0] * 24)
    monkeypatch.setattr(curvas, "curva_medidor_en_vivo", _curva_en_vivo)

    drift_medidores.verificar_drift_medidores(db, date(2026, 8, 25))

    capacidades_por_frt = dict(capacidades)
    assert capacidades_por_frt["frt001"] == 0.99  # 990 kWp / 1000
    assert capacidades_por_frt["frt002"] is None
