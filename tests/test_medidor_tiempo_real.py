"""snapshot_medidor() / elegir_medidor() -- la lectura del medidor para la
vista de Generación Solar, por el mismo camino que el pipeline del ASIC.

Reemplaza a GaiaClient.get_node_electrical_snapshot() en ese uso: el compuesto
pide las 8 familias de variables del nodo y la tarjeta lo hacía para principal
y respaldo (hasta 16 llamadas externas por proyecto para dibujar dos líneas).
Acá se piden solo `ap` y `eae`.
"""
import pytest

from app.services.mgs.medidor_tiempo_real import elegir_medidor, snapshot_medidor


class _GaiaFake:
    """Devuelve filas con la forma real verificada en vivo el 2026-09-03:
    {time, node_id, artificial, recovered, app1..3 | eaepd1..3}."""

    def __init__(self, ap=None, eae=None):
        self._ap = ap or []
        self._eae = eae or []
        self.llamadas = []

    def get_node_measurements(self, node_id, fecha_str, var_name):
        self.llamadas.append((node_id, fecha_str, var_name))
        return self._ap if var_name == "ap" else self._eae


def _ap(hora, kw, recovered=False):
    return {"time": f"2026-09-03T{hora}-05:00", "node_id": 1731, "artificial": False,
            "recovered": recovered, "app1": kw / 3, "app2": kw / 3, "app3": kw / 3}


def _eae(hora, kwh):
    return {"time": f"2026-09-03T{hora}-05:00", "node_id": 1731, "artificial": False,
            "recovered": False, "eaepd1": kwh / 3, "eaepd2": kwh / 3, "eaepd3": kwh / 3}


def test_pide_solo_ap_y_eae():
    """El punto del cambio: dos variables en vez de las ocho del compuesto."""
    gaia = _GaiaFake(ap=[_ap("10:00:00", 500)])
    snapshot_medidor(gaia, 1731, "2026-09-03")

    assert [v for _, _, v in gaia.llamadas] == ["ap", "eae"]


