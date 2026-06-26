"""Tests del parseo del MEMIngestionService (funciones puras, sin BD)."""
import io
from datetime import date

import pytest

from app.services.mem_ingestion_service import (
    parse_tabular, _parse_date, _parse_float, _norm_header, _canonical,
)


def test_parse_csv_asic_canonical_headers():
    csv = (
        b"codigo_asic,fecha,hora,generacion_kwh,fuente\n"
        b"FRT001,2026-06-01,0,123.5,ASIC\n"
        b"FRT001,2026-06-01,1,130.0,ASIC\n"
    )
    rows = parse_tabular(csv, "gen.csv")
    assert len(rows) == 2
    assert rows[0]["codigo_asic"] == "FRT001"
    assert rows[0]["generacion_kwh"] == "123.5"
    assert rows[1]["hora"] == "1"


def test_parse_csv_with_semicolon_and_aliases():
    # encabezados con acentos / sinónimos y delimitador ';'
    csv = "código;hora;energia_kwh\nFRT9;5;10,5\n".encode("utf-8")
    rows = parse_tabular(csv, "x.csv")
    assert rows == [{"codigo_asic": "FRT9", "hora": "5", "generacion_kwh": "10,5"}]


def test_parse_csv_prices():
    csv = b"fecha,hora,precio_cop_kwh\n2026-06-01,0,250.75\n"
    rows = parse_tabular(csv, "precios.csv")
    assert rows[0]["fecha"] == "2026-06-01"
    assert rows[0]["precio_cop_kwh"] == "250.75"


def test_parse_skips_blank_rows():
    csv = b"codigo_asic,fecha,hora,generacion_kwh\nFRT1,2026-06-01,0,1\n,,,\n"
    rows = parse_tabular(csv, "x.csv")
    assert len(rows) == 1


def test_parse_xlsx_roundtrip():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["codigo_asic", "fecha", "hora", "generacion_kwh"])
    ws.append(["FRT001", "2026-06-01", 0, 123.5])
    buf = io.BytesIO()
    wb.save(buf)
    rows = parse_tabular(buf.getvalue(), "gen.xlsx")
    assert rows[0]["codigo_asic"] == "FRT001"
    assert rows[0]["hora"] == 0
    assert rows[0]["generacion_kwh"] == 123.5


def test_parse_empty_file_returns_empty():
    assert parse_tabular(b"", "x.csv") == []


def test_parse_date_formats():
    assert _parse_date("2026-06-01") == date(2026, 6, 1)
    assert _parse_date("01/06/2026") == date(2026, 6, 1)
    assert _parse_date(date(2026, 6, 1)) == date(2026, 6, 1)


def test_parse_float_us_format():
    # Formato US: punto decimal, coma de miles.
    assert _parse_float("1,234.5") == 1234.5
    assert _parse_float("1,234,567") == 1234567.0
    assert _parse_float("10") == 10.0
    assert _parse_float("250.75") == 250.75


def test_parse_float_colombian_decimal_comma():
    # Formato colombiano/XM: coma = separador DECIMAL (no de miles). Tratarla como
    # miles inflaba la magnitud (230,5 → 2305 = 10×) — misma clase del bug kWh/MWh.
    assert _parse_float("230,5") == 230.5
    assert _parse_float("1.234,75") == 1234.75
    assert _parse_float("0,001") == 0.001
    # Numérico nativo (xlsx data_only) pasa sin tocar.
    assert _parse_float(123.5) == 123.5
    assert _parse_float(10) == 10.0


def test_parse_float_rejects_empty():
    with pytest.raises(ValueError):
        _parse_float("")
    with pytest.raises(ValueError):
        _parse_float("   ")


def test_norm_header_and_canonical():
    assert _norm_header(" Generación KWH ") == "generacion_kwh"
    assert _canonical("mpo") == "precio_cop_kwh"
    assert _canonical("desconocido") is None
