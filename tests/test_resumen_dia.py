"""Tests de la lógica pura del resumen del día (sin red ni DB)."""
import pytest

from app.api.v1 import generacion_solar as gs


# ── _sum_today_inverter_kwh ──────────────────────────────────────────────────────

def test_sum_today_only_today_entries():
    m = {
        "2026-06-09 08:00": 10,
        "2026-06-09 09:00": "15.5",   # strings también suman
        "2026-06-08 09:00": 99,        # de ayer → se ignora
    }
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == pytest.approx(25.5)


def test_sum_today_ignores_bad_values():
    m = {"2026-06-09 08:00": "n/a", "2026-06-09 09:00": 5}
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == pytest.approx(5)


@pytest.mark.parametrize("m", [None, {}])
def test_sum_today_empty(m):
    assert gs._sum_today_inverter_kwh(m, "2026-06-09") == 0.0


def test_sum_today_no_match_returns_zero():
    assert gs._sum_today_inverter_kwh({"2026-06-08 09:00": 50}, "2026-06-09") == 0.0


# ── _meter_kwh_from_detail ──────────────────────────────────────────────
# Reemplaza a _meter_kwh_from_summary: SolarView no tiene el lote de summary de
# Solenium, asi que la generacion del medidor sale de /config/project-detail/.

def test_meter_kwh_lee_el_valor_del_bloque_generation():
    detalle = {"results": {"generation": {"value": 123.4, "unit": "kWh", "complete": True}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(123.4)


def test_meter_kwh_acepta_la_respuesta_ya_desenvuelta():
    assert gs._meter_kwh_from_detail({"generation": {"value": 123.4, "unit": "kWh"}}) == pytest.approx(123.4)


def test_meter_kwh_convierte_mwh_a_kwh():
    """La unidad viene DECLARADA en el bloque y puede ser kWh o MWh -- se lee,
    nunca se asume. Verificado en vivo contra SolarView el 2026-09-03."""
    detalle = {"results": {"generation": {"value": 5.9683, "unit": "MWh"}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(5968.3)


def test_meter_kwh_tolera_mayusculas_raras_en_la_unidad():
    detalle = {"results": {"generation": {"value": 1.5, "unit": "Mwh"}}}
    assert gs._meter_kwh_from_detail(detalle) == pytest.approx(1500.0)


@pytest.mark.parametrize("d", [
    None,
    {},
    {"results": {}},
    {"results": {"generation": {}}},
    {"results": {"generation": {"value": None}}},
    {"results": {"generation": {"value": "x"}}},
])
def test_meter_kwh_sin_dato_o_ilegible_devuelve_none(d):
    assert gs._meter_kwh_from_detail(d) is None


# ── Picos espurios de SolarView ──────────────────────────────────────────────
# SolarView calcula la generacion POR DIFERENCIA DE ACUMULADOS, asi que cuando
# el acumulador se reinicia la diferencia es el acumulado historico entero.
# Verificado en vivo el 2026-09-03 con San Pedro (996 kWp): dos horas del dia
# marcaban 4.682.690,23 kWh cada una junto a valores normales de 87,52. Sin
# filtro, el total del dia daba 4,7 GWh y el de la flota 98 GWh.

def test_descarta_las_horas_fisicamente_imposibles():
    mapa = {
        "2026-09-03 00:00": 4682690.23,   # glitch
        "2026-09-03 03:00": 4682690.23,   # glitch
        "2026-09-03 06:00": 87.52,
        "2026-09-03 12:00": 640.0,
    }
    total = gs._sum_today_inverter_kwh(mapa, "2026-09-03", capacidad_kwp=996.0)

    assert total == pytest.approx(727.52), "solo las dos horas plausibles"


def test_sin_capacidad_no_se_filtra_nada():
    """No hay contra que comparar: se prefiere no inventar un techo."""
    mapa = {"2026-09-03 00:00": 4682690.23, "2026-09-03 06:00": 87.52}
    total = gs._sum_today_inverter_kwh(mapa, "2026-09-03", capacidad_kwp=None)

    assert total == pytest.approx(4682777.75)


def test_una_planta_grande_no_pierde_sus_horas_buenas():
    """El techo sale de la capacidad de CADA planta, no de un numero fijo."""
    mapa = {"2026-09-03 12:00": 6800.0}
    assert gs._sum_today_inverter_kwh(mapa, "2026-09-03", capacidad_kwp=8000.0) == pytest.approx(6800.0)


def test_solo_se_suman_las_horas_de_hoy_con_el_filtro_puesto():
    mapa = {"2026-09-02 12:00": 500.0, "2026-09-03 12:00": 640.0}
    assert gs._sum_today_inverter_kwh(mapa, "2026-09-03", capacidad_kwp=996.0) == pytest.approx(640.0)


def test_limite_hora_sin_capacidad_es_none():
    assert gs._limite_hora_kwh(None) is None
    assert gs._limite_hora_kwh(0) is None