def test_la_potencia_de_ahora_es_la_ultima_lectura_real():
    gaia = _GaiaFake(ap=[_ap("09:00:00", 300), _ap("10:00:00", 500), _ap("11:00:00", 846.2)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03")

    assert s["potencia_kw"] == pytest.approx(846.2)
    assert s["ultima_lectura"] == "2026-09-03T11:00:00-05:00", "sirve para mostrar la frescura"
    assert s["lecturas"] == 3


def test_descarta_los_marcadores_sinteticos_de_quoia():
    """Filas `recovered`: 0.0 insertados justo antes de la lectura real. El
    compuesto NO los filtra; el pipeline del ASIC sí (ver datos_crudos.py,
    donde no filtrarlos multiplicaba la energía por ~70x en un intervalo)."""
    gaia = _GaiaFake(ap=[
        _ap("09:45:00", 700),
        _ap("10:00:00", 0, recovered=True),
        _ap("10:00:05", 720),
    ])
    s = snapshot_medidor(gaia, 1731, "2026-09-03")

    assert s["lecturas"] == 2
    assert s["descartadas"] == 1
    assert all(p["kw"] > 0 for p in s["curva"]), "no debe quedar ningún cero sintético"
    assert s["potencia_kw"] == pytest.approx(720)


def test_corrige_el_signo_de_medidores_con_polaridad_invertida():
    """Verificado en vivo: el nodo 1731 reporta -721,7 kW generando."""
    gaia = _GaiaFake(ap=[_ap("09:45:00", -721.7)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03")

    assert s["potencia_kw"] == pytest.approx(721.7)


def test_detecta_vatios_comparando_contra_la_capacidad_instalada():
    """Una planta de 1 MW no puede entregar 850.000 kW -- son vatios."""
    gaia = _GaiaFake(ap=[_ap("10:00:00", 846_200)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03", capacidad_efectiva_mw=1.0)

    assert s["potencia_kw"] == pytest.approx(846.2)


def test_no_divide_cuando_los_valores_ya_estan_en_kilovatios():
    gaia = _GaiaFake(ap=[_ap("10:00:00", 846.2)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03", capacidad_efectiva_mw=1.0)

    assert s["potencia_kw"] == pytest.approx(846.2)


def test_una_planta_de_mas_de_5_mw_no_se_divide_por_error():
    """El compuesto asume vatios si algún valor pasa de 5000, así que una
    planta de 8 MW quedaba dividida entre 1000. Con la capacidad como
    referencia eso no pasa."""
    gaia = _GaiaFake(ap=[_ap("12:00:00", 7_400)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03", capacidad_efectiva_mw=8.0)

    assert s["potencia_kw"] == pytest.approx(7_400), "7.400 kW es plausible para 8 MW"


def test_la_energia_del_dia_sale_del_contador_no_de_integrar_la_curva():
    """Por eso los huecos en la curva no la afectan: es el punto que hace
    innecesario el relleno con potencia derivada."""
    gaia = _GaiaFake(
        ap=[_ap("09:00:00", 300)],
        eae=[_eae("09:00:00", 2000.0), _eae("10:00:00", 3995.0)],
    )
    s = snapshot_medidor(gaia, 1731, "2026-09-03")

    assert s["energia_kwh"] == pytest.approx(5995.0)
    assert s["lecturas"] == 1, "una sola lectura de potencia y aun así la energía está completa"


def test_no_se_rellenan_los_huecos():
    """La curva se entrega tal cual: si `ap` se cayó, el hueco se ve."""
    gaia = _GaiaFake(ap=[_ap("09:00:00", 700), _ap("15:00:00", 400)])
    s = snapshot_medidor(gaia, 1731, "2026-09-03")

    assert [p["time"][11:16] for p in s["curva"]] == ["09:00", "15:00"], (
        "entre las 9 y las 15 no se inventa ningún punto"
    )


def test_sin_nodo_devuelve_none_pero_sin_dato_devuelve_estructura():
    """'no hay medidor' y 'el medidor no reportó' no son lo mismo."""
    assert snapshot_medidor(_GaiaFake(), None, "2026-09-03") is None

    s = snapshot_medidor(_GaiaFake(), 1731, "2026-09-03")
    assert s is not None
    assert s["curva"] == [] and s["potencia_kw"] is None and s["lecturas"] == 0


def test_elige_el_medidor_que_reporta_mejor_no_el_de_mayor_energia():
    """'Mayor valor' es el criterio que el clasificador de Consumo descartó en
    julio: un hueco de telemetría infla un medidor y lo hace ganar siempre."""
    principal = {"lecturas": 80, "energia_kwh": 5000.0}
    respaldo = {"lecturas": 6, "energia_kwh": 9000.0}

    snap, tipo = elegir_medidor(principal, respaldo)

    assert tipo == "principal", "80 lecturas reales le ganan a 6 con más energía acumulada"
    assert snap is principal


def test_elige_el_respaldo_cuando_el_principal_esta_caido():
    principal = {"lecturas": 2, "energia_kwh": 100.0}
    respaldo = {"lecturas": 77, "energia_kwh": 90.0}

    _, tipo = elegir_medidor(principal, respaldo)

    assert tipo == "respaldo"


def test_en_empate_gana_el_principal():
    """Es el medidor de liquidación: sin razón para preferir el otro, ese."""
    _, tipo = elegir_medidor({"lecturas": 77}, {"lecturas": 77})
    assert tipo == "principal"


def test_elegir_medidor_tolera_que_falte_alguno():
    assert elegir_medidor(None, None) == (None, None)
    assert elegir_medidor({"lecturas": 3}, None)[1] == "principal"
    assert elegir_medidor(None, {"lecturas": 3})[1] == "respaldo"
