"""documento_disponible refleja la EXISTENCIA física del archivo, no solo el
registro en BD (un archivo perdido no debe mostrar ícono de descarga)."""
import types
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.contratos import ContratoServicio
from app.models.proyectos import Proyecto
from app.models.om import IPCTasa, OMSeleccion, OMDocumentoProyecto
from app.api.v1 import om as api


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, ContratoServicio.__table__, IPCTasa.__table__,
        OMSeleccion.__table__, OMDocumentoProyecto.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _setup(db):
    p = Proyecto(nombre_comercial="Alpha", estado="en_operacion", tipo_proyecto="minigranja")
    db.add(p); db.flush()
    c = ContratoServicio(servicio_aplica="mantenimiento", proyecto_id=p.id, estado="vigente",
                         tarifa_base=12_000_000, fecha_inicio_om=date(2020, 1, 1),
                         periodicidad_pago="mensual")
    db.add(c); db.flush()
    return c


def test_documento_no_disponible_si_archivo_no_existe(db):
    c = _setup(db)
    db.add(OMDocumentoProyecto(contrato_id=c.id, periodo="2026-06",
                               nombre_archivo="x.pdf", ruta_local="/ruta/inexistente/x.pdf"))
    db.flush()
    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.contrato_id == c.id)
    assert fila.documento_disponible is False


def test_documento_disponible_si_archivo_existe(db, tmp_path):
    c = _setup(db)
    archivo = tmp_path / "x.pdf"
    archivo.write_bytes(b"%PDF-1.4 test")
    db.add(OMDocumentoProyecto(contrato_id=c.id, periodo="2026-06",
                               nombre_archivo="x.pdf", ruta_local=str(archivo)))
    db.flush()
    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.contrato_id == c.id)
    assert fila.documento_disponible is True
