"""Tests del pipeline de ingesta de datos XM.

Unit: normalización de encabezados, coerción numérica/fecha, hash de fila y
`parse_dataframe`. Integración: CRUD sobre sqlite (dedup por hash, filtros,
status) y `process_xm_file` de punta a punta leyendo un .xlsx temporal.
"""
import datetime as dt
import os
import tempfile

import pandas as pd
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.models.liquidacion_xm import LiquidacionXMDatoIngesta
from app.crud import crud_liquidacion_xm
from app.schemas.liquidacion_xm import LiquidacionXMDatoCreate
from app.services import xm_ingestion_service as svc


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):  # noqa: D401
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[LiquidacionXMDatoIngesta.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── unit: helpers ────────────────────────────────────────────────────────────

def test_normalizar_header():
    assert svc.normalizar_header("Código del Recurso") == "codigo_del_recurso"
    assert svc.normalizar_header("  Generación (kWh) ") == "generacion_kwh"
    assert svc.normalizar_header("CEN-MW") == "cen_mw"


def test_to_float_formatos():
    assert svc.to_float("1234.56") == pytest.approx(1234.56)
    assert svc.to_float("1.234,56") == pytest.approx(1234.56)   # es-CO
    assert svc.to_float("1234,56") == pytest.approx(1234.56)
    assert svc.to_float("$ 1.000,50") == pytest.approx(1000.50)
    assert svc.to_float(42) == 42.0
    assert svc.to_float("") is None
    assert svc.to_float("n/a") is None
    assert svc.to_float(None) is None


def test_to_date():
    assert svc.to_date("2026-07-11") == dt.date(2026, 7, 11)
    assert svc.to_date("11/07/2026") == dt.date(2026, 7, 11)  # dayfirst
    assert svc.to_date(dt.date(2026, 1, 1)) == dt.date(2026, 1, 1)
    assert svc.to_date("no-es-fecha") is None


def test_compute_row_hash_es_consistente_y_sensible():
    base = dict(
        fuente_archivo="generacion_distribuida.xlsx",
        codigo_recurso="ABC1",
        fecha=dt.date(2026, 7, 11),
        generacion_kwh=100.0,
        precio_liquidacion_cop_kwh=250.0,
        valor_liquidacion_cop=25000.0,
    )
    h1 = svc.compute_row_hash(**base)
    h2 = svc.compute_row_hash(**base)
    assert h1 == h2                       # determinista
    assert len(h1) == 64                  # sha256 hex
    # normalización de código (mayúsc/espacios) no cambia el hash
    assert svc.compute_row_hash(**{**base, "codigo_recurso": " abc1 "}) == h1
    # cambiar generación cambia el hash
    assert svc.compute_row_hash(**{**base, "generacion_kwh": 101.0}) != h1


# ── unit: parse_dataframe ────────────────────────────────────────────────────

def test_parse_dataframe_generacion():
    df = pd.DataFrame([
        {"Código Recurso": "REC1", "Fecha": "2026-07-11",
         "Generación kWh": "1.000,50", "Precio Liquidación": "250,00",
         "Valor Liquidación": "250.125,00", "Agente": "AGX", "Tipo Recurso": "Solar"},
    ])
    datos, errores = svc.parse_dataframe(df, svc.FILE_TYPE_GENERACION, "generacion_distribuida.xlsx")
    assert errores == []
    assert len(datos) == 1
    d = datos[0]
    assert d.codigo_recurso == "REC1"
    assert d.fecha == dt.date(2026, 7, 11)
    assert d.generacion_kwh == pytest.approx(1000.50)
    assert d.valor_liquidacion_cop == pytest.approx(250125.00)
    assert d.agente == "AGX"
    assert len(d.hash_fila) == 64


def test_parse_dataframe_usa_fecha_default_si_falta_columna():
    df = pd.DataFrame([
        {"Codigo": "REC9", "Agente": "A", "Capacidad Efectiva Neta": "5,5"},
    ])
    hoy = dt.date(2026, 7, 11)
    datos, errores = svc.parse_dataframe(
        df, svc.FILE_TYPE_LISTADO, "listado_recursos.xlsx", fecha_default=hoy
    )
    assert errores == []
    assert datos[0].fecha == hoy
    assert datos[0].capacidad_efectiva_neta_mw == pytest.approx(5.5)


def test_parse_dataframe_sin_codigo_es_fatal():
    df = pd.DataFrame([{"Fecha": "2026-07-11", "Generación kWh": "10"}])
    with pytest.raises(ValueError):
        svc.parse_dataframe(df, svc.FILE_TYPE_GENERACION, "x.xlsx")


def test_parse_dataframe_file_type_invalido():
    df = pd.DataFrame([{"Codigo": "R1"}])
    with pytest.raises(ValueError):
        svc.parse_dataframe(df, "no_existe", "x.xlsx")


def test_parse_dataframe_fila_sin_fecha_se_reporta_no_aborta():
    df = pd.DataFrame([
        {"Codigo": "R1", "Fecha": "basura", "Generación kWh": "10"},
        {"Codigo": "R2", "Fecha": "2026-07-11", "Generación kWh": "20"},
    ])
    datos, errores = svc.parse_dataframe(df, svc.FILE_TYPE_GENERACION, "x.xlsx")
    assert len(datos) == 1        # solo R2 se pudo parsear
    assert len(errores) == 1
    assert datos[0].codigo_recurso == "R2"


# ── integración: CRUD ────────────────────────────────────────────────────────

def _mk(hash_fila, codigo="R1", fecha=dt.date(2026, 7, 11), gen=10.0):
    return LiquidacionXMDatoCreate(
        codigo_recurso=codigo, fecha=fecha, generacion_kwh=gen,
        fuente_archivo="f.xlsx", hash_fila=hash_fila,
    )


def test_create_multiple_deduplica(db):
    n = crud_liquidacion_xm.create_multiple(db, [_mk("h1"), _mk("h2"), _mk("h1")])
    assert n == 2  # h1 duplicado dentro del lote se ignora
    n2 = crud_liquidacion_xm.create_multiple(db, [_mk("h1"), _mk("h3")])
    assert n2 == 1  # h1 ya existe en BD
    assert db.query(LiquidacionXMDatoIngesta).count() == 3


def test_get_existing_hashes(db):
    crud_liquidacion_xm.create_multiple(db, [_mk("h1"), _mk("h2")])
    assert crud_liquidacion_xm.get_existing_hashes(db, ["h1", "h2", "h9"]) == {"h1", "h2"}


def test_get_filtered_por_fecha_y_recurso(db):
    crud_liquidacion_xm.create_multiple(db, [
        _mk("a", codigo="R1", fecha=dt.date(2026, 7, 1)),
        _mk("b", codigo="R1", fecha=dt.date(2026, 7, 15)),
        _mk("c", codigo="R2", fecha=dt.date(2026, 7, 15)),
    ])
    items, total = crud_liquidacion_xm.get_filtered(db, codigo_recurso="R1")
    assert total == 2
    items, total = crud_liquidacion_xm.get_filtered(
        db, start_date=dt.date(2026, 7, 10), end_date=dt.date(2026, 7, 20)
    )
    assert total == 2
    items, total = crud_liquidacion_xm.get_filtered(db, limit=1)
    assert total == 3 and len(items) == 1  # paginación


def test_get_status(db):
    assert crud_liquidacion_xm.get_status(db)["total_registros"] == 0
    crud_liquidacion_xm.create_multiple(db, [_mk("h1")])
    st = crud_liquidacion_xm.get_status(db)
    assert st["total_registros"] == 1
    assert st["fuente_archivo"] == "f.xlsx"
    assert st["ultima_ingesta"] is not None


# ── integración: process_xm_file de punta a punta ────────────────────────────

def test_process_xm_file_end_to_end(db):
    df = pd.DataFrame([
        {"Codigo Recurso": "REC1", "Fecha": "2026-07-11", "Generacion kWh": 100,
         "Precio Liquidacion": 250, "Valor Liquidacion": 25000},
        {"Codigo Recurso": "REC2", "Fecha": "2026-07-11", "Generacion kWh": 200,
         "Precio Liquidacion": 250, "Valor Liquidacion": 50000},
    ])
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_generacion_distribuida.xlsx")
    tmp.close()
    try:
        df.to_excel(tmp.name, index=False, engine="openpyxl")
        r1 = svc.process_xm_file(db, tmp.name)  # tipo inferido del nombre
        assert r1["file_type"] == svc.FILE_TYPE_GENERACION
        assert r1["filas_leidas"] == 2
        assert r1["filas_nuevas"] == 2
        # reprocesar el mismo archivo no inserta nada nuevo (idempotente)
        r2 = svc.process_xm_file(db, tmp.name)
        assert r2["filas_nuevas"] == 0
        assert r2["filas_duplicadas"] == 2
        assert db.query(LiquidacionXMDatoIngesta).count() == 2
    finally:
        os.unlink(tmp.name)
