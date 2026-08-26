"""Normalización de texto, fechas y versiones para el Modelo Predictivo.

Los tres casos de fecha y el de SEPT salen del corpus real: si el matcher no los
cubre, pierde archivos sin lanzar error.
"""
import datetime

from app.services.garantias_modelo.normalizar import (
    coincide_concepto,
    fecha_de_nombre,
    normalizar_concepto,
    orden_version,
    version_de_nombre,
)


def test_normalizar_concepto_quita_tildes_y_mayusculas():
    assert normalizar_concepto("Generación Kw") == "generacion kw"
    assert normalizar_concepto("  PÉRDIDAS  ASIGNADAS ") == "perdidas asignadas"


def test_normalizar_concepto_borra_el_mojibake_pero_pierde_la_vocal():
    # 6 de los 725 CSV de CGM llegan así. La doble codificación DESTRUYE el carácter
    # acentuado: ninguna normalización lo recupera. Se documenta el hecho.
    assert normalizar_concepto("Generaciï¿½n Kw") == "generacin kw"
    assert normalizar_concepto("Generación Kw") == "generacion kw"


def test_coincide_concepto_reconoce_el_mojibake():
    # Por eso el match no es por igualdad: la forma corrupta es una SUBSECUENCIA de la
    # limpia, porque al mojibake le faltan caracteres y no le sobran.
    assert coincide_concepto("Generaciï¿½n Kw", "Generación Kw")
    assert coincide_concepto("Generación Kw", "Generación Kw")


def test_coincide_concepto_no_confunde_conceptos_distintos():
    assert not coincide_concepto("Compras Kw", "Ventas Kw")
    assert not coincide_concepto("Generación Kw", "Demanda Kw")


def test_fecha_de_nombre_formato_ddmmm():
    assert fecha_de_nombre("GARANTIA SEMANAL MENSUAL 02ENE-2026.xlsx") == datetime.date(2026, 1, 2)


def test_fecha_de_nombre_formato_iso():
    assert fecha_de_nombre("GARANTIA SEMANAL MENSUAL 2026-05-01.xlsx") == datetime.date(2026, 5, 1)


def test_fecha_de_nombre_sept_de_cuatro_letras():
    assert fecha_de_nombre("GARANTIA MENSUAL 19SEPT-2025.XLSX") == datetime.date(2025, 9, 19)


def test_fecha_de_nombre_devuelve_none_si_no_hay_fecha():
    assert fecha_de_nombre("garantias_hoja_madre_formato.xlsx") is None


def test_version_de_nombre():
    assert version_de_nombre("BalCttos0101.tx2") == "tx2"
    assert version_de_nombre("trsd0101.TX1") == "tx1"
    assert version_de_nombre("arrpas0101.txf") == "txf"
    assert version_de_nombre("algo.xlsx") is None


def test_orden_version_es_creciente():
    assert orden_version("tx1") < orden_version("tx2") < orden_version("txr") < orden_version("txf")


def test_orden_version_desconocida_va_al_final():
    assert orden_version("zzz") > orden_version("txf")
