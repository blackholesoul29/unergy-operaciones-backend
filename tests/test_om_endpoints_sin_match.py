"""Tests de integración para la persistencia y asignación manual de páginas
sin match del split O&M (OMPaginaSinMatch). Harness sqlite; auth stubeado en
conftest, así que las funciones del router se llaman directamente."""
import asyncio
import types
from io import BytesIO

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.models.base import Base
import app.models  # noqa: F401 - registra todos los modelos para resolver relationships
from app.models.contratos import ContratoServicio
from app.models.om import OMFacturaMensual, OMDocumentoProyecto, OMPaginaSinMatch
from app.api.v1 import om as api
from app.schemas.om import OMSinMatchAsignar


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))
PERIODO = "2026-06"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ContratoServicio.__table__, OMFacturaMensual.__table__,
        OMDocumentoProyecto.__table__, OMPaginaSinMatch.__table__,
    ])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _pdf_con_texto(paginas_texto: list[str]) -> bytes:
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


class _FakeUploadFile:
    """Sustituto mínimo de fastapi.UploadFile — solo lo que usa el endpoint."""
    def __init__(self, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


def _crear_contrato(db, servicio_aplica="mantenimiento", prestador_nombre="Proyecto Test"):
    c = ContratoServicio(servicio_aplica=servicio_aplica, prestador_nombre=prestador_nombre)
    db.add(c)
    db.flush()
    return c


def _crear_factura(db, tmp_path, textos_paginas, periodo=PERIODO):
    ruta = tmp_path / f"{periodo}.pdf"
    ruta.write_bytes(_pdf_con_texto(textos_paginas))
    factura = OMFacturaMensual(periodo=periodo, nombre_archivo="factura.pdf", ruta_local=str(ruta))
    db.add(factura)
    db.flush()
    return factura, ruta


def _crear_sin_match(db, pagina=1, periodo=PERIODO, resuelto=False):
    s = OMPaginaSinMatch(
        periodo=periodo, pagina=pagina, razon="no_se_extrajo_nombre",
        nombre_extraido=None, resuelto=resuelto,
    )
    db.add(s)
    db.flush()
    return s


# ── PATCH /om/factura/{periodo}/sin-match/{id}/asignar ──────────────────────

def test_asignar_resuelve_pendiente_y_crea_documento(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    contrato = _crear_contrato(db)
    _crear_factura(db, tmp_path, ["Texto irreconocible sin proyecto SOLENIUM SAS"])
    sin_match = _crear_sin_match(db, pagina=1)

    resultado = api.asignar_sin_match(
        PERIODO, sin_match.id, OMSinMatchAsignar(contrato_id=contrato.id), db=db, _=ADMIN,
    )

    assert resultado["ok"] is True
    assert resultado["contrato_id"] == contrato.id

    db.refresh(sin_match)
    assert sin_match.resuelto is True
    assert sin_match.contrato_id_asignado == contrato.id

    doc = db.query(OMDocumentoProyecto).filter(
        OMDocumentoProyecto.contrato_id == contrato.id,
        OMDocumentoProyecto.periodo == PERIODO,
    ).first()
    assert doc is not None
    assert len(PdfReader(doc.ruta_local).pages) == 1


def test_asignar_anexa_pagina_a_documento_existente(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    contrato = _crear_contrato(db)
    _factura, ruta_pdf = _crear_factura(db, tmp_path, [
        "Mantenimiento Preventivo - Proyecto Test - Junio",
        "Texto irreconocible sin proyecto SOLENIUM SAS",
    ])
    # Simula que la página 1 ya se había asignado automáticamente (documento existente).
    ruta_doc = (tmp_path / "uploads_om" / "documentos" / PERIODO
                / f"SOFV_{contrato.prestador_nombre}_{PERIODO}_mantenimiento.pdf")
    ruta_doc.parent.mkdir(parents=True)
    ruta_doc.write_bytes(_pdf_con_texto(["Mantenimiento Preventivo - Proyecto Test - Junio"]))
    doc = OMDocumentoProyecto(
        contrato_id=contrato.id, periodo=PERIODO,
        nombre_archivo=ruta_doc.name, ruta_local=str(ruta_doc),
    )
    db.add(doc)
    sin_match = _crear_sin_match(db, pagina=2)
    db.flush()

    api.asignar_sin_match(PERIODO, sin_match.id, OMSinMatchAsignar(contrato_id=contrato.id), db=db, _=ADMIN)

    db.refresh(doc)
    assert len(PdfReader(doc.ruta_local).pages) == 2


def test_asignar_falla_si_ya_resuelto(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    contrato = _crear_contrato(db)
    _crear_factura(db, tmp_path, ["texto"])
    sin_match = _crear_sin_match(db, pagina=1, resuelto=True)

    with pytest.raises(Exception) as exc_info:
        api.asignar_sin_match(PERIODO, sin_match.id, OMSinMatchAsignar(contrato_id=contrato.id), db=db, _=ADMIN)
    assert exc_info.value.status_code == 400


def test_asignar_falla_si_contrato_no_es_mantenimiento(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    contrato_arriendo = _crear_contrato(db, servicio_aplica="arriendo")
    _crear_factura(db, tmp_path, ["texto"])
    sin_match = _crear_sin_match(db, pagina=1)

    with pytest.raises(Exception) as exc_info:
        api.asignar_sin_match(PERIODO, sin_match.id, OMSinMatchAsignar(contrato_id=contrato_arriendo.id), db=db, _=ADMIN)
    assert exc_info.value.status_code == 404


def test_asignar_falla_si_no_hay_pdf_original(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    contrato = _crear_contrato(db)
    sin_match = _crear_sin_match(db, pagina=1)  # sin OMFacturaMensual creada

    with pytest.raises(Exception) as exc_info:
        api.asignar_sin_match(PERIODO, sin_match.id, OMSinMatchAsignar(contrato_id=contrato.id), db=db, _=ADMIN)
    assert exc_info.value.status_code == 404


# ── Re-upload invalida los sin_match viejos del período ─────────────────────

def test_reupload_borra_sin_match_viejos_del_periodo(db, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "_UPLOADS_DIR", tmp_path / "uploads_om")
    _crear_contrato(db, prestador_nombre="Uruaco")
    _crear_sin_match(db, pagina=7)  # sin_match "viejo" de una subida anterior

    fake_file = _FakeUploadFile(
        "factura.pdf",
        _pdf_con_texto(["Texto irreconocible sin proyecto SOLENIUM SAS"]),
    )
    asyncio.run(api.upload_factura_mensual(PERIODO, file=fake_file, db=db, _=ADMIN))

    pendientes = db.query(OMPaginaSinMatch).filter(OMPaginaSinMatch.periodo == PERIODO).all()
    # El viejo (página 7) ya no existe; el nuevo split solo generó 1 página sin match.
    assert len(pendientes) == 1
    assert pendientes[0].pagina == 1
    assert pendientes[0].origen == "upload"
