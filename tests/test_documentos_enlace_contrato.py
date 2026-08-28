"""ContratoServicio.enlace_drive y PPAContrato.carpeta_link -- generalizacion
2026-08-28 (auditoria de Clientes). Las columnas se eliminaron (migracion 122);
ahora son un @property de solo lectura respaldado por una fila tipo='contrato'
en cliente_documentos_comerciales, escrita via
app/services/documentos.set_enlace_documento. El nombre de campo en la API
(ContratoServicioOut.enlace_drive / PPAContratoOut.carpeta_link) no cambia --
estas pruebas verifican que ese passthrough sigue funcionando end-to-end.
"""
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.clientes import ClienteDocumentoComercial
from app.models.contratos import ContratoServicio, PPAContrato
from app.schemas.contratos_servicio import ContratoServicioCreate, ContratoServicioUpdate
from app.schemas.ppa import PPAContratoCreate, PPAContratoUpdate
from app.api.v1 import contratos_servicio as cs_api
from app.api.v1 import ppa as ppa_api
from app.services.documentos import set_enlace_documento


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


ADMIN = None
_ids = iter(range(1, 100_000))


def _contrato(db, **kw):
    kw.setdefault("id", next(_ids))
    kw.setdefault("servicio_aplica", "mantenimiento")
    c = ContratoServicio(**kw)
    db.add(c)
    db.commit()
    return c


def _ppa(db, **kw):
    kw.setdefault("id", next(_ids))
    p = PPAContrato(**kw)
    db.add(p)
    db.commit()
    return p


# ── set_enlace_documento (servicio compartido) ───────────────────────────────

