"""DELETE /proyectos/{id} -- el guard de "registros de negocio" solo
chequeaba 11 relaciones del ORM, dejando pasar 7 tablas con FK
ON DELETE CASCADE hacia proyectos que Postgres SÍ borra en silencio:
generacion_diaria (relationship existente pero no chequeada) y 6 tablas
sin relationship en el modelo (panel_contable, panel_consecutivo,
clasificacion_energia_mensual, clasificacion_liquidacion,
registro_conexion, arr_documento) -- auditoría de Proyectos 2026-08-27."""
from datetime import date

import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.generacion import GeneracionDiaria
from app.models.panel_contable import PanelContable, PanelConsecutivo, ClasificacionLiquidacion
from app.models.clasificacion_energia import ClasificacionEnergiaMensual
from app.models.registros_cnd import RegistroConexion
from app.models.arriendos import ArrDocumento
from app.api.v1 import proyectos as proyectos_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    # delete_proyecto() recorre TODAS las relaciones del modelo (fallas,
    # mantenimientos, contratos_servicio, ppa_contratos, etc) para el guard
    # de negocio -- se necesita el esquema completo, no solo las tablas que
    # este archivo prueba directamente.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto(db, id=1):
    p = Proyecto(id=id, nombre_comercial="Test")
    db.add(p)
    db.commit()
    return p


def test_sin_ningun_registro_asociado_si_se_puede_borrar(db):
    _proyecto(db)
    proyectos_api.delete_proyecto(id=1, db=db, _=None)
    assert db.get(Proyecto, 1) is None


def test_generacion_diaria_bloquea_el_borrado(db):
    """Tenía relationship (Proyecto.generaciones) pero no se chequeaba."""
    _proyecto(db)
    db.add(GeneracionDiaria(proyecto_id=1, fecha=date(2026, 8, 1), fuente="manual"))
    db.commit()

    with pytest.raises(Exception) as exc:
        proyectos_api.delete_proyecto(id=1, db=db, _=None)
    assert exc.value.status_code == 409
    assert db.get(Proyecto, 1) is not None


@pytest.mark.parametrize("tabla,fila", [
    ("panel_contable", lambda: PanelContable(proyecto_id=1, periodo="2026-08", tipo="oficial")),
    ("panel_consecutivo", lambda: PanelConsecutivo(
        proyecto_id=1, periodo="2026-08", tipo="oficial", inversionista_nombre="Test SAS",
    )),
    ("clasificacion_liquidacion", lambda: ClasificacionLiquidacion(proyecto_id=1, periodo="2026-08", tipo="normal")),
    ("clasificacion_energia_mensual", lambda: ClasificacionEnergiaMensual(
        proyecto_id=1, anio=2026, mes=8, categoria="ppa",
    )),
    ("registro_conexion", lambda: RegistroConexion(proyecto_id=1)),
    ("arr_documento", lambda: ArrDocumento(
        proyecto_id=1, periodo="2026-08", pago_id=1, codigo_contrato="C1",
        tipo_documento="factura_electronica", nombre_archivo="a.pdf", ruta_local="/a.pdf",
    )),
])
def test_tabla_sin_relationship_en_el_modelo_bloquea_el_borrado(db, tabla, fila):
    """Estas 6 tablas no tienen relationship en Proyecto -- antes del fix,
    el guard no las veía y Postgres las borraba en cascada sin aviso."""
    _proyecto(db)
    db.add(fila())
    db.commit()

    with pytest.raises(Exception) as exc:
        proyectos_api.delete_proyecto(id=1, db=db, _=None)
    assert exc.value.status_code == 409, f"debió bloquear el borrado por una fila en {tabla}"
    assert db.get(Proyecto, 1) is not None
