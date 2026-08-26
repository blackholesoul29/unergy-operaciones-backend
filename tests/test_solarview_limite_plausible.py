"""curva_generacion() -- descartar lecturas fisicamente imposibles de SolarView.

Mismo criterio que ya existia para el reconectador (ver
test_reconectador_limite_plausible.py, MGS 0033 Sabana de Torres): un panel
solar puede superar brevemente su capacidad nominal, pero no por un margen
enorme. Ver MGS 0010 Villanueva 2026-08-26: SolarView /generation/ reporto
~48.090 kWh en una sola hora para una frontera de 0,99 MW de capacidad
efectiva (~48x lo fisicamente posible) -- un glitch de telemetria, no
generacion real. Ese valor se colaba en e_inv/curva_solenium_referencia,
contaminando la comparacion medidor-vs-inversores de Caso 3 y aplastando
la escala del eje Y del grafico.
"""
from app.services.reporte_energia import solarview


class _SolFalso:
    def __init__(self, gen_kwh):
        self._gen_kwh = gen_kwh

    def get_generation(self, *a, **kw):
        return {"generation_kwh": self._gen_kwh}


def test_descarta_solo_la_hora_implausible():
    sol = _SolFalso({
        "2026-08-25 10:00": 500,      # 500 kWh en 1h -- plausible
        "2026-08-25 18:00": 48090.16,  # imposible para 0,99 MW
    })
    curva, completo = solarview.curva_generacion(sol, 1, "2026-08-25", capacidad_efectiva_mw=0.99)

    assert curva[10] == 500
    assert curva[18] is None or curva[18] != curva[18]  # NaN -- descartada
    assert completo is False  # la hora descartada cuenta como hueco


def test_si_todas_las_horas_son_implausibles_completo_es_falso_y_suma_cero():
    sol = _SolFalso({
        "2026-08-25 10:00": 250000,
        "2026-08-25 11:00": 300000,
    })
    curva, completo = solarview.curva_generacion(sol, 1, "2026-08-25", capacidad_efectiva_mw=0.99)

    assert completo is False
    assert float(curva.fillna(0).sum()) == 0.0


def test_sin_capacidad_efectiva_no_filtra_nada():
    """Compatibilidad hacia atras -- si no se pasa capacidad_efectiva_mw, el
    comportamiento es igual que antes de este fix: no se descarta nada."""
    sol = _SolFalso({"2026-08-25 18:00": 48090.16})
    curva, _ = solarview.curva_generacion(sol, 1, "2026-08-25")

    assert curva[18] == 48090.16


def test_lectura_dentro_del_margen_generoso_no_se_descarta():
    """El multiplicador (3x) es generoso a proposito -- un pico real de
    generacion (irradiancia alta) no debe descartarse por error."""
    sol = _SolFalso({"2026-08-25 12:00": 2500})  # ~2,5x una capacidad de 0.99 MW
    curva, _ = solarview.curva_generacion(sol, 1, "2026-08-25", capacidad_efectiva_mw=0.99)

    assert curva[12] == 2500
