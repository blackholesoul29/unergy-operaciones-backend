"""_decidir_caso() -- CGM valido + inversores incompletos, comparados
dentro de la ventana solar.

Si el reporte CGM es automatico/valido y los inversores reportan
incompletos ese dia, se compara CGM contra el total PARCIAL de inversores
dentro de la ventana solar (no el dia completo) solo como chequeo de
plausibilidad -- el numero reportado sigue siendo CGM en cualquier caso.
Si esa comparacion queda dentro de rango, es funcionalmente lo mismo que
Caso 1 (se confia en CGM, sin revision) -- se reclasifica a Caso 1 para
que "Revision de hoy" no lo muestre como "Corregido automatico" cuando en
realidad no se corrigio nada (pedido 2026-08-21). Si el error se sale de
rango, se queda en Caso 5 + revisar_manualmente, sin cambios.
"""
from datetime import date

import pandas as pd

from app.services.reporte_energia import clasificador

FECHA = date(2026, 8, 21)
FECHA_STR = str(FECHA)


def _curva_pareja(valor_horas_solares):
    """Serie de 24h con `valor_horas_solares` en cada hora de la ventana
    solar (6-17) y 0 fuera de ella."""
    data = {h: (valor_horas_solares if 6 <= h < 18 else 0.0) for h in range(24)}
    return pd.Series(data, dtype=float)


def _decidir(reporte_valido, e_inv_incompleto, curva_solarview, curva_cgm):
    e_cgm = float(curva_cgm.sum())
    curva_vacia = pd.Series([None] * 24, dtype=float)
    return clasificador._decidir_caso(
        db=None, frontera_id=1, fecha=FECHA, fecha_str=FECHA_STR,
        e_cgm=e_cgm, curva_cgm=curva_cgm, reporte_valido=reporte_valido,
        cgm_tiene_dato=True,
        curva_ppal=curva_vacia, curva_resp=curva_vacia,
        completo_ppal=False, completo_resp=False,
        e_inv=0.0, e_inv_incompleto=e_inv_incompleto, curva_solarview=curva_solarview,
        id_solarview=123, node_ppal=None, gaia=object(), sv=object(),
    )


def test_en_rango_se_reclasifica_a_caso1():
    curva_cgm = _curva_pareja(100.0)
    curva_solenium = _curva_pareja(100.0)  # mismo total en la ventana -- error 0%

    resultado = _decidir(True, 500.0, curva_solenium, curva_cgm)

    assert resultado["caso"] == 1
    assert resultado["medidor_usado"] == "cgm"
    assert resultado["revisar_manualmente"] is False
    assert resultado["energia_final_kwh"] == float(curva_cgm.sum())


def test_fuera_de_rango_se_queda_en_caso5():
    curva_cgm = _curva_pareja(100.0)
    curva_solenium = _curva_pareja(300.0)  # ~67% de error dentro de la ventana

    resultado = _decidir(True, 500.0, curva_solenium, curva_cgm)

    assert resultado["caso"] == 5
    assert resultado["medidor_usado"] == "cgm"
    assert resultado["revisar_manualmente"] is True


def test_sin_inversores_en_absoluto_no_reclasifica():
    """Sin e_inv_incompleto (inversores realmente ausentes, no solo
    incompletos) no hay nada que validar -- sigue Caso 5, sin que esta
    rama toque revisar_manualmente."""
    curva_cgm = _curva_pareja(100.0)
    curva_vacia = pd.Series([None] * 24, dtype=float)

    resultado = _decidir(True, None, curva_vacia, curva_cgm)

    assert resultado["caso"] == 5
    assert resultado["medidor_usado"] == "cgm"
    assert "revisar_manualmente" not in resultado
