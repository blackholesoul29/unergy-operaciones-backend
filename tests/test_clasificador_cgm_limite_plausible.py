"""clasificar_generacion() -- descartar un CGM (reported_data_main)
fisicamente implausible.

Mismo criterio ya aplicado a medidor/SolarView/reconectador/datos crudos
(ver limite_plausible_kwh() en utils.py). Ver MGS 0010 Villanueva
2026-08-26: el glitch original se encontro en SolarView, pero el reporte
oficial de Quoia al ASIC tampoco es inmune a un error de telemetria del
lado del medidor que lo alimenta. A diferencia de las otras fuentes, acá
no se enmascara solo la hora implausible -- se descarta CGM entero para
la fila (reporte_valido=False), porque Caso 1 usa curva_cgm DIRECTO como
curva_final y no tiene relleno horario automático (CASOS_CON_RELLENO_HORARIO
no incluye el 1)."""
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.reporte_energia import clasificador


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


FECHA = date(2026, 8, 26)

_SIN_MEDIDOR = {
    "node_ppal": None, "node_resp": None,
    "curva_ppal": pd.Series([None] * 24, dtype=float), "curva_resp": pd.Series([None] * 24, dtype=float),
    "ppal_completo": False, "resp_completo": False,
    "consumo_ppal": None, "consumo_resp": None,
    "consumo_ppal_completo": False, "consumo_resp_completo": False,
    "recuperacion_datos": None,
}


class _GaiaStub:
    def __init__(self, reported_data_main):
        self._curva = reported_data_main

    def get_border_report_status(self, border_id, fecha_str):
        return {"status": "OK", "reported_data_main": self._curva}


def test_cgm_implausible_no_activa_caso1(db, monkeypatch):
    curva_inv = pd.Series([4000.0] + [0.0] * 23, dtype=float)  # mismo total que el CGM implausible
    monkeypatch.setattr(clasificador.solarview_svc, "curva_generacion", lambda *a, **kw: (curva_inv.copy(), True))
    monkeypatch.setattr(clasificador.curvas, "curvas_de_frontera", lambda *a, **kw: _SIN_MEDIDOR)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", lambda *a, **kw: None)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub([4000.0] + [0.0] * 23), sv=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solarview=123, mapa_medidor_nodo={}, fecha=FECHA,
        capacidad_efectiva_mw=0.1,  # limite = 300 kWh -- 4000 kWh es implausible
    )

    assert resultado["caso"] != 1
    assert resultado["medidor_usado"] != "cgm"


def test_cgm_dentro_del_margen_si_activa_caso1(db, monkeypatch):
    """Control: sin el glitch, el mismo escenario SÍ dispara Caso 1 --
    confirma que el test anterior se descarta por el filtro, no por otra
    razón del árbol de decisión."""
    curva_inv = pd.Series([100.0] * 24, dtype=float)  # 2.400 kWh total
    monkeypatch.setattr(clasificador.solarview_svc, "curva_generacion", lambda *a, **kw: (curva_inv.copy(), True))
    monkeypatch.setattr(clasificador.curvas, "curvas_de_frontera", lambda *a, **kw: _SIN_MEDIDOR)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", lambda *a, **kw: None)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub([100.0] * 24), sv=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solarview=123, mapa_medidor_nodo={}, fecha=FECHA,
        capacidad_efectiva_mw=0.99,  # limite ~2.970 kWh -- 100/h está dentro de rango
    )

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"


def test_sin_capacidad_efectiva_no_filtra_cgm(db, monkeypatch):
    """Compatibilidad hacia atrás -- sin capacidad_efectiva_mw, el
    comportamiento es igual que antes de este fix."""
    curva_inv = pd.Series([4000.0] + [0.0] * 23, dtype=float)
    monkeypatch.setattr(clasificador.solarview_svc, "curva_generacion", lambda *a, **kw: (curva_inv.copy(), True))
    monkeypatch.setattr(clasificador.curvas, "curvas_de_frontera", lambda *a, **kw: _SIN_MEDIDOR)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", lambda *a, **kw: None)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub([4000.0] + [0.0] * 23), sv=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solarview=123, mapa_medidor_nodo={}, fecha=FECHA,
    )

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"
