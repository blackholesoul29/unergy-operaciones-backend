"""ArrProyecto debe tener columna proyecto_id (FK opcional a proyectos)."""
from app.models.arriendos import ArrProyecto


def test_arr_proyecto_tiene_columna_proyecto_id():
    cols = ArrProyecto.__table__.columns.keys()
    assert "proyecto_id" in cols


def test_arr_proyecto_id_es_nullable_y_fk():
    col = ArrProyecto.__table__.columns["proyecto_id"]
    assert col.nullable is True
    fks = list(col.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "proyectos"
