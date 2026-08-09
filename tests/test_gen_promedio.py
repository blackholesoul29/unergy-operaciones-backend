"""Pruebas del cálculo de generación mensual promedio.

Solo el núcleo puro: sin red, sin BD. Es donde vive la regla —qué mes cuenta y
cuál no— y es lo único que puede dar un número equivocado en silencio.
"""
from datetime import date

import pytest

from app.services import gen_promedio as gp


def dias_del_mes(anio, mes, kwh_por_dia, dias=None):
    """`{fecha: kwh}` para un mes, con `dias` días de lectura (por defecto todos)."""
    import calendar
    total = calendar.monthrange(anio, mes)[1]
    return {date(anio, mes, d): kwh_por_dia for d in range(1, (dias or total) + 1)}


# ── agrupar ──────────────────────────────────────────────────────────────────

def test_agrupar_suma_kwh_y_cuenta_dias():
    por_dia = {**dias_del_mes(2026, 5, 100.0), **dias_del_mes(2026, 6, 200.0)}
    m = gp.agrupar_por_mes(por_dia)
    assert m[(2026, 5)] == {"kwh": 3100.0, "dias": 31}
    assert m[(2026, 6)] == {"kwh": 6000.0, "dias": 30}


# ── la regla ─────────────────────────────────────────────────────────────────

def test_promedia_los_meses_completos_en_mwh():
    # mayo: 31 × 1000 kWh = 31 MWh · junio: 30 × 1000 = 30 MWh → promedio 30.5
    por_dia = {**dias_del_mes(2026, 5, 1000.0), **dias_del_mes(2026, 6, 1000.0)}
    r = gp.promedio_mensual(por_dia, hoy=date(2026, 7, 15))
    assert r["promedio_mwh"] == 30.5
    assert r["meses"] == 2
    assert (r["desde"], r["hasta"]) == (date(2026, 5, 1), date(2026, 6, 30))


def test_el_mes_en_curso_no_entra():
    """Está a medias: contarlo bajaría el promedio sin que la planta cambie."""
    por_dia = {**dias_del_mes(2026, 6, 1000.0),
               **dias_del_mes(2026, 7, 1000.0, dias=5)}   # julio recién empieza
    r = gp.promedio_mensual(por_dia, hoy=date(2026, 7, 5))
    assert r["meses"] == 1
    assert r["promedio_mwh"] == 30.0
    assert any("mes en curso" in d for d in r["descartados"])


def test_un_mes_con_pocos_dias_de_lectura_se_descarta():
    """Mide la caída del monitoreo, no la de la planta."""
    por_dia = {**dias_del_mes(2026, 5, 1000.0),
               **dias_del_mes(2026, 6, 1000.0, dias=10)}   # solo 10 de 30 días
    r = gp.promedio_mensual(por_dia, hoy=date(2026, 7, 1))
    assert r["meses"] == 1
    assert r["promedio_mwh"] == 31.0
    assert any("10 de 30" in d for d in r["descartados"])


def test_un_mes_al_que_le_falta_un_fin_de_semana_si_cuenta():
    # 28 de 31 días = 90% > 85%: un hueco corto del monitoreo no invalida el mes.
    por_dia = dias_del_mes(2026, 5, 1000.0, dias=28)
    r = gp.promedio_mensual(por_dia, hoy=date(2026, 7, 1))
    assert r["meses"] == 1
    assert r["promedio_mwh"] == 28.0


def test_solo_se_toman_los_ultimos_n_meses():
    por_dia = {}
    for mes, kwh in ((1, 1000.0), (2, 1000.0), (3, 1000.0), (4, 5000.0), (5, 5000.0)):
        por_dia.update(dias_del_mes(2026, mes, kwh))
    r = gp.promedio_mensual(por_dia, hoy=date(2026, 6, 10), meses=2)
    assert r["meses"] == 2
    assert r["desde"] == date(2026, 4, 1)      # abril y mayo, los dos últimos
    assert r["promedio_mwh"] == pytest.approx((30 * 5000 + 31 * 5000) / 2 / 1000, rel=1e-6)


# ── cuando no se puede ───────────────────────────────────────────────────────

def test_sin_lecturas_devuelve_none_no_cero():
    """'No sé' y 'genera cero' son cosas distintas: un 0 haría ver como muerta
    a una planta que solo no tiene histórico cargado."""
    r = gp.promedio_mensual({}, hoy=date(2026, 8, 9))
    assert r["promedio_mwh"] is None
    assert r["meses"] == 0
    assert "sin lecturas" in r["motivo"]


def test_solo_el_mes_en_curso_tampoco_alcanza():
    r = gp.promedio_mensual(dias_del_mes(2026, 8, 1000.0, dias=8), hoy=date(2026, 8, 9))
    assert r["promedio_mwh"] is None
    assert "ningún mes completo" in r["motivo"]


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
    motivo = gp.decidir(ProyFalso(sub=None), force=False)
    assert "a mano" in motivo


def test_el_alias_de_monitoreo_sirve_como_identificador():
    assert gp.decidir(ProyFalso(sub=None, alias="otro_nombre"), force=False) is None


def test_un_valor_de_api_se_recalcula_sin_force():
    assert gp.decidir(ProyFalso(origen="api"), force=False) is None
