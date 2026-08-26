"""curvas._curva_nodo() / curvas_de_frontera() -- descartar horas del
medidor de nodo (Quoia) físicamente implausibles.

Mismo criterio ya aplicado a SolarView/reconectador/CGM/datos crudos (ver
limite_plausible_kwh() en utils.py). Ver MGS 0010 Villanueva 2026-08-26:
el glitch original se encontró en SolarView, pero el medidor de nodo es
el de MAYOR riesgo -- estas curvas se reportan DIRECTO como curva_final
en Casos 2/4/5, sin FP ni comparación de por medio."""
from app.services.reporte_energia import curvas


def _fila(hora, valor):
    ts = f"2026-08-26T{hora:02d}:00:00"
    return {"time": ts, "eaepd1": valor, "eaepd2": 0, "eaepd3": 0}


class _GaiaStub:
    def __init__(self, filas):
        self._filas = filas

    def get_node_measurements(self, node_id, fecha_str, var_name):
        return self._filas


def test_curva_nodo_descarta_hora_implausible():
    filas = [_fila(10, 500), _fila(11, 48090)]  # 48.090 kWh en 1h -- implausible para 0,99 MW
    curva, completo = curvas._curva_nodo(
        _GaiaStub(filas), node_id=1, fecha_str="2026-08-26", label="test",
        var_name="eae", capacidad_efectiva_mw=0.99,
    )

    assert curva[10] == 500
    assert curva[11] is None or curva[11] != curva[11]  # NaN -- descartada
    assert completo is False  # la hora descartada cuenta como hueco


def test_curva_nodo_sin_capacidad_efectiva_no_filtra():
    filas = [_fila(11, 48090)]
    curva, _ = curvas._curva_nodo(
        _GaiaStub(filas), node_id=1, fecha_str="2026-08-26", label="test", var_name="eae",
    )
    assert curva[11] == 48090


def test_curva_nodo_lectura_dentro_del_margen_no_se_descarta():
    filas = [_fila(11, 2500)]  # ~2,5x una capacidad de 0.99 MW -- dentro del margen 3x
    curva, _ = curvas._curva_nodo(
        _GaiaStub(filas), node_id=1, fecha_str="2026-08-26", label="test",
        var_name="eae", capacidad_efectiva_mw=0.99,
    )
    assert curva[11] == 2500


def test_curvas_de_frontera_propaga_capacidad_efectiva_a_los_4_medidores(monkeypatch):
    """curvas_de_frontera() trae eae+iae x principal+respaldo -- las 4
    llamadas a _curva_nodo() deben recibir la misma capacidad_efectiva_mw
    de la frontera."""
    llamados = []

    def _fake_curva_nodo(gaia, node_id, fecha_str, label, var_name="eae", capacidad_efectiva_mw=None):
        llamados.append((label, var_name, capacidad_efectiva_mw))
        import pandas as pd
        return pd.Series([0.0] * 24, dtype=float), True

    monkeypatch.setattr(curvas, "_curva_nodo", _fake_curva_nodo)

    curvas.curvas_de_frontera(
        gaia=object(), mapa_medidor_nodo={1: 10, 2: 20}, main_meter_id=1, backup_meter_id=2,
        fecha_str="2026-08-26", frt_code="frt001", recuperar=False, capacidad_efectiva_mw=0.99,
    )

    assert len(llamados) == 4
    assert all(cap == 0.99 for _, _, cap in llamados)
