"""Tests del reparto por porcentaje y del mensaje de facturación.

El mensaje se pega tal cual en las facturas, así que el formato se fija con un
test de string exacto: cualquier cambio de espacios, separadores o decimales
tiene que ser deliberado.
"""
from datetime import date

import pytest

from app.services.facturacion_factura import construir_mensaje, contribuciones


# ── Reparto por porcentaje ──────────────────────────────────────────────────────
def test_sin_agrupacion_todo_al_ppa():
    assert contribuciones(None, "Terpel 1") == [("Terpel 1", 1.0, None)]


def test_agrupacion_total_mueve_el_contrato_completo():
    """porcentaje NULL = el contrato entero se mueve a la factura nombrada."""
    assert contribuciones(("Terpel 2 Unergy", None), "Terpel 2") == [
        ("Terpel 2 Unergy", 1.0, None)
    ]


def test_agrupacion_parcial_reparte_uruaco():
    """El caso real: Uruaco 78596 → 22.8066% a "Terpel 1 Suno", el resto en Terpel 1."""
    r = contribuciones(("Terpel 1 Suno", 22.8066), "Terpel 1")
    assert len(r) == 2
    (n1, f1, p1), (n2, f2, p2) = r
    assert (n1, p1) == ("Terpel 1 Suno", 22.8066)
    assert (n2, p2) == ("Terpel 1", 77.1934)
    assert f1 == pytest.approx(0.228066)
    assert f2 == pytest.approx(0.771934)
    assert f1 + f2 == pytest.approx(1.0)


def test_porcentaje_100_no_parte_nada():
    """100% es equivalente a mover el contrato entero: una sola contribución."""
    assert contribuciones(("Otra", 100), "Terpel 1") == [("Otra", 1.0, None)]


def test_porcentaje_cero_se_ignora():
    assert contribuciones(("Otra", 0), "Terpel 1") == [("Otra", 1.0, None)]


def test_nombre_de_factura_vacio_cae_al_ppa():
    assert contribuciones(("", None), "Terpel 1") == [("Terpel 1", 1.0, None)]


def test_no_revienta_si_la_entrada_es_un_string():
    """Regresión: `agrup` se cargaba como {codigo: nombre} (string) mientras el
    consumidor esperaba tuplas, y `0 < a[1] < 100` lanzaba TypeError comparando
    int con la segunda letra del nombre. Un string se trata como nombre sin %."""
    assert contribuciones("Terpel 2 Unergy", "Terpel 2") == [
        ("Terpel 2 Unergy", 1.0, None)
    ]


# ── Mensaje de facturación ──────────────────────────────────────────────────────
MENSAJE_TERPEL_4 = """OM-UNERGY-012-2025
Periodo: 01/6/2026 a 30/6/2026
Energía suministrada: 513,732.38 kWh


La información utilizada para la facturación de la energía fue extraída de los archivos TXF.
Contrato: 88770, 89339

Tarifa Base: $ 325
IPP Base agosto 2024 Provisional: $ 177.83
IPP junio 2026- Provisional: $ 187.43
Indexación: 1.054
Tarifa Actualizada: $ 342.54"""


def test_mensaje_replica_el_formato_de_terpel_4():
    """Caso tomado del Excel de junio 2026 (fila Terpel 4)."""
    assert construir_mensaje(
        numeros_contrato=["OM-UNERGY-012-2025"],
        periodo="2026-06",
        kwh=513732.38,
        contratos_sic=["88770", "89339"],
        tarifa_base=325.0,
        ipp_base=177.83,
        periodo_ipp_base="2024-08",
        ipp_mes=187.43,
    ) == MENSAJE_TERPEL_4


def test_indexacion_y_tarifa_actualizada_se_calculan():
    """No se pasan: se derivan de ipp_mes/ipp_base y tarifa_base, igual que el
    resto del pipeline (indexación a 3 decimales, tarifa a 2)."""
    m = construir_mensaje(
        numeros_contrato=["X"], periodo="2026-06", kwh=1000,
        contratos_sic=["1"], tarifa_base=322.9, ipp_base=177.68,
        periodo_ipp_base="2024-08", ipp_mes=187.43,
    )
    assert "Indexación: 1.055" in m
    assert "Tarifa Actualizada: $ 340.62" in m


def test_ultimo_dia_del_mes_sale_del_calendario():
    """Febrero de año bisiesto: 29, no 28 ni 30."""
    m = construir_mensaje(
        numeros_contrato=["X"], periodo="2024-02", kwh=1,
        contratos_sic=["1"], tarifa_base=100, ipp_base=100,
        periodo_ipp_base="2024-01", ipp_mes=100,
    )
    assert "Periodo: 01/2/2024 a 29/2/2024" in m


def test_varios_numeros_de_contrato_se_listan():
    m = construir_mensaje(
        numeros_contrato=["OM-A", "OM-B"], periodo="2026-06", kwh=1,
        contratos_sic=["1"], tarifa_base=100, ipp_base=100,
        periodo_ipp_base="2024-08", ipp_mes=100,
    )
    assert m.startswith("OM-A, OM-B\n")


def test_tarifa_entera_no_muestra_decimales_y_decimal_si():
    """En el mensaje real la base es "$ 325", no "$ 325.00"."""
    base = dict(numeros_contrato=["X"], periodo="2026-06", kwh=1, contratos_sic=["1"],
                ipp_base=100, periodo_ipp_base="2024-08", ipp_mes=100)
    assert "Tarifa Base: $ 325\n" in construir_mensaje(tarifa_base=325.0, **base)
    assert "Tarifa Base: $ 322.9\n" in construir_mensaje(tarifa_base=322.9, **base)


def test_sin_ipp_base_no_inventa_indexacion():
    """Si falta el IPP base no se puede indexar: el mensaje lo dice en vez de
    mostrar un número inventado."""
    m = construir_mensaje(
        numeros_contrato=["X"], periodo="2026-06", kwh=1, contratos_sic=["1"],
        tarifa_base=325, ipp_base=None, periodo_ipp_base=None, ipp_mes=187.43,
    )
    assert "Indexación: —" in m
    assert "Tarifa Actualizada: —" in m


def test_mes_del_ipp_base_en_espanol():
    m = construir_mensaje(
        numeros_contrato=["X"], periodo="2026-06", kwh=1, contratos_sic=["1"],
        tarifa_base=100, ipp_base=100, periodo_ipp_base="2025-12", ipp_mes=100,
    )
    assert "IPP Base diciembre 2025 Provisional:" in m
