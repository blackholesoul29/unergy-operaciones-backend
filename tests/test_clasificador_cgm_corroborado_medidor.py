"""Caso 1 por corroboracion del medidor (2026-09-02).

Cuando el reporte CGM es automatico pero NO cuadra contra inversores, antes
bajaba a Casos 2/3/4 o quedaba en revision manual -- aunque los inversores
(SolarView/Solenium) son hoy la fuente menos confiable y muchas veces no habia
ninguna evidencia real contra el CGM.

Ahora se le da al CGM una segunda oportunidad contra el MEDIDOR, que es una
fuente fisicamente independiente: si coinciden dentro de rango Y el CGM es
mayor que los inversores (la firma de un SolarView desactualizado), se resuelve
como Caso 1 con medidor_usado="cgm" -- se confia en el reporte que Quoia ya
envio, sin matriz de generacion (reporte_excel usa medidor_usado == "cgm" para
decidirlo) y sin revision manual.

Se exige medidor COMPLETO: uno incompleto que "cuadra" es coincidencia, no
validacion (mismo criterio que Caso 2).
"""
from datetime import date

import pandas as pd
import pytest

from app.services.reporte_energia import clasificador, historial

FECHA = date(2026, 9, 2)
FECHA_STR = str(FECHA)


@pytest.fixture(autouse=True)
def _fp_sin_db(monkeypatch):
    """Los casos donde la corroboracion NO aplica caen a Casos 2/3/4, y Caso 3
    pide el Factor de Perdida a la BD. Estos tests corren con db=None (el arbol
    de decision es puro), asi que se stubbea el FP."""
    monkeypatch.setattr(
        historial, "get_factor_perdida_detalle", lambda db, fid, fecha: (0.97, 0.97)
    )


def _curva(total_dia, horas=range(6, 18)):
    """Curva de 24h que reparte `total_dia` entre `horas`, 0 en el resto."""
    horas = list(horas)
    por_hora = total_dia / len(horas)
    return pd.Series(
        {h: (por_hora if h in horas else 0.0) for h in range(24)}, dtype=float
    )


CURVA_SIN_DATO = pd.Series([None] * 24, dtype=float)


def _decidir(*, e_cgm, e_inv, e_inv_incompleto, curva_ppal, completo_ppal,
             curva_resp=CURVA_SIN_DATO, completo_resp=False, reporte_valido=True):
    curva_inv_total = e_inv or e_inv_incompleto or 0.0
    return clasificador._decidir_caso(
        db=None, frontera_id=1, fecha=FECHA, fecha_str=FECHA_STR,
        e_cgm=e_cgm, curva_cgm=_curva(e_cgm), reporte_valido=reporte_valido,
        cgm_tiene_dato=True,
        curva_ppal=curva_ppal, curva_resp=curva_resp,
        completo_ppal=completo_ppal, completo_resp=completo_resp,
        e_inv=e_inv, e_inv_incompleto=e_inv_incompleto,
        curva_solarview=_curva(curva_inv_total),
        id_solarview=123, node_ppal=None, gaia=object(), sv=object(),
    )


# ── El caso real que motivo el cambio ────────────────────────────────────────
# Chiriguana Norte 1, 2026-09-02: CGM automatico 8.207,5 kWh, identico al
# medidor principal al decimal (respaldo 8.205,7, +0,02%), mientras los
# inversores reportaban 7.570,8 con 14h faltantes -- un 7,8% por debajo, apenas
# fuera del +-6%, que era justo lo que la mandaba a revisar a mano.
def test_inversores_incompletos_pero_medidor_confirma_el_cgm():
    resultado = _decidir(
        e_cgm=8207.5, e_inv=0.0, e_inv_incompleto=7570.8,
        curva_ppal=_curva(8207.5), completo_ppal=True,
    )

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"          # => sin matriz a Quoia
    assert resultado["revisar_manualmente"] is False
    assert resultado["energia_final_kwh"] == 8207.5


def test_inversores_completos_fuera_de_rango_pero_medidor_confirma_el_cgm():
    # Inversores 7.000 vs CGM 8.207,5 -> ~15% de error, fuera del +-6%: antes
    # bajaba a Casos 2/3/4 y el CGM se descartaba como numero final.
    resultado = _decidir(
        e_cgm=8207.5, e_inv=7000.0, e_inv_incompleto=None,
        curva_ppal=_curva(8207.5), completo_ppal=True,
    )

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"
    assert resultado["revisar_manualmente"] is False


def test_sirve_tambien_el_medidor_de_respaldo():
    resultado = _decidir(
        e_cgm=8207.5, e_inv=0.0, e_inv_incompleto=7570.8,
        curva_ppal=CURVA_SIN_DATO, completo_ppal=False,
        curva_resp=_curva(8205.7), completo_resp=True,
    )

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"


# ── Donde NO debe aplicar: se mantiene la cautela ────────────────────────────
def test_no_aplica_si_los_inversores_reportan_mas_que_el_cgm():
    """Inversores por encima del CGM sugiere que el CGM subreporta -- ese es el
    riesgo real para el ASIC, no un SolarView desactualizado. No se corrobora."""
    resultado = _decidir(
        e_cgm=7000.0, e_inv=9000.0, e_inv_incompleto=None,
        curva_ppal=_curva(7000.0), completo_ppal=True,
    )

    assert resultado["caso"] != 1


def test_no_aplica_si_el_medidor_no_coincide_con_el_cgm():
    """Sin corroboracion real (medidor tambien discrepa) se mantiene el camino
    anterior."""
    resultado = _decidir(
        e_cgm=8207.5, e_inv=7000.0, e_inv_incompleto=None,
        curva_ppal=_curva(5000.0), completo_ppal=True,
    )

    assert resultado["caso"] != 1


def test_no_aplica_si_el_medidor_esta_casi_empatado_con_los_inversores():
    """El hueco que cerro RANGO_CORROBORACION: con la tolerancia normal (+-6%)
    un medidor a -5,5% "cuadraba" con el CGM aunque los inversores estuvieran a
    -7%, o sea medidor e inversores coincidiendo ENTRE SI contra el CGM. Eso no
    es corroborar el CGM, es lo contrario -- dos fuentes diciendo que el CGM
    sobrereporta. Con la tolerancia estricta ya no aplica."""
    resultado = _decidir(
        e_cgm=100.0, e_inv=93.0, e_inv_incompleto=None,   # inversores -7%
        curva_ppal=_curva(94.5), completo_ppal=True,      # medidor    -5,5%
    )

    assert resultado["caso"] != 1


def test_no_aplica_si_el_medidor_esta_incompleto():
    """Un medidor incompleto que 'cuadra' es coincidencia, no validacion."""
    resultado = _decidir(
        e_cgm=8207.5, e_inv=0.0, e_inv_incompleto=7570.8,
        curva_ppal=_curva(8207.5), completo_ppal=False,
    )

    assert resultado["caso"] != 1 or resultado["medidor_usado"] != "cgm" or \
        resultado.get("revisar_manualmente") is not False


def test_no_aplica_si_el_reporte_no_es_automatico():
    """Sin reporte automatico valido, el CGM no es candidato a confiarse."""
    resultado = _decidir(
        e_cgm=8207.5, e_inv=7000.0, e_inv_incompleto=None,
        curva_ppal=_curva(8207.5), completo_ppal=True, reporte_valido=False,
    )

    assert resultado["caso"] != 1
