"""_decidir_medidor_o_historico() (clasificador_consumo.py) -- caso
'Histórico' cuando hay mediana pero NO forma horaria.

Bug real (La Catedral Consumo, MINIGRANJA SOLAR CAÑAHUATE SER AUX,
confirmado 2026-08-27): get_mediana_consumo() y get_forma_consumo() piden
requisitos distintos sobre la misma ventana de días -- la mediana solo
exige un total válido por día, la forma exige además la curva COMPLETA (sin
huecos) y con total > 0. Cuando había mediana pero la forma no se podía
construir, el código reportaba igual "caso: Histórico" con
energia_final_kwh = mediana pero curva_final en CURVA_CERO (24 ceros) --
el resumen decía un número y la tabla de corrección manual mostraba otro
completamente distinto (0), contradictorios entre sí."""
from datetime import date

import pandas as pd

import app.services.reporte_energia.clasificador_consumo as mod


def _curva_sin_dato():
    return pd.Series([None] * 24, index=mod.HORAS, dtype=float)


def test_mediana_sin_forma_no_reporta_historico_contradictorio(monkeypatch):
    monkeypatch.setattr(mod.historial, "get_mediana_consumo", lambda db, fid, fecha: (6.9, 20))
    monkeypatch.setattr(mod.historial, "get_forma_consumo", lambda db, fid, fecha: (None, 3))

    c = {"consumo_ppal": _curva_sin_dato(), "consumo_resp": _curva_sin_dato(), "recuperacion_datos": None}
    resultado = mod._decidir_medidor_o_historico(
        db=None, frontera_id=78, fecha=date(2026, 8, 26), e_cgm=0.0, estado_reporte="WARNING", c=c,
    )

    assert resultado["caso"] == "Sin dato", (
        "sin forma horaria no debe fabricar un 'Histórico' con curva y total contradictorios"
    )
    assert resultado["energia_final_kwh"] is None
    assert resultado["curva_final"].isna().all(), "'Sin dato' es CURVA_VACIA (sin dato), no una curva en cero"


def test_mediana_con_forma_si_reporta_historico_consistente(monkeypatch):
    forma = pd.Series([1 / 24] * 24, index=mod.HORAS, dtype=float)
    monkeypatch.setattr(mod.historial, "get_mediana_consumo", lambda db, fid, fecha: (6.9, 20))
    monkeypatch.setattr(mod.historial, "get_forma_consumo", lambda db, fid, fecha: (forma, 20))

    c = {"consumo_ppal": _curva_sin_dato(), "consumo_resp": _curva_sin_dato(), "recuperacion_datos": None}
    resultado = mod._decidir_medidor_o_historico(
        db=None, frontera_id=78, fecha=date(2026, 8, 26), e_cgm=0.0, estado_reporte="WARNING", c=c,
    )

    assert resultado["caso"] == "Histórico"
    assert resultado["energia_final_kwh"] == 6.9
    assert abs(float(resultado["curva_final"].sum()) - 6.9) < 0.01, (
        "la curva debe sumar lo mismo que energia_final_kwh, no quedar desincronizada"
    )
