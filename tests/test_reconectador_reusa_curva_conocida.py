"""rellenar_horas_faltantes() -- reusa curva_reconectador_conocida en vez
de volver a consultar Solenium.

Desde que clasificar_generacion() consulta y persiste el reconectador
SIEMPRE (ver curva_reconectador_referencia), "Rellenar horas" volvía a
pedirlo igual -- llamada duplicada el mismo día. Si el llamador ya tiene
la curva a mano, se debe reusar (2026-08-21).
"""
from datetime import date

import pandas as pd
import pytest

from app.services.reporte_energia import reconectador


FECHA_STR = str(date(2026, 8, 20))


def test_reusa_curva_conocida_sin_volver_a_consultar():
    curva = pd.Series([100.0] * 24, dtype=float)
    curva[10] = None  # un hueco, dentro de HORAS_RECONECTADOR

    llamados = []

    class _SolFalso:
        def get_relay_historical(self, *a, **kw):
            llamados.append(1)
            raise AssertionError("no debía volver a consultar Solenium")

    curva_conocida = pd.Series([55.0] * 24, dtype=float)
    resultado, horas_rec, horas_sol, horas_hist, curva_ref = reconectador.rellenar_horas_faltantes(
        db=None, sv=_SolFalso(), curva=curva, id_solarview=123, fecha_str=FECHA_STR,
        curva_reconectador_conocida=curva_conocida,
    )

    assert llamados == []
    assert 10 in horas_rec
    assert resultado[10] == 55.0
    assert curva_ref is curva_conocida


def test_sin_curva_conocida_si_consulta_a_solenium():
    curva = pd.Series([100.0] * 24, dtype=float)
    curva[10] = None

    llamados = []

    class _SolFalso:
        def get_relay_historical(self, *a, **kw):
            llamados.append(1)
            return {"results": {"2026-08-20T10:00:00": {"kw": 55.0}}}

    resultado, horas_rec, horas_sol, horas_hist, curva_ref = reconectador.rellenar_horas_faltantes(
        db=None, sv=_SolFalso(), curva=curva, id_solarview=123, fecha_str=FECHA_STR,
    )

    assert llamados == [1]  # sin curva conocida, sí consulta
