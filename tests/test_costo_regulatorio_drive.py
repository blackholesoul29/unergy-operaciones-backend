"""Ingesta del costo regulatorio desde el Drive de ER. La selección de período/versión
es pura; la orquestación inyecta las funciones de Drive (sin red)."""
from app.services.costo_regulatorio_drive import _rank_version, seleccionar_cruce


def _cruce(anio, mes, version, fid):
    return {"id": fid, "anio": anio, "mes": mes, "version": version}


def test_rank_version_txf_es_la_mas_alta_y_txN_por_numero():
    assert _rank_version("txf") > _rank_version("tx8")
    assert _rank_version("tx8") > _rank_version("tx3")
    assert _rank_version("???") < _rank_version("tx3")


def test_selecciona_periodo_exacto_prefiriendo_txf():
    cruces = [
        _cruce(2026, 7, "tx3", "a"),
        _cruce(2026, 7, "txf", "b"),
        _cruce(2026, 6, "txf", "c"),
    ]
    elegido = seleccionar_cruce(cruces, 2026, 7)
    assert elegido["id"] == "b"
    assert elegido["fallback"] is False


def test_fallback_al_ultimo_periodo_no_mayor_al_pedido():
    # Se pide agosto (aún no cerrado, no hay cruce) -> cae a julio, el último <= agosto.
    cruces = [
        _cruce(2026, 6, "txf", "jun"),
        _cruce(2026, 7, "txf", "jul"),
    ]
    elegido = seleccionar_cruce(cruces, 2026, 8)
    assert elegido["id"] == "jul"
    assert elegido["fallback"] is True
    assert (elegido["anio"], elegido["mes"]) == (2026, 7)


def test_sin_cruces_devuelve_none():
    assert seleccionar_cruce([], 2026, 8) is None
