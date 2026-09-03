"""Regla TEMPORAL (2026-09-02): reportar con inversores x FP => revisar manual.

Toda frontera que termine con `medidor_usado == "inversores"` (lo que la
plataforma muestra como "Inversores x FP") sale marcada
`revisar_manualmente = True`, sin importar el Caso. Motivo: la generacion de
Solenium a veces llega desactualizada aunque el dia figure completo, y el total
de inversores es justo la base de ese reporte.

Es contencion, no una regla del arbol de Casos: CUANDO SOLENIUM SE NORMALICE Y
SE QUITE LA REGLA, ESTE ARCHIVO SE BORRA TAMBIEN. El mismo cambio esta portado
en Reporte-Energia (process/src/internals/clasificador.py).
"""
from datetime import date

import pandas as pd

from app.services.reporte_energia import clasificador, historial

FECHA = date(2026, 9, 2)
FECHA_STR = str(FECHA)


def _curva(valor_por_hora_solar):
    """24h con `valor_por_hora_solar` en la ventana solar (6-17), 0 fuera."""
    return pd.Series(
        {h: (valor_por_hora_solar if 6 <= h < 18 else 0.0) for h in range(24)},
        dtype=float,
    )


def _decidir():
    """Escenario de Caso 3: reporte CGM no valido y los medidores subreportan
    frente a los inversores (1.000 kWh de inversores vs 800 de medidor, +20%
    de error, fuera del rango aceptable), asi que se reporta con
    inversores x FP."""
    curva_medidor = _curva(800.0 / 12)   # 800 kWh en el dia
    return clasificador._decidir_caso(
        db=None, frontera_id=1, fecha=FECHA, fecha_str=FECHA_STR,
        e_cgm=0.0, curva_cgm=_curva(0.0), reporte_valido=False,
        cgm_tiene_dato=False,
        curva_ppal=curva_medidor, curva_resp=pd.Series([None] * 24, dtype=float),
        completo_ppal=True, completo_resp=False,
        e_inv=1000.0, e_inv_incompleto=None, curva_solarview=_curva(1000.0 / 12),
        id_solarview=123, node_ppal=None, gaia=object(), sv=object(),
    )


def test_caso3_inversores_fp_queda_para_revision_manual(monkeypatch):
    monkeypatch.setattr(
        historial, "get_factor_perdida_detalle", lambda db, fid, fecha: (0.97, 0.97)
    )

    resultado = _decidir()

    assert resultado["caso"] == 3
    assert resultado["medidor_usado"] == "inversores"
    assert resultado["revisar_manualmente"] is True
    # El numero reportado sigue siendo inversores x FP -- la marca de revision
    # no cambia el dato, solo pide que alguien lo confirme.
    assert resultado["energia_final_kwh"] == 1000.0 * 0.97