def test_set_enlace_documento_crea_documento_nuevo(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/x", nombre="Enlace")
    db.commit()

    docs = db.query(ClienteDocumentoComercial).filter_by(contrato_servicio_id=c.id).all()
    assert len(docs) == 1
    assert docs[0].tipo == "contrato"
    assert docs[0].archivo_url == "https://drive/x"
    assert docs[0].cliente_id is None
    assert docs[0].ppa_contrato_id is None


def test_set_enlace_documento_actualiza_sin_duplicar(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/viejo", nombre="Enlace")
    db.commit()
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/nuevo", nombre="Enlace")
    db.commit()

    docs = db.query(ClienteDocumentoComercial).filter_by(contrato_servicio_id=c.id).all()
    assert len(docs) == 1
    assert docs[0].archivo_url == "https://drive/nuevo"


def test_set_enlace_documento_url_vacia_borra(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/x", nombre="Enlace")
    db.commit()
    set_enlace_documento(db, contrato_servicio_id=c.id, url="", nombre="Enlace")
    db.commit()

    assert db.query(ClienteDocumentoComercial).filter_by(contrato_servicio_id=c.id).count() == 0


def test_set_enlace_documento_ppa(db):
    p = _ppa(db)
    set_enlace_documento(db, ppa_contrato_id=p.id, url="https://drive/ppa", nombre="Enlace")
    db.commit()

    docs = db.query(ClienteDocumentoComercial).filter_by(ppa_contrato_id=p.id).all()
    assert len(docs) == 1
    assert docs[0].archivo_url == "https://drive/ppa"
    assert docs[0].cliente_id is None
    assert docs[0].contrato_servicio_id is None


def test_set_enlace_documento_exige_un_solo_dueno(db):
    with pytest.raises(AssertionError):
        set_enlace_documento(db, url="https://drive/x", nombre="Enlace")
    with pytest.raises(AssertionError):
        set_enlace_documento(db, contrato_servicio_id=1, ppa_contrato_id=2,
                              url="https://drive/x", nombre="Enlace")


# ── @property de solo lectura en los modelos ─────────────────────────────────

def test_contrato_servicio_enlace_drive_property_sin_documento(db):
    c = _contrato(db)
    assert c.enlace_drive is None


def test_contrato_servicio_enlace_drive_property_lee_documento(db):
    c = _contrato(db)
    db.add(ClienteDocumentoComercial(contrato_servicio_id=c.id, tipo="contrato",
                                      nombre="Enlace", estado="firmado",
                                      archivo_url="https://drive/y"))
    db.commit()
    db.expire_all()

    assert db.get(ContratoServicio, c.id).enlace_drive == "https://drive/y"


def test_ppa_contrato_carpeta_link_property_lee_documento(db):
    p = _ppa(db)
    db.add(ClienteDocumentoComercial(ppa_contrato_id=p.id, tipo="contrato",
                                      nombre="Enlace", estado="firmado",
                                      archivo_url="https://drive/z"))
    db.commit()
    db.expire_all()

    assert db.get(PPAContrato, p.id).carpeta_link == "https://drive/z"


# ── API: ContratoServicio ─────────────────────────────────────────────────────

def test_crear_contrato_con_enlace_drive_lo_expone_en_el_out(db):
    body = ContratoServicioCreate(servicio_aplica="mantenimiento", enlace_drive="https://drive/nuevo")
    out = cs_api.create_contrato(body, db=db, _=ADMIN)

    assert out.enlace_drive == "https://drive/nuevo"
    assert db.query(ClienteDocumentoComercial).filter_by(
        contrato_servicio_id=out.id, tipo="contrato").count() == 1


def test_actualizar_contrato_reemplaza_enlace_drive(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/viejo", nombre="x")
    db.commit()

    out = cs_api.update_contrato(c.id, ContratoServicioUpdate(enlace_drive="https://drive/nuevo"),
                                  db=db, _=ADMIN)

    assert out.enlace_drive == "https://drive/nuevo"
    assert db.query(ClienteDocumentoComercial).filter_by(contrato_servicio_id=c.id).count() == 1


def test_actualizar_contrato_sin_tocar_enlace_drive_lo_deja_intacto(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/viejo", nombre="x")
    db.commit()

    out = cs_api.update_contrato(c.id, ContratoServicioUpdate(numero_contrato="ABC-1"),
                                  db=db, _=ADMIN)

    assert out.enlace_drive == "https://drive/viejo"


def test_actualizar_contrato_enlace_drive_vacio_lo_borra(db):
    c = _contrato(db)
    set_enlace_documento(db, contrato_servicio_id=c.id, url="https://drive/viejo", nombre="x")
    db.commit()

    out = cs_api.update_contrato(c.id, ContratoServicioUpdate(enlace_drive=None), db=db, _=ADMIN)

    assert out.enlace_drive is None
    assert db.query(ClienteDocumentoComercial).filter_by(contrato_servicio_id=c.id).count() == 0


# ── API: PPAContrato ───────────────────────────────────────────────────────

def test_crear_ppa_con_carpeta_link_lo_expone_en_el_out(db):
    body = PPAContratoCreate(carpeta_link="https://drive/ppa-nuevo")
    out = ppa_api.create_contrato(body, db=db, _=ADMIN)

    assert out.carpeta_link == "https://drive/ppa-nuevo"
    assert db.query(ClienteDocumentoComercial).filter_by(
        ppa_contrato_id=out.id, tipo="contrato").count() == 1


# ── fusionar-representacion: enlace_drive no es una columna con setattr ──────

def test_fusionar_representacion_traslada_enlace_drive_del_perdedor(db):
    """El campo `enlace_drive` que `analizar()` calcula para completar el
    registro conservado no admite `setattr` (es un @property de solo
    lectura) -- antes de la generalizacion esto reventaba con AttributeError
    en cuanto un grupo fusionable traia el enlace solo en el duplicado."""
    ganador = _contrato(db, servicio_aplica="representacion",
                         inversionista_nombre="Inversionista X", proyecto_id=1,
                         numero_contrato="UNERGY-RC-1")
    perdedor = _contrato(db, servicio_aplica="representacion",
                          inversionista_nombre="Inversionista X", proyecto_id=1)
    set_enlace_documento(db, contrato_servicio_id=perdedor.id, url="https://drive/del-perdedor",
                          nombre="x")
    db.commit()

    resultado = cs_api.fusionar_representacion(ids=None, db=db, _=ADMIN)

    assert resultado["contratos_eliminados"] == 1
    db.expire_all()
    assert db.get(ContratoServicio, ganador.id).enlace_drive == "https://drive/del-perdedor"
    assert db.get(ContratoServicio, perdedor.id) is None


def test_actualizar_ppa_reemplaza_carpeta_link(db):
    p = _ppa(db)
    set_enlace_documento(db, ppa_contrato_id=p.id, url="https://drive/viejo", nombre="x")
    db.commit()

    resultado = ppa_api.update_contrato(p.id, PPAContratoUpdate(carpeta_link="https://drive/nuevo"),
                                         db=db, _=ADMIN)

    assert resultado["carpeta_link"] == "https://drive/nuevo"
    assert db.query(ClienteDocumentoComercial).filter_by(ppa_contrato_id=p.id).count() == 1
