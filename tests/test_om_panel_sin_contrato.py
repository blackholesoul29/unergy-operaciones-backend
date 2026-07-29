"""Rediseño: el panel incluye proyectos en operación SIN contrato y marca
estado_contrato (con_contrato | en_tramite | sin_contrato)."""
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


def _proy(db, nombre, estado="en_operacion"):
    p = Proyecto(nombre_comercial=nombre, estado=estado, srv_operacion=True)
    db.add(p)
    db.flush()
    return p


def _contrato(db, proy, estado="vigente"):
    c = ContratoServicio(
        servicio_aplica="mantenimiento", proyecto_id=proy.id, estado=estado,
        tarifa_base=12_000_000, fecha_firma_contrato=date(2020, 1, 1),
        periodicidad_pago="mensual",
    )
    db.add(c)
    db.flush()
    return c


def test_panel_incluye_sin_contrato_y_marca_estado(db):
    a = _proy(db, "Alpha"); _contrato(db, a, "vigente")
    b = _proy(db, "Bravo"); _contrato(db, b, "vencido")   # no vigente → en trámite
    _proy(db, "Charlie")                                   # sin contrato
    _proy(db, "Delta", estado="en_desarrollo")             # no debe aparecer

    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    estados = {f.nombre_proyecto: f.estado_contrato for f in resp.filas}
    assert estados == {
        "Alpha": "con_contrato", "Bravo": "en_tramite", "Charlie": "sin_contrato",
    }
    charlie = next(f for f in resp.filas if f.nombre_proyecto == "Charlie")
    assert charlie.habilitado is False   # sin contrato → no facturable


def test_sin_firma_pero_con_fecha_inicio_del_dialogo_habilita(db):
    """La 'Fecha de inicio O&M' del diálogo vive en fecha_inicio; sin firma pero
    con esa fecha, la fila queda HABILITADA (om.py usa fecha_inicio_om or fecha_inicio)."""
    p = Proyecto(nombre_comercial="SinFirma", estado="en_operacion", srv_operacion=True, tipo_proyecto="minigranja")
    db.add(p); db.flush()
    c = ContratoServicio(
        servicio_aplica="mantenimiento", proyecto_id=p.id, estado="vigente",
        tarifa_base=12_000_000, fecha_firma_contrato=None,
        fecha_inicio_om=None, fecha_inicio=date(2020, 1, 1),
        periodicidad_pago="mensual",
    )
    db.add(c); db.flush()

    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.nombre_proyecto == "SinFirma")
    assert fila.habilitado is True
    assert fila.historial_indexaciones != "Sin fecha de suscripción"


def test_calculo_expone_motivo_exclusion(db):
    """La fila trae el motivo_exclusion guardado para mostrarlo en el panel (tooltip)."""
    p = Proyecto(nombre_comercial="Excl", estado="en_operacion", srv_operacion=True, tipo_proyecto="minigranja")
    db.add(p); db.flush()
    c = _contrato(db, p, "vigente")
    db.add(OMSeleccion(contrato_id=c.id, periodo="2026-06",
                       incluido=False, motivo_exclusion="en disputa con el cliente"))
    db.flush()

    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.contrato_id == c.id)
    assert fila.motivo_exclusion == "en disputa con el cliente"


def test_fila_incluye_tipo_proyecto(db):
    """Cada fila lleva el tipo_proyecto para agrupar el panel (como en Proyectos)."""
    mg = Proyecto(nombre_comercial="Mini", estado="en_operacion", srv_operacion=True, tipo_proyecto="minigranja")
    db.add(mg); db.flush(); _contrato(db, mg, "vigente")
    ac = Proyecto(nombre_comercial="Auto", estado="en_operacion", srv_operacion=True, tipo_proyecto="autoconsumo")
    db.add(ac); db.flush()   # sin contrato

    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    tipos = {f.nombre_proyecto: f.tipo_proyecto for f in resp.filas}
    assert tipos == {"Mini": "minigranja", "Auto": "autoconsumo"}
