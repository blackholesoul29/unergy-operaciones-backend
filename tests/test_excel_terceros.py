"""aplicar_excel_terceros() -- carga del Excel de FRONTERAS_TERCEROS.

Falla real 2026-08-25: un día el Excel solo trajo la fila 'Backup' (sin
'Primary') y ese día no se reportó nada -- aplicar_excel_terceros() exigía
`principal` para no saltarse la fecha, aunque sí hubiera llegado backup.

Ahora, si solo llega una matriz (Primary o Backup), esa se reporta como
curva_final y curva_respaldo_terceros queda en None -- _enviar_a_quoia()
(app/api/v1/reporte_energia.py) ya sabe estimar el respaldo con la fórmula
±1% cuando no hay dato real de terceros."""
import io
from datetime import date

import openpyxl
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.reporte_energia import ReporteEnergiaGeneracion
from app.services.reporte_energia.excel_terceros import (
    parse_excel_terceros, aplicar_excel_terceros,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _biginteger_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Frontera.__table__, ReporteEnergiaGeneracion.__table__])
    s = sessionmaker(bind=engine)()
    front = Frontera(id=1, nombre_frontera="Test Terceros", tipo_frontera=TipoFronteraEnum.generacion)
    s.add(front)
    s.commit()
    yield s
    s.close()


_HEADER = ["CODIGO SIC", "ROLE", "ENERGY TYPE", "FECHA"] + [f"HORA{h:02d}" for h in range(24)]


def _xlsx(filas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_HEADER)
    for fila in filas:
        ws.append(fila)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _fila(role: str, fecha: str, valor: float) -> list:
    return ["Frt00001", role, "Energia Exportada Activa", fecha] + [valor] * 24


def test_parse_reconoce_primary_y_backup_del_mismo_dia():
    contenido = _xlsx([
        _fila("Primary", "2026-08-25", 10.0),
        _fila("Backup", "2026-08-25", 9.9),
    ])
    resultado = parse_excel_terceros(contenido)
    assert list(resultado.keys()) == [date(2026, 8, 25)]
    assert resultado[date(2026, 8, 25)]["principal"] == [10.0] * 24
    assert resultado[date(2026, 8, 25)]["respaldo"] == [9.9] * 24


def test_aplicar_con_ambas_matrices_reporta_las_dos_tal_cual(db):
    contenido = _xlsx([
        _fila("Primary", "2026-08-25", 10.0),
        _fila("Backup", "2026-08-25", 9.9),
    ])
    fechas = aplicar_excel_terceros(db, frontera_id=1, contenido=contenido)

    assert fechas == [date(2026, 8, 25)]
    rep = db.query(ReporteEnergiaGeneracion).filter_by(frontera_id=1, fecha=date(2026, 8, 25)).one()
    assert rep.curva_final == [10.0] * 24
    assert rep.curva_respaldo_terceros == [9.9] * 24
    assert rep.medidor_usado == "excel_terceros"


def test_aplicar_solo_con_backup_reporta_la_curva_y_deja_respaldo_en_none(db):
    """El bug real: antes esto se saltaba el día por completo."""
    contenido = _xlsx([_fila("Backup", "2026-08-25", 7.5)])

    fechas = aplicar_excel_terceros(db, frontera_id=1, contenido=contenido)

    assert fechas == [date(2026, 8, 25)]
    rep = db.query(ReporteEnergiaGeneracion).filter_by(frontera_id=1, fecha=date(2026, 8, 25)).one()
    assert rep.curva_final == [7.5] * 24, "sin Primary, la curva de Backup debe reportarse como final"
    assert rep.curva_respaldo_terceros is None, (
        "sin respaldo real, se deja en None para que _enviar_a_quoia() calcule el ±1%"
    )


def test_aplicar_solo_con_primary_reporta_la_curva_y_deja_respaldo_en_none(db):
    contenido = _xlsx([_fila("Primary", "2026-08-25", 12.0)])

    fechas = aplicar_excel_terceros(db, frontera_id=1, contenido=contenido)

    rep = db.query(ReporteEnergiaGeneracion).filter_by(frontera_id=1, fecha=date(2026, 8, 25)).one()
    assert rep.curva_final == [12.0] * 24
    assert rep.curva_respaldo_terceros is None


def test_aplicar_sobrescribe_un_respaldo_previo_si_esta_carga_no_lo_trae(db):
    """Una carga anterior sí trajo Backup real; esta nueva carga del mismo
    día solo trae Primary -- no debe quedar el respaldo viejo colgado."""
    db.add(ReporteEnergiaGeneracion(
        frontera_id=1, fecha=date(2026, 8, 25), caso=0,
        curva_final=[1.0] * 24, curva_respaldo_terceros=[0.9] * 24,
    ))
    db.commit()

    contenido = _xlsx([_fila("Primary", "2026-08-25", 12.0)])
    aplicar_excel_terceros(db, frontera_id=1, contenido=contenido)

    rep = db.query(ReporteEnergiaGeneracion).filter_by(frontera_id=1, fecha=date(2026, 8, 25)).one()
    assert rep.curva_final == [12.0] * 24
    assert rep.curva_respaldo_terceros is None
