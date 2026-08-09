"""Tests del backfill histórico de páginas sin match (om_backfill_sin_match).
Harness sqlite, mismo patrón que test_om_endpoints_sin_match.py."""
import types
from io import BytesIO

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.om import OMFacturaMensual, OMPaginaSinMatch
from app.services.om_backfill_sin_match import backfill_sin_match


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


def _pdf_con_texto(paginas_texto):
    writer = PdfWriter()
    for texto in paginas_texto:
        page = writer.add_blank_page(width=612, height=792)
        content = f"BT /F1 12 Tf 50 700 Td ({texto}) Tj ET".encode("latin-1")
        stream = DecodedStreamObject()
        stream.set_data(content)
        stream_ref = writer._add_object(stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Contents")] = stream_ref
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ContratoServicio.__table__, OMFacturaMensual.__table__, OMPaginaSinMatch.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_dry_run_no_escribe_nada(db, tmp_path):
    ruta = tmp_path / "2026-01.pdf"
    ruta.write_bytes(_pdf_con_texto(["Texto irreconocible sin proyecto SOLENIUM SAS"]))
    db.add(OMFacturaMensual(periodo="2026-01", ruta_local=str(ruta)))
    db.flush()

    res = backfill_sin_match(db, apply=False)

    assert res["periodos_revisados"] == ["2026-01"]
    assert len(res["nuevos_sin_match"]) == 1
    assert db.query(OMPaginaSinMatch).count() == 0  # dry-run: nada persistido


def test_apply_persiste_con_origen_backfill(db, tmp_path):
    ruta = tmp_path / "2026-01.pdf"
    ruta.write_bytes(_pdf_con_texto(["Texto irreconocible sin proyecto SOLENIUM SAS"]))
    db.add(OMFacturaMensual(periodo="2026-01", ruta_local=str(ruta)))
    db.flush()

    backfill_sin_match(db, apply=True)

    filas = db.query(OMPaginaSinMatch).filter(OMPaginaSinMatch.periodo == "2026-01").all()
    assert len(filas) == 1
    assert filas[0].origen == "backfill"


def test_salta_periodos_que_ya_tienen_sin_match(db, tmp_path):
    ruta = tmp_path / "2026-01.pdf"
    ruta.write_bytes(_pdf_con_texto(["Texto irreconocible sin proyecto SOLENIUM SAS"]))
    db.add(OMFacturaMensual(periodo="2026-01", ruta_local=str(ruta)))
    db.add(OMPaginaSinMatch(periodo="2026-01", pagina=1, razon="ya_registrado", origen="upload"))
    db.flush()

    res = backfill_sin_match(db, apply=True)

    assert res["periodos_saltados_ya_tenian"] == ["2026-01"]
    assert res["periodos_revisados"] == []
    # No se duplica la fila existente
    assert db.query(OMPaginaSinMatch).filter(OMPaginaSinMatch.periodo == "2026-01").count() == 1


def test_reporta_periodos_sin_archivo_en_disco(db, tmp_path):
    ruta_inexistente = tmp_path / "no-existe.pdf"
    db.add(OMFacturaMensual(periodo="2026-02", ruta_local=str(ruta_inexistente)))
    db.flush()

    res = backfill_sin_match(db, apply=True)

    assert res["periodos_sin_archivo"] == ["2026-02"]
    assert res["periodos_revisados"] == []
