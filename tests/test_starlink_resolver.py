"""Tests del resolver puro sitio Starlink → proyecto (sin DB)."""
from app.services.starlink_resolver import normalizar_sitio, resolver_lineas


def test_normalizar_quita_acentos_y_colapsa():
    assert normalizar_sitio("Cañahuate") == "CANAHUATE"
    assert normalizar_sitio("  el   molino ") == "EL MOLINO"
    assert normalizar_sitio(None) == ""


def test_resuelve_por_nombre_normalizado():
    agrupado = [{"descripcion": "Gandalf", "sin_iva": 100.0, "iva": 19.0, "monto_total": 119.0}]
    mapeos = [{"patron": "GANDALF", "proyecto_id": 7}]
    lineas = resolver_lineas(agrupado, mapeos)
    assert len(lineas) == 1
    assert lineas[0]["proyecto_id"] == 7
    assert lineas[0]["sin_iva"] == 100.0
    assert lineas[0]["descripcion"] == "Gandalf"


def test_sin_match_proyecto_none():
    agrupado = [{"descripcion": "NESTLE", "sin_iva": 50.0, "iva": 9.5, "monto_total": 59.5}]
    lineas = resolver_lineas(agrupado, [])
    assert lineas[0]["proyecto_id"] is None


def test_match_ignora_acentos_del_patron():
    agrupado = [{"descripcion": "CAÑAHUATE", "sin_iva": 10.0, "iva": 1.9, "monto_total": 11.9}]
    mapeos = [{"patron": "Cañahuate", "proyecto_id": 3}]
    assert resolver_lineas(agrupado, mapeos)[0]["proyecto_id"] == 3


def test_una_linea_por_entrada_del_agrupado():
    agrupado = [
        {"descripcion": "Gandalf", "sin_iva": 1, "iva": 0, "monto_total": 1},
        {"descripcion": "Cañahuate", "sin_iva": 2, "iva": 0, "monto_total": 2},
    ]
    lineas = resolver_lineas(agrupado, [{"patron": "GANDALF", "proyecto_id": 7}])
    assert len(lineas) == 2
    assert [l["proyecto_id"] for l in lineas] == [7, None]


def test_campos_none_se_normalizan_a_cero():
    agrupado = [{"descripcion": "Baraya", "sin_iva": None, "iva": None, "monto_total": None}]
    linea = resolver_lineas(agrupado, [])[0]
    assert linea["sin_iva"] == 0.0 and linea["iva"] == 0.0 and linea["monto_total"] == 0.0
