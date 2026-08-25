"""Internet sale de la factura real de Starlink, no del Excel.

Cruzado contra 2026-07: los 26 proyectos que tienen internet en el Panel cuadran
al peso con Starlink, 3.894.133 en ambos lados. Las 14 líneas de Starlink que no
cruzan son plantas no operativas, y por eso el total de Starlink es mayor.
"""
import types

from app.services.costos_panel import CONCEPTO_INTERNET, internet_desde_starlink


def _linea(sin_iva, iva=0.0, excluido=False):
    return types.SimpleNamespace(sin_iva=sin_iva, iva=iva, excluido=excluido)


def test_devuelve_la_base_en_negativo():
    """Los costos del Panel van en negativo."""
    out = internet_desde_starlink([_linea(64_706.0, 12_294.0)])
    assert out[CONCEPTO_INTERNET]["valor"] == -64_706.0


def test_no_devuelve_el_iva():
    """El Panel lo deriva por cliente al leer; mandarlo aquí lo duplicaría."""
    out = internet_desde_starlink([_linea(64_706.0, 12_294.0)])
    assert "iva" not in out[CONCEPTO_INTERNET]


def test_marca_la_fuente():
    """La vista muestra de dónde salió cada costo."""
    out = internet_desde_starlink([_linea(64_706.0)])
    assert out[CONCEPTO_INTERNET]["fuente"] == "starlink"


def test_va_al_grupo_de_costos():
    assert internet_desde_starlink([_linea(1.0)])[CONCEPTO_INTERNET]["grupo"] == "costos"


def test_suma_varias_lineas_del_mismo_proyecto():
    """Perija tiene dos sitios: 64.706 + 64.707 = 129.413."""
    out = internet_desde_starlink([_linea(64_706.0), _linea(64_707.0)])
    assert out[CONCEPTO_INTERNET]["valor"] == -129_413.0


def test_ignora_las_lineas_excluidas():
    """Starlink permite excluir cargos que no son del proyecto."""
    out = internet_desde_starlink([_linea(64_706.0), _linea(999.0, excluido=True)])
    assert out[CONCEPTO_INTERNET]["valor"] == -64_706.0


def test_sin_lineas_no_devuelve_el_concepto():
    """Devolver 0 pisaría con un cero falso el valor que traiga el ER."""
    assert internet_desde_starlink([]) == {}


def test_solo_lineas_excluidas_tampoco_devuelve_el_concepto():
    assert internet_desde_starlink([_linea(999.0, excluido=True)]) == {}


def test_un_sin_iva_nulo_no_revienta():
    out = internet_desde_starlink([_linea(None), _linea(64_706.0)])
    assert out[CONCEPTO_INTERNET]["valor"] == -64_706.0
