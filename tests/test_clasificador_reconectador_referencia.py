"""clasificar_generacion() -- curva_reconectador_referencia se consulta y
persiste SIEMPRE durante la clasificación diaria, igual que medidor/
Solenium -- no depende de que la curva final tenga huecos ni de que
alguien haga clic en "Rellenar horas" (pedido 2026-08-21: "Detalle de las
fuentes" debe mostrar el reconectador como una fuente más, sin ese
criterio)."""
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


FECHA = date(2026, 8, 20)
CURVA_10 = pd.Series([10.0] * 24, dtype=float)


class _GaiaStub:
    def get_border_report_status(self, border_id, fecha_str):
        return {"status": "OK", "reported_data_main": [10.0] * 24}


def _preparar_caso1(monkeypatch):
    """Fuerza Caso 1 (CGM válido == inversores, en rango) -- el camino más
    corto en _decidir_caso, así no hace falta mockear medidor/histórico
    también."""
    monkeypatch.setattr(clasificador.solenium_svc, "curva_generacion", lambda *a, **kw: (CURVA_10.copy(), True))
    monkeypatch.setattr(
        clasificador.curvas, "curvas_de_frontera",
        lambda *a, **kw: {
            "node_ppal": None, "node_resp": None,
            "curva_ppal": pd.Series([None] * 24, dtype=float), "curva_resp": pd.Series([None] * 24, dtype=float),
            "ppal_completo": False, "resp_completo": False,
            "consumo_ppal": None, "consumo_resp": None,
            "consumo_ppal_completo": False, "consumo_resp_completo": False,
            "recuperacion_datos": None,
        },
    )


def test_reconectador_se_consulta_y_persiste_con_curva_final_completa(db, monkeypatch):
    """Caso 1 -- CGM ya válido, curva_final SIN huecos. Antes esto era
    justo el caso donde el reconectador nunca se consultaba (no hacía
    falta "Rellenar horas"); ahora debe consultarse igual."""
    _preparar_caso1(monkeypatch)
    llamados = []

    def _fake_reconectador(sol, id_solenium, fecha_str):
        llamados.append((id_solenium, fecha_str))
        return pd.Series([5.0] * 24, dtype=float)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", _fake_reconectador)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub(), sol=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solenium=123, mapa_medidor_nodo={}, fecha=FECHA,
    )

    assert llamados == [(123, str(FECHA))]
    assert resultado["curva_reconectador_referencia"] == [5.0] * 24
    assert resultado["caso"] == 1  # confirma que sí se tomó el camino corto esperado


def test_sin_project_id_solenium_no_consulta_reconectador(db, monkeypatch):
    _preparar_caso1(monkeypatch)
    llamados = []
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", lambda *a, **kw: llamados.append(1))

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub(), sol=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solenium=None, mapa_medidor_nodo={}, fecha=FECHA,
    )

    assert llamados == []
    assert resultado["curva_reconectador_referencia"] is None


def test_reconectador_sin_dato_deja_referencia_en_none(db, monkeypatch):
    _preparar_caso1(monkeypatch)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", lambda *a, **kw: None)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStub(), sol=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solenium=123, mapa_medidor_nodo={}, fecha=FECHA,
    )

    assert resultado["curva_reconectador_referencia"] is None


class _GaiaStubInvalido:
    def get_border_report_status(self, border_id, fecha_str):
        return {"status": "ERROR", "reported_data_main": None}


def test_caso7_reusa_la_misma_curva_sin_consultar_dos_veces(db, monkeypatch):
    """Cuando el reconectador es la fuente COMPLETA del día (Caso 7 --
    sin CGM, sin medidor, sin inversores), clasificar_generacion() no debe
    volver a consultarlo al final: ya se consultó dentro de _decidir_caso
    y ese mismo resultado debe reusarse. Antes se consultaba una SEGUNDA
    vez, con riesgo de devolver algo distinto y contradecir "Fuente usada"
    (ver MGS 0033 Sabana de Torres 2026-08-18/21: "Fuente usada:
    Reconectador" pero "Detalle de las fuentes" mostraba "Sin dato")."""
    monkeypatch.setattr(clasificador.solenium_svc, "curva_generacion", lambda *a, **kw: (pd.Series([None] * 24, dtype=float), False))
    monkeypatch.setattr(
        clasificador.curvas, "curvas_de_frontera",
        lambda *a, **kw: {
            "node_ppal": None, "node_resp": None,
            "curva_ppal": pd.Series([None] * 24, dtype=float), "curva_resp": pd.Series([None] * 24, dtype=float),
            "ppal_completo": False, "resp_completo": False,
            "consumo_ppal": None, "consumo_resp": None,
            "consumo_ppal_completo": False, "consumo_resp_completo": False,
            "recuperacion_datos": None,
        },
    )
    llamados = []

    def _fake_reconectador(sol, id_solenium, fecha_str):
        llamados.append((id_solenium, fecha_str))
        return pd.Series([20.0] * 24, dtype=float)
    monkeypatch.setattr(clasificador.reconectador, "get_curva_reconectador", _fake_reconectador)

    resultado = clasificador.clasificar_generacion(
        db, _GaiaStubInvalido(), sol=object(), frontera_id=1, frt_code="frt001",
        border_meta={"border_id": 1, "main_meter": None, "backup_meter": None},
        project_id_solenium=123, mapa_medidor_nodo={}, fecha=FECHA,
    )

    assert resultado["caso"] == 7
    assert resultado["medidor_usado"] == "reconectador"
    assert len(llamados) == 1  # una sola consulta, no dos
    assert resultado["curva_reconectador_referencia"] == [20.0] * 24
    assert resultado["curva_reconectador_referencia"] == resultado["curva_final"].tolist()
