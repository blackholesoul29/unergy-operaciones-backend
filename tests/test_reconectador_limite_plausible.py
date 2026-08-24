"""get_curva_reconectador() -- descartar lecturas fisicamente imposibles.

Ver MGS 0033 Sabana de Torres 2026-08-21: el reconectador reporto
~235.000 kWh en una sola hora para una frontera de 0,99 MW de capacidad
efectiva (~237x lo fisicamente posible) -- un error de escala de unidades
del dispositivo, no generacion real. Ese valor se guardaba igual (como
fuente completa en Caso 5/7, o como referencia para el grafico), e
inflaba la escala del eje Y del chart hasta aplastar la curva real.
"""
from app.services.reporte_energia import reconectador


class _SolFalso:
    def __init__(self, puntos):
        self._puntos = puntos

    def get_relay_historical(self, *a, **kw):
        return {"results": self._puntos}


def test_descarta_solo_la_hora_implausible():
    sol = _SolFalso({
        "2026-08-20 10:00:00": {"kw": 500},      # 500 kWh en 1h -- plausible
        "2026-08-20 11:00:00": {"kw": 250000},   # 250.000 kWh en 1h -- imposible
    })
    curva = reconectador.get_curva_reconectador(sol, 123, "2026-08-20", capacidad_efectiva_mw=0.99)

    assert curva is not None
    assert curva[10] == 500
    assert curva[11] is None or curva[11] != curva[11]  # NaN -- descartada


def test_si_todas_las_horas_son_implausibles_retorna_none():
    sol = _SolFalso({
        "2026-08-20 10:00:00": {"kw": 250000},
        "2026-08-20 11:00:00": {"kw": 300000},
    })
    curva = reconectador.get_curva_reconectador(sol, 123, "2026-08-20", capacidad_efectiva_mw=0.99)

    assert curva is None


def test_sin_capacidad_efectiva_no_filtra_nada():
    """Compatibilidad hacia atras -- si no se pasa capacidad_efectiva_mw
    (ej. algun llamador que todavia no la tiene a mano), el comportamiento
    es igual que antes de este fix: no se descarta nada."""
    sol = _SolFalso({
        "2026-08-20 10:00:00": {"kw": 250000},
        "2026-08-20 11:00:00": {"kw": 300000},
    })
    curva = reconectador.get_curva_reconectador(sol, 123, "2026-08-20")

    assert curva[10] == 250000


def test_capacidad_cero_o_negativa_no_filtra():
    sol = _SolFalso({
        "2026-08-20 10:00:00": {"kw": 250000},
        "2026-08-20 11:00:00": {"kw": 300000},
    })
    curva = reconectador.get_curva_reconectador(sol, 123, "2026-08-20", capacidad_efectiva_mw=0)

    assert curva[10] == 250000


def test_lectura_dentro_del_margen_generoso_no_se_descarta():
    """El multiplicador (3x) es generoso a proposito -- un pico real de
    generacion (irradiancia alta) no debe descartarse por error."""
    sol = _SolFalso({
        "2026-08-20 10:00:00": {"kw": 2500},   # ~2,5x una capacidad de 0.99 MW
        "2026-08-20 11:00:00": {"kw": 2600},
    })
    curva = reconectador.get_curva_reconectador(sol, 123, "2026-08-20", capacidad_efectiva_mw=0.99)

    assert curva[10] == 2500
