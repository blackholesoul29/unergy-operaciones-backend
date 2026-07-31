"""Path-traversal en uploads de arriendos: periodo estricto, nombres saneados y
contención del directorio de destino (helpers + endpoint llamado directo con
sesión sqlite en memoria, mismo patrón que test_arr_arrendadores_crud)."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.arriendos import ArrDocumento
import app.api.v1.arriendos as arriendos_mod
from app.api.v1.arriendos import (
    _validar_periodo, _safe_segment, _sanit_nombre, _dir_seguro, _ext_segura,
    upload_documento,
)


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[ArrDocumento.__table__])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


class _FakeUpload:
    def __init__(self, filename="doc.pdf", contenido=b"%PDF-fake"):
        self.filename = filename
        self._contenido = contenido

    async def read(self):
        return self._contenido


# ---------- _validar_periodo ----------

@pytest.mark.parametrize("malo", [
    "../-01",        # el split("-") viejo lo dejaba pasar → escapaba _UPLOADS_DIR
    "..-12",
    "2026-13",
    "2026-00",
    "2026-1",
    "x/2026-01",
    "2026-01/../..",
    "2026-01\n",
    "",
])
def test_periodo_invalido_rechazado(malo):
    with pytest.raises(HTTPException) as e:
        _validar_periodo(malo)
    assert e.value.status_code == 400


@pytest.mark.parametrize("bueno", ["2026-01", "2026-07", "1999-12"])
def test_periodo_valido_pasa(bueno):
    _validar_periodo(bueno)  # no debe lanzar


# ---------- _safe_segment / _sanit_nombre ----------

def test_safe_segment_neutraliza_traversal():
    assert "/" not in _safe_segment("../../etc")
    assert ".." not in _safe_segment("../../etc")
    assert _safe_segment("..") == "sin_codigo"
    assert _safe_segment("") == "sin_codigo"
    assert _safe_segment("CT-2024\x00\x1f") == "CT-2024"


def test_sanit_nombre_neutraliza_traversal():
    assert _sanit_nombre("../../../etc/cron.d/evil", "fb") == "evil"
    assert _sanit_nombre("..", "fb") == "fb"
    assert _sanit_nombre("", "fb") == "fb"
    assert _sanit_nombre("..\\evil.pdf", "fb") == "evil.pdf"
    assert _sanit_nombre(".oculto.pdf", "fb") == "oculto.pdf"
    assert _sanit_nombre("cuenta enero.pdf", "fb") == "cuenta enero.pdf"


def test_ext_segura_filtra_chars_del_filename():
    assert _ext_segura("doc.pdf") == ".pdf"
    assert _ext_segura("x.pdf\x00") == ".pdf"          # null byte no llega al filesystem
    assert _ext_segura("a.b\\..\\evil") == ".evil"     # backslash filtrado: sin separadores
    assert _ext_segura(None) == ".pdf"
    assert _ext_segura("sin_extension") == ".pdf"
    assert _ext_segura("informe.XLSX") == ".XLSX"


# ---------- _dir_seguro ----------

def test_dir_seguro_contiene_dentro_de_uploads(tmp_path, monkeypatch):
    monkeypatch.setattr(arriendos_mod, "_UPLOADS_DIR", tmp_path / "uploads" / "arriendos")
    d = _dir_seguro("2026-07", "CT-001")
    assert d.is_relative_to((tmp_path / "uploads" / "arriendos").resolve())


def test_dir_seguro_bloquea_periodo_traversal(tmp_path, monkeypatch):
    # Defensa en profundidad: aunque un periodo malicioso llegara hasta aquí,
    # la contención tras resolve() lo bloquea.
    monkeypatch.setattr(arriendos_mod, "_UPLOADS_DIR", tmp_path / "uploads" / "arriendos")
    with pytest.raises(HTTPException) as e:
        _dir_seguro("../..", "CT-001")
    assert e.value.status_code == 400


# ---------- endpoint upload_documento ----------

def test_upload_rechaza_periodo_traversal(db, tmp_path, monkeypatch):
    monkeypatch.setattr(arriendos_mod, "_UPLOADS_DIR", tmp_path / "uploads" / "arriendos")
    with pytest.raises(HTTPException) as e:
        asyncio.run(upload_documento(
            arr_proyecto_id=1, periodo="../-01", pago_id=1,
            codigo_contrato="CT-001", tipo_documento="cuenta_cobro",
            nombre_resultante="cuenta.pdf", proyecto_id=None,
            file=_FakeUpload(), file_secundario=None, db=db, _=None,
        ))
    assert e.value.status_code == 400
    assert not (tmp_path / "uploads").exists() or not list((tmp_path / "uploads").rglob("*.pdf"))


def test_upload_nombre_resultante_traversal_queda_contenido(db, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads" / "arriendos"
    monkeypatch.setattr(arriendos_mod, "_UPLOADS_DIR", uploads)
    res = asyncio.run(upload_documento(
        arr_proyecto_id=1, periodo="2026-07", pago_id=1,
        codigo_contrato="CT-001", tipo_documento="cuenta_cobro",
        nombre_resultante="../../../../fuera.pdf", proyecto_id=None,
        file=_FakeUpload(), file_secundario=None, db=db, _=None,
    ))
    assert res["ok"] is True
    # Nada se escribió fuera del árbol de uploads…
    escritos = [p for p in tmp_path.rglob("*.pdf")]
    assert escritos, "el upload debió escribir el archivo"
    for p in escritos:
        assert p.resolve().is_relative_to(uploads.resolve())
    # …y el registro en BD apunta adentro con el nombre saneado.
    doc = db.query(ArrDocumento).first()
    assert doc.nombre_archivo == "fuera.pdf"


def test_upload_normal_sigue_funcionando(db, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads" / "arriendos"
    monkeypatch.setattr(arriendos_mod, "_UPLOADS_DIR", uploads)
    res = asyncio.run(upload_documento(
        arr_proyecto_id=1, periodo="2026-07", pago_id=2,
        codigo_contrato="CT-001", tipo_documento="cuenta_cobro",
        nombre_resultante="CT-001_2026-07_cuenta", proyecto_id=None,
        file=_FakeUpload(filename="original.pdf"), file_secundario=None, db=db, _=None,
    ))
    assert res["ok"] is True
    esperado = uploads / "2026-07" / "CT-001" / "CT-001_2026-07_cuenta.pdf"
    assert esperado.exists()
    assert esperado.read_bytes() == b"%PDF-fake"
