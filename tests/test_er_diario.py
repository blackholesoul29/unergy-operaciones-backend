"""La tabla día por día del Estado de Resultados.

El ER no es un resumen: arranca con una fila por día -- generación, importación y
venta -- y de ahí salen los totales.

La importación es el consumo: la suma de las 24 horas de `disp_contracts_ftp_xm`.
Verificado contra agustin_2 en 2026-07, donde sus 31 días suman 621,66, que es
exactamente el `importacion_kwh` mensual que reporta la API.
"""
from app.services.er_diario import construir_tabla_diaria


def _despacho(fecha, energia, precio, tipo="dispatch"):
    return {"date": fecha, "energy": energia, "price": precio, "data_type": tipo}


def _consumo(fecha, por_hora):
    fila = {"date": fecha}
    fila.update({f"con_hour{h:02d}": por_hora for h in range(1, 25)})
    return fila


def test_una_fila_por_dia():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 5629.63, 4_491_783.26),
                   _despacho("2026-07-02", 3597.46, 2_839_856.69)],
        consumos=[_consumo("2026-07-01", 1.0), _consumo("2026-07-02", 1.0)])
    assert [f["fecha"] for f in tabla] == ["2026-07-01", "2026-07-02"]


def test_la_importacion_es_la_suma_de_las_24_horas():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0)],
        consumos=[_consumo("2026-07-01", 0.94)])
    assert tabla[0]["importacion_kwh"] == 22.56


def test_un_dia_sin_consumo_va_en_cero_no_desaparece():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-05", 100.0, 1000.0)], consumos=[])
    assert tabla[0]["importacion_kwh"] == 0.0


def test_un_dia_solo_con_consumo_tambien_aparece():
    """Una planta parada sigue consumiendo: ese día es información, no un hueco."""
    tabla = construir_tabla_diaria(despachos=[], consumos=[_consumo("2026-07-05", 1.0)])
    assert tabla[0]["fecha"] == "2026-07-05"
    assert tabla[0]["generacion_kwh"] == 0.0


def test_suma_varios_contratos_del_mismo_dia():
    """Una planta con dos contratos despacha dos veces el mismo día."""
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-01", 50.0, 500.0)],
        consumos=[])
    assert tabla[0]["generacion_kwh"] == 150.0
    assert tabla[0]["venta_cop"] == 1500.0


def test_las_compras_no_suman_como_generacion():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-01", 30.0, -300.0, tipo="purchase")],
        consumos=[])
    assert tabla[0]["generacion_kwh"] == 100.0
    assert tabla[0]["venta_cop"] == 1000.0


def test_la_venta_en_bolsa_si_suma():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 50.0, 500.0, tipo="dispatch_fazni")],
        consumos=[])
    assert tabla[0]["generacion_kwh"] == 50.0


def test_los_dias_salen_ordenados():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-03", 1.0, 1.0), _despacho("2026-07-01", 1.0, 1.0)],
        consumos=[])
    assert [f["fecha"] for f in tabla] == ["2026-07-01", "2026-07-03"]


def test_recorta_la_fecha_si_viene_con_hora():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01T00:00:00-05:00", 1.0, 1.0)], consumos=[])
    assert tabla[0]["fecha"] == "2026-07-01"


def test_los_totales_cuadran_con_las_filas():
    tabla = construir_tabla_diaria(
        despachos=[_despacho("2026-07-01", 100.0, 1000.0),
                   _despacho("2026-07-02", 200.0, 2000.0)],
        consumos=[_consumo("2026-07-01", 1.0)])
    assert sum(f["generacion_kwh"] for f in tabla) == 300.0
    assert sum(f["importacion_kwh"] for f in tabla) == 24.0


def test_una_hora_nula_no_revienta():
    fila = _consumo("2026-07-01", 1.0)
    fila["con_hour07"] = None
    tabla = construir_tabla_diaria(despachos=[], consumos=[fila])
    assert tabla[0]["importacion_kwh"] == 23.0


def test_sin_datos_devuelve_vacio():
    assert construir_tabla_diaria(despachos=[], consumos=[]) == []
