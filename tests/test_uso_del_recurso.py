"""Figura 'Uso del recurso': flags exclusivos y clasificación doble (a+c).

Una planta cuyo cliente está en bolsa pero que Unergy mete a un contrato para
cumplir (pagándole al cliente a precio bolsa) clasifica DOBLE: fila estándar en
(a) PPA Venta + fila espejo en (c) Compra en Bolsa con vendedor = el cliente.
Es distinta del duplicado clásico (compra real en bolsa), que solo vive en (c).
"""
import pytest
from fastapi import HTTPException


def test_flags_exclusivos_rechaza_ambos_true():
    from app.api.v1.asic import _validar_flags_exclusivos
    with pytest.raises(HTTPException) as exc:
        _validar_flags_exclusivos(es_duplicado=True, uso_del_recurso=True)
    assert exc.value.status_code == 422


def test_flags_exclusivos_acepta_combinaciones_validas():
    from app.api.v1.asic import _validar_flags_exclusivos
    _validar_flags_exclusivos(True, False)
    _validar_flags_exclusivos(False, True)
    _validar_flags_exclusivos(False, False)


def _data_ur():
    return {
        "venta": [
            {"id": 5, "nombre": "Terpel 8", "comprador_nombre": "Terpel",
             "plantas": [
                 {"id": 55, "nombre": "GD Yuan Solar", "codigo_sic": "89900",
                  "es_duplicado": False, "uso_del_recurso": True,
                  "fecha_inicio": "2026-06-01", "fecha_fin": "2040-12-31"},
                 {"id": 99, "nombre": "Planta Normal", "codigo_sic": "89999",
                  "es_duplicado": False, "uso_del_recurso": False,
                  "fecha_inicio": "2026-01-01", "fecha_fin": "2040-12-31"},
             ]},
        ],
        "compra": [], "bolsa": [], "bolsa_libre": [], "bolsa_comercializador": [],
    }


def test_uso_del_recurso_en_a_y_espejo_en_c():
    from app.services.clasificacion_energia import derivar_pools
    pools = derivar_pools(_data_ur())["pools"]
    terpel = pools["ppa_venta_ungg"][0]
    assert {p["id"] for p in terpel["plantas"]} == {55, 99}
    assert len(pools["bolsa_compra_ungg"]) == 1
    assert [p["id"] for p in pools["bolsa_compra_ungg"][0]["plantas"]] == [55]
    assert pools["bolsa_compra_ungg"][0]["plantas"][0]["uso_del_recurso"] is True


def test_filas_snapshot_doble_a_y_c():
    """A diferencia del duplicado (solo fila en c), uso_del_recurso genera fila
    estándar en (a) Y fila espejo en (c), ambas con el flag."""
    from app.services.clasificacion_energia import derivar_pools, _filas_desde_pools
    pools = derivar_pools(_data_ur())["pools"]
    filas = _filas_desde_pools(pools, 2026, 7)
    de_55 = [(f.categoria, bool(f.uso_del_recurso)) for f in filas if f.proyecto_id == 55]
    assert ("ppa_venta_ungg", True) in de_55
    assert ("bolsa_compra_ungg", True) in de_55
    assert len(de_55) == 2
    de_99 = [(f.categoria, bool(f.uso_del_recurso)) for f in filas if f.proyecto_id == 99]
    assert de_99 == [("ppa_venta_ungg", False)]


def test_duplicado_clasico_no_cambia():
    """Regresión: el duplicado sigue clasificando SOLO en (c)."""
    from app.services.clasificacion_energia import derivar_pools, _filas_desde_pools
    data = _data_ur()
    data["venta"][0]["plantas"][0] = {**data["venta"][0]["plantas"][0],
                                      "es_duplicado": True, "uso_del_recurso": False}
    pools = derivar_pools(data)["pools"]
    filas = _filas_desde_pools(pools, 2026, 7)
    de_55 = [f.categoria for f in filas if f.proyecto_id == 55]
    assert de_55 == ["bolsa_compra_ungg"]
