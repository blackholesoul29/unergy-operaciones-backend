"""Pruebas del cálculo de generación mensual promedio.

Solo el núcleo puro: sin red, sin BD. Es donde vive la regla —qué días cuentan y
cuáles no— y es lo único que puede dar un número equivocado en silencio.

La ventana es **móvil**: los últimos 30 días corridos, no el mes calendario
anterior. Un promedio "de julio" consultado el 9 de agosto describe algo que
terminó hace más de una semana; los últimos 30 días describen la planta hoy.
"""
from datetime import date, timedelta

import pytest

from app.services import gen_promedio as gp

HOY = date(2026, 8, 9)


def ventana(hoy, dias, kwh_por_dia, saltear=0):
    """`{fecha: kwh}` para los `dias` días previos a `hoy`, salteando los primeros
    `saltear` (simula días sin lectura del monitoreo)."""
    fechas = [hoy - timedelta(days=d) for d in range(1, dias + 1)]
    return {f: kwh_por_dia for f in fechas[saltear:]}


# ── la ventana ───────────────────────────────────────────────────────────────

def test_promedia_los_ultimos_30_dias_corridos():
    # 30 días × 1000 kWh = 30.000 kWh = 30 MWh
    r = gp.promedio_mensual(ventana(HOY, 30, 1000.0), hoy=HOY)
    assert r["promedio_mwh"] == 30.0
    assert r["dias"] == 30
    assert r["desde"] == HOY - timedelta(days=30)
    assert r["hasta"] == HOY - timedelta(days=1)


def test_el_dia_de_hoy_no_entra_porque_esta_a_medias():
    por_dia = ventana(HOY, 30, 1000.0)
    por_dia[HOY] = 50.0                      # lo poco que va del día
    r = gp.promedio_mensual(por_dia, hoy=HOY)
    assert r["promedio_mwh"] == 30.0         # los 50 kWh de hoy no lo mueven
    assert r["hasta"] == HOY - timedelta(days=1)


def test_lo_anterior_a_la_ventana_no_entra():
    """El mes pasado ya no describe a la planta: por eso la ventana es móvil."""
    por_dia = ventana(HOY, 30, 1000.0)
    for d in range(31, 90):                  # histórico viejo, mucho más alto
        por_dia[HOY - timedelta(days=d)] = 9000.0
    r = gp.promedio_mensual(por_dia, hoy=HOY)
    assert r["promedio_mwh"] == 30.0


def test_una_ventana_distinta_se_normaliza_a_30_dias():
    """El campo es un mes típico: con 60 días de ventana el número no se duplica."""
    r = gp.promedio_mensual(ventana(HOY, 60, 1000.0), hoy=HOY, dias=60)
    assert r["promedio_mwh"] == 30.0
    assert r["dias"] == 60


# ── días faltantes ───────────────────────────────────────────────────────────

def test_faltar_pocos_dias_no_invalida_la_ventana():
    # 27 de 30 días = 90% > 85%. Se normaliza por los días CON lectura, no por 30:
    # si no, un hueco del monitoreo se leería como que la planta generó menos.
    r = gp.promedio_mensual(ventana(HOY, 30, 1000.0, saltear=3), hoy=HOY)
    assert r["dias_con_datos"] == 27
    assert r["promedio_mwh"] == 30.0


def test_faltar_muchos_dias_no_produce_un_numero_subestimado():
    """Mide la caída del monitoreo, no la de la planta: mejor no dar número."""
    r = gp.promedio_mensual(ventana(HOY, 30, 1000.0, saltear=20), hoy=HOY)
    assert r["promedio_mwh"] is None
    assert "10 de 30" in r["motivo"]


def test_sin_lecturas_devuelve_none_no_cero():
    """'No sé' y 'genera cero' son cosas distintas: un 0 haría ver como muerta
    a una planta que solo no tiene histórico cargado."""
    r = gp.promedio_mensual({}, hoy=HOY)
    assert r["promedio_mwh"] is None
    assert r["dias_con_datos"] == 0
    assert "sin lecturas" in r["motivo"]


def test_una_planta_recien_energizada_no_alcanza_la_ventana():
    # Energizada hace 5 días: 5 de 30 días. No hay promedio confiable todavía.
    r = gp.promedio_mensual(ventana(HOY, 5, 1000.0), hoy=HOY)
    assert r["promedio_mwh"] is None
    assert "5 de 30" in r["motivo"]


def test_los_ceros_reales_si_cuentan():
    """Un día nublado con lectura 0 es información: baja el promedio de verdad."""
    por_dia = ventana(HOY, 30, 1000.0)
    for d in range(1, 6):
        por_dia[HOY - timedelta(days=d)] = 0.0
    r = gp.promedio_mensual(por_dia, hoy=HOY)
    assert r["dias_con_datos"] == 30
    assert r["promedio_mwh"] == pytest.approx(25.0, rel=1e-6)


# ── manual vs. api ───────────────────────────────────────────────────────────

class ProyFalso:
    def __init__(self, origen=None, sub="algo", alias=None):
        self.gen_promedio_origen = origen
        self.sub_project = sub
        self.alias_monitoreo = alias


def test_no_se_pisa_un_valor_cargado_a_mano():
    assert "manual" in gp.decidir(ProyFalso(origen="manual"), force=False)


def test_con_force_si_se_pisa():
    assert gp.decidir(ProyFalso(origen="manual"), force=True) is None


def test_una_planta_sin_identificador_de_monitoreo_se_manda_a_carga_manual():
    assert "a mano" in gp.decidir(ProyFalso(sub=None), force=False)


def test_el_alias_de_monitoreo_sirve_como_identificador():
    assert gp.decidir(ProyFalso(sub=None, alias="otro_nombre"), force=False) is None


def test_un_valor_de_api_se_recalcula_sin_force():
    assert gp.decidir(ProyFalso(origen="api"), force=False) is None


# ── caso real ────────────────────────────────────────────────────────────────

def test_caso_real_valle_de_gandalf():
    """MGS 0004 Valle de Gandalf, reportado por operaciones el 2026-08-09:
    227.467 kWh entre el 8 de julio y el 8 de agosto (32 días) → ~7.108 kWh/día.

    La vista mostraba 57,9 MWh, que eran los 8 días que iban de agosto. El
    promedio de 30 días tiene que quedar en el orden de los 200 MWh, que es lo
    que genera de verdad una minigranja de 1 MW.
    """
    kwh_dia = 227_467 / 32
    r = gp.promedio_mensual(ventana(HOY, 30, kwh_dia), hoy=HOY)
    assert r["promedio_mwh"] == pytest.approx(213.3, abs=0.5)
    assert r["promedio_mwh"] > 200, "una MGS de 1 MW no genera 57 MWh al mes"
