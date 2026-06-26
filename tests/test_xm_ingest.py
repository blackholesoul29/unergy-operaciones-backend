"""Tests de XMIngestionService (lectura/normalización/validación de Excel XM).

No tocan la BD: `parse_rows` recibe el lookup de proyectos como dict y
`_read_rows` solo usa openpyxl. El upsert (on_conflict) depende de PostgreSQL y
se valida fuera de este suite.
"""
import io
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook

from app.services.xm_ingest_service import XMIngestionService, _norm


def _xlsx(headers, rows):
    """Construye un .xlsx en memoria y lo devuelve como BytesIO."""
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── normalización ───────────────────────────────────────────────────────────
def test_norm_strips_accents_and_punctuation():
    assert _norm("Generación (MWh)") == "generacion mwh"
    assert _norm(None) == ""


# ── detección flexible de columnas ────────────────────────────────────────────
def test_read_rows_detects_columns_by_alias():
    buf = _xlsx(
        ["Proyecto", "Medidor", "Fecha", "Generación MWh"],
        [["El Copey", "FRT123", "01/06/2026", 12.5]],
    )
    svc = XMIngestionService(db=None)
    rows, col_map = svc._read_rows(buf)
    assert rows == [{
        "proyecto": "El Copey", "meter_id": "FRT123",
        "fecha": "01/06/2026", "generacion": 12.5,
    }]
    assert set(col_map) == {"proyecto", "meter_id", "fecha", "generacion"}


def test_read_rows_requires_date_and_generation_columns():
    buf = _xlsx(["Proyecto", "Medidor"], [["El Copey", "FRT123"]])
    svc = XMIngestionService(db=None)
    try:
        svc._read_rows(buf)
        assert False, "debió lanzar ValueError"
    except ValueError as exc:
        assert "fecha" in str(exc) and "generacion" in str(exc)


# ── parsing de fechas y generación ────────────────────────────────────────────
def test_parse_fecha_ddmmyyyy_and_iso():
    assert XMIngestionService._parse_fecha("01/06/2026") == datetime(2026, 6, 1)
    assert XMIngestionService._parse_fecha("2026-06-01") == datetime(2026, 6, 1)
    assert XMIngestionService._parse_fecha(datetime(2026, 6, 1, 8)) == datetime(2026, 6, 1, 8)
    assert XMIngestionService._parse_fecha("no-fecha") is None
    assert XMIngestionService._parse_fecha("") is None


def test_parse_generacion_handles_separators():
    assert XMIngestionService._parse_generacion("1.234,56") == Decimal("1234.56")
    assert XMIngestionService._parse_generacion("12,5") == Decimal("12.5")
    assert XMIngestionService._parse_generacion(12.5) == Decimal("12.5")
    assert XMIngestionService._parse_generacion("abc") is None
    assert XMIngestionService._parse_generacion(None) is None


# ── validación fila por fila ──────────────────────────────────────────────────
def _svc():
    return XMIngestionService(db=None)


def test_parse_rows_valid_and_corrupt_split():
    lookup = {"el copey": 7}
    rows = [
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "01/06/2026", "generacion": 10},
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "fecha-mala", "generacion": 10},
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "02/06/2026", "generacion": None},
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "03/06/2026", "generacion": -5},
        {"proyecto": "Desconocido", "meter_id": "M1", "fecha": "04/06/2026", "generacion": 1},
        {"proyecto": "El Copey", "meter_id": "", "fecha": "05/06/2026", "generacion": 1},
    ]
    valid, errors = _svc().parse_rows(rows, lookup)
    assert len(valid) == 1
    assert valid[0]["proyecto_id"] == 7
    assert valid[0]["generation_mwh"] == Decimal("10")
    # cinco filas corruptas → cinco errores, cada uno con su número de fila
    assert len(errors) == 5
    assert any("fecha" in e for e in errors)
    assert any("generación" in e.lower() for e in errors)
    assert any("negativa" in e for e in errors)
    assert any("proyecto no reconocido" in e for e in errors)
    assert any("meter_id" in e for e in errors)


def test_parse_rows_explicit_proyecto_id_beats_name():
    rows = [{"proyecto_id": 42, "proyecto": "ignorado", "meter_id": "M1",
             "fecha": "01/06/2026", "generacion": 1}]
    valid, errors = _svc().parse_rows(rows, {})
    assert not errors
    assert valid[0]["proyecto_id"] == 42


def test_parse_rows_dedupes_keeping_last():
    lookup = {"el copey": 7}
    rows = [
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "01/06/2026", "generacion": 10},
        {"proyecto": "El Copey", "meter_id": "M1", "fecha": "01/06/2026", "generacion": 99},
    ]
    valid, errors = _svc().parse_rows(rows, lookup)
    assert len(valid) == 1
    assert valid[0]["generation_mwh"] == Decimal("99")
