"""Arriendos Fase A: al facturar se congela el canon; al desmarcar se descongela."""
import types
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401
from app.models.arriendos import ArrProyecto, ArrSeleccion, ArrIPCTasa
from app.models.proyectos import Proyecto
from app.models.contratos import ContratoServicio
from app.api.v1 import arriendos as api
from app.schemas.arriendos import ArrSeleccionGuardar, ArrSeleccionItem


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


ADMIN = types.SimpleNamespace(id=1)
PERIODO = "2026-06"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        ArrProyecto.__table__, ArrSeleccion.__table__, ArrIPCTasa.__table__,
        Proyecto.__table__, ContratoServicio.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proy(db):
    p = ArrProyecto(nombre="Predio", codigo="C1", valor_base=1_000_000,
                    fecha_firma_contrato=date(2020, 1, 1), activo=True)
    db.add(p); db.flush()
    return p


def test_facturar_congela_y_desmarcar_descongela(db):
    p = _proy(db)
    sel = api.toggle_facturado(PERIODO, p.id, db=db, _=ADMIN)   # marca → congela
    assert sel.facturado is True
    assert sel.valor_facturado_congelado is not None

    sel = api.toggle_facturado(PERIODO, p.id, db=db, _=ADMIN)   # desmarca → descongela
    assert sel.facturado is False
    assert sel.valor_facturado_congelado is None


def test_calculo_usa_valor_congelado(db):
    p = _proy(db)
    db.add(ArrSeleccion(arr_proyecto_id=p.id, periodo=PERIODO, incluido=True,
                        facturado=True, valor_facturado_congelado=555_000))
    db.flush()
    resp = api.calcular_periodo(PERIODO, db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.id == p.id)
    assert fila.canon_a_facturar == 555_000


def test_calculo_toma_datos_del_contrato_no_de_arrproyecto(db):
    """El valor/estado/tipo salen del contrato de arriendo en Operación (fuente de
    verdad), no del ArrProyecto (que queda solo como llave/respaldo)."""
    p = Proyecto(nombre_comercial="Baraya", estado="en_operacion", tipo_proyecto="minigranja")
    db.add(p); db.flush()
    db.add(ContratoServicio(servicio_aplica="arriendo", proyecto_id=p.id, estado="vigente",
                            tarifa_base=9_000_000, fecha_firma_contrato=date(2020, 1, 1),
                            periodicidad_pago="mensual"))
    db.add(ArrProyecto(nombre="Minigranja Solar Baraya", codigo="C1", valor_base=1_000_000,
                       fecha_firma_contrato=date(2019, 1, 1), activo=True))
    db.flush()

    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.proyecto == "Baraya")
    assert fila.estado_contrato == "con_contrato"
    assert fila.tipo_proyecto == "minigranja"
    # tarifa_base del contrato es ANUAL (9.000.000); el motor de cálculo espera
    # valor_base MENSUAL, así que el router divide entre 12 -> 750.000.
    # Confirma que sale del contrato (750.000), NO del ArrProyecto (1.000.000).
    assert fila.valor_base == 750_000


def test_arrproyecto_sin_contrato_queda_sin_contrato(db):
    db.add(ArrProyecto(nombre="Predio Suelto", codigo="Z", valor_base=2_000_000,
                       fecha_firma_contrato=date(2020, 1, 1), activo=True))
    db.flush()
    resp = api.calcular_periodo("2026-06", db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.proyecto == "Predio Suelto")
    assert fila.estado_contrato == "sin_contrato"
    assert fila.valor_base == 2_000_000        # respaldo al ArrProyecto


def test_motivo_exclusion_se_guarda_y_se_expone(db):
    p = _proy(db)
    api.guardar_seleccion(PERIODO, ArrSeleccionGuardar(items=[
        ArrSeleccionItem(proyecto_id=p.id, incluido=False, motivo_exclusion="en disputa"),
    ]), db=db, _=ADMIN)

    sel = db.query(ArrSeleccion).filter(ArrSeleccion.arr_proyecto_id == p.id).first()
    assert sel.incluido is False and sel.motivo_exclusion == "en disputa"

    resp = api.calcular_periodo(PERIODO, db=db, _=ADMIN)
    fila = next(f for f in resp.filas if f.id == p.id)
    assert fila.motivo_exclusion == "en disputa"
