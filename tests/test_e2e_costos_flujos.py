"""Smoke test end-to-end de los flujos de Costos ↔ Proyectos ↔ Servicios/Operación.

Ejerce los ENDPOINTS reales (no solo las funciones puras) contra una BD SQLite en
memoria, cubriendo:
  1. Mantenimiento: crear contrato desde "Agregar Costo" → aparece en /om/calculo.
  2. Arriendos: crear arr_proyecto vinculado → el sync crea el contrato (arriendo)
     que ve Servicios→Operación, y aparece en /arriendos/calculo.
  3. Editar el contrato desde Operación → se refleja de vuelta en Costos (arr_proyecto).
  4. Anti-duplicado: no se crea un segundo arr_proyecto para el mismo proyecto.
"""
import pytest
from datetime import date
from fastapi import HTTPException
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from app.models.base import Base
import app.models  # noqa: F401  (registra todos los modelos/relaciones)
from app.models import Proyecto
from app.models.clientes import Cliente
from app.models.contratos import ContratoServicio, PagoServicio
from app.models.arriendos import ArrProyecto, ArrIPCTasa, ArrSeleccion
from app.models.om import IPCTasa, OMSeleccion, OMDocumentoProyecto

from app.schemas.contratos_servicio import ContratoServicioCreate, ContratoServicioUpdate
from app.schemas.arriendos import ArrProyectoIn
from app.api.v1 import contratos_servicio as cs_api
from app.api.v1 import om as om_api
from app.api.v1 import arriendos as arr_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Proyecto.__table__, Cliente.__table__,
            ContratoServicio.__table__, PagoServicio.__table__,
            ArrProyecto.__table__, ArrIPCTasa.__table__, ArrSeleccion.__table__,
            IPCTasa.__table__, OMSeleccion.__table__, OMDocumentoProyecto.__table__,
        ],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


PERIODO = "2026-07"


def test_e2e_mantenimiento_agregar_costo_aparece_en_panel(db):
    db.add(Proyecto(id=1, nombre_comercial="MGS 0023 Joropo", estado="en_operacion"))
    db.commit()

    # Antes: Joropo no está en el panel O&M
    antes = om_api.calcular_periodo(PERIODO, db=db, _=None)
    assert all(f.nombre_proyecto != "MGS 0023 Joropo" for f in antes.filas)

    # "Agregar Costo" → crea el contrato de mantenimiento
    dto = ContratoServicioCreate(
        servicio_aplica="mantenimiento", proyecto_id=1,
        tarifa_base=12_000_000, fecha_firma_contrato=date(2024, 1, 1),
    )
    cs_api.create_contrato(dto, db=db, _=None)

    # Después: aparece habilitado y con valor a facturar
    despues = om_api.calcular_periodo(PERIODO, db=db, _=None)
    joropo = [f for f in despues.filas if f.nombre_proyecto == "MGS 0023 Joropo"]
    assert len(joropo) == 1
    assert joropo[0].habilitado is True
    assert joropo[0].valor_a_facturar is not None and joropo[0].valor_a_facturar > 0


def test_e2e_arriendo_crear_sincroniza_a_operacion(db):
    db.add(Proyecto(id=2, nombre_comercial="Mapalé", estado="en_operacion"))
    db.commit()

    # "Agregar Costo" en Arriendos, vinculado al proyecto maestro
    out = arr_api.crear_proyecto(
        ArrProyectoIn(nombre="Mapalé", proyecto_id=2, valor_base=5_000_000,
                      fecha_firma_contrato=date(2024, 6, 1)),
        db=db, _=None,
    )
    assert out.proyecto_id == 2

    # El sync creó el contrato de arriendo que ve Servicios→Operación
    contrato = db.query(ContratoServicio).filter_by(
        proyecto_id=2, servicio_aplica="arriendo").first()
    assert contrato is not None
    assert float(contrato.tarifa_base) == 5_000_000
    assert contrato.fecha_firma_contrato == date(2024, 6, 1)

    # Y aparece en el panel de Arriendos
    calc = arr_api.calcular_periodo(PERIODO, db=db, _=None)
    assert any(f.proyecto == "Mapalé" for f in calc.filas)


def test_e2e_editar_contrato_desde_operacion_refleja_en_costos(db):
    db.add(Proyecto(id=2, nombre_comercial="Mapalé", estado="en_operacion"))
    db.commit()
    arr_api.crear_proyecto(
        ArrProyectoIn(nombre="Mapalé", proyecto_id=2, valor_base=5_000_000),
        db=db, _=None,
    )
    contrato = db.query(ContratoServicio).filter_by(
        proyecto_id=2, servicio_aplica="arriendo").first()

    # Editar el contrato desde Servicios→Operación
    cs_api.update_contrato(
        contrato.id, ContratoServicioUpdate(tarifa_base=6_500_000), db=db, _=None)

    # Se refleja de vuelta en Costos (arr_proyecto)
    arr = db.query(ArrProyecto).filter_by(proyecto_id=2).first()
    assert float(arr.valor_base) == 6_500_000


def test_e2e_no_duplica_arriendo_para_mismo_proyecto(db):
    db.add(Proyecto(id=2, nombre_comercial="Mapalé", estado="en_operacion"))
    db.commit()
    arr_api.crear_proyecto(ArrProyectoIn(nombre="Mapalé", proyecto_id=2), db=db, _=None)

    with pytest.raises(HTTPException) as exc:
        arr_api.crear_proyecto(ArrProyectoIn(nombre="Mapalé", proyecto_id=2), db=db, _=None)
    assert exc.value.status_code == 409
    assert db.query(ArrProyecto).filter_by(proyecto_id=2).count() == 1
