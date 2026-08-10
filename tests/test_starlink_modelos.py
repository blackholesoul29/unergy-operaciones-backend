"""Smoke test: los modelos nuevos existen, tienen tabla y columnas esperadas."""
from app.models.starlink import StarlinkMapeoSitio, StarlinkFacturaLinea


def test_mapeo_sitio_tabla_y_columnas():
    assert StarlinkMapeoSitio.__tablename__ == "starlink_mapeo_sitio"
    cols = set(StarlinkMapeoSitio.__table__.columns.keys())
    assert {"id", "patron", "proyecto_id", "activo"} <= cols


def test_factura_linea_tabla_y_columnas():
    assert StarlinkFacturaLinea.__tablename__ == "starlink_factura_linea"
    cols = set(StarlinkFacturaLinea.__table__.columns.keys())
    assert {"id", "factura_id", "proyecto_id", "descripcion",
            "sin_iva", "iva", "monto_total"} <= cols


def test_factura_linea_fk_a_facturas_con_cascade():
    fk = list(StarlinkFacturaLinea.__table__.c.factura_id.foreign_keys)[0]
    assert fk.column.table.name == "starlink_facturas"
    assert fk.ondelete == "CASCADE"
