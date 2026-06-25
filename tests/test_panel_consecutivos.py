"""
La cadena de consecutivos de COSTOS se asigna por la decisión del usuario
(liquidar_costos), sin exigir que el ER haya traído líneas de costos (tiene_costos).
Un proyecto puede tener costos que este mes no llegaron en el ER o que vendrán de la
vista de costos.
"""
from types import SimpleNamespace
from app.api.v1.panel_contable import _asignar_consecutivos


def _panel(id, liq_ing=False, liq_cost=False, tiene_costos=False):
    return SimpleNamespace(
        id=id, liquidar_ingresos=liq_ing, liquidar_costos=liq_cost,
        tiene_costos=tiene_costos, consecutivo_ingresos=None, consecutivo_costos=None,
    )


def test_costos_se_numera_aunque_no_haya_lineas_de_costos():
    # Proyecto marcado para liquidar costos pero cuyo ER no trajo costos.
    p = _panel(1, liq_cost=True, tiene_costos=False)
    _asignar_consecutivos([p], ini_ing=900, ini_cos=800, solo_faltantes=False)
    assert p.consecutivo_costos == 800   # antes habría quedado en None


def test_no_marcado_no_recibe_consecutivo_de_costos():
    p = _panel(1, liq_cost=False, tiene_costos=False)
    _asignar_consecutivos([p], ini_ing=900, ini_cos=800, solo_faltantes=False)
    assert p.consecutivo_costos is None


def test_cadena_costos_independiente_de_ingresos():
    a = _panel(1, liq_ing=True, liq_cost=False)
    b = _panel(2, liq_ing=False, liq_cost=True, tiene_costos=False)
    c = _panel(3, liq_ing=True, liq_cost=True, tiene_costos=True)
    _asignar_consecutivos([a, b, c], ini_ing=900, ini_cos=800, solo_faltantes=False)
    # Ingresos: a y c en orden -> 900, 901 ; b sin ingresos -> None
    assert (a.consecutivo_ingresos, b.consecutivo_ingresos, c.consecutivo_ingresos) == (900, None, 901)
    # Costos: b y c -> 800, 801 ; a sin costos -> None
    assert (a.consecutivo_costos, b.consecutivo_costos, c.consecutivo_costos) == (None, 800, 801)
