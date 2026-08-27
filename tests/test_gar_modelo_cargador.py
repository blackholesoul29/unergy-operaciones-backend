"""Carga de insumos FTP: idempotencia y la regla de disponible_desde."""
import datetime

import pytest

from app.services.garantias_modelo.cargador import (
    LAG_POR_VERSION,
    agregar_por_clave_natural,
    disponible_desde_derivado,
    filas_a_medidas,
)

FECHA = datetime.date(2026, 8, 14)


def test_lag_de_tx2_es_siete_dias():
    """Sale del timeline de XM: la ventana cierra 14 días antes del vencimiento y XM
    calcula 7 días antes, usando TX2 de esos días."""
    assert LAG_POR_VERSION["tx2"] == 7


def test_disponible_desde_derivado_suma_el_lag():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.date() == datetime.date(2026, 8, 21)


def test_disponible_desde_derivado_es_utc():
    r = disponible_desde_derivado(FECHA, "tx2")
    assert r.tzinfo is not None


def test_version_sin_lag_conocido_falla_ruidosamente():
    """Errar por exceso es seguro, inventar no. Una versión desconocida se rechaza."""
    with pytest.raises(ValueError):
        disponible_desde_derivado(FECHA, "txz")


def test_filas_a_medidas_asigna_el_archivo():
    filas = [{"tipo": "trsd", "fecha_documento": FECHA, "hora": 1, "entidad": "NACIONAL",
              "concepto": "pbna", "concepto_raw": "PBNA", "valor": 250.5, "version": "tx2"}]
    r = filas_a_medidas(filas, archivo_id=42)
    assert len(r) == 1
    assert r[0]["archivo_id"] == 42
    assert r[0]["concepto"] == "pbna"


def test_filas_a_medidas_vacio():
    assert filas_a_medidas([], archivo_id=1) == []


def _fila(concepto, valor, hora=1):
    return {"tipo": "balcttos", "fecha_documento": FECHA, "hora": hora,
            "entidad": "UNGG", "concepto": concepto, "concepto_raw": concepto.upper(),
            "valor": valor, "version": "tx2"}


def test_agregar_suma_las_filas_que_comparten_clave():
    """BalCttos trae una linea por contrato: en julio-2026, 50 con el mismo CONCEPTO."""
    filas, colapsadas = agregar_por_clave_natural(
        [_fila("contrato de venta", 10.0), _fila("contrato de venta", 5.0)])
    assert len(filas) == 1
    assert filas[0]["valor"] == pytest.approx(15.0)
    assert colapsadas == 1


def test_agregar_no_toca_los_conceptos_de_la_replica():
    """`neto de compras/ventas` vienen una sola vez por dia: deben pasar intactos."""
    entrada = [_fila("neto de compras en bolsa", 100.0),
               _fila("neto de ventas en bolsa", 40.0)]
    filas, colapsadas = agregar_por_clave_natural(entrada)
    assert colapsadas == 0
    assert {f["concepto"]: f["valor"] for f in filas} == {
        "neto de compras en bolsa": 100.0, "neto de ventas en bolsa": 40.0}


def test_agregar_separa_por_hora():
    filas, colapsadas = agregar_por_clave_natural(
        [_fila("contrato de venta", 10.0, hora=1),
         _fila("contrato de venta", 7.0, hora=2)])
    assert len(filas) == 2
    assert colapsadas == 0


def test_agregar_separa_por_entidad():
    a = _fila("contrato de venta", 10.0)
    b = dict(_fila("contrato de venta", 10.0), entidad="UNGC")
    filas, colapsadas = agregar_por_clave_natural([a, b])
    assert len(filas) == 2
    assert colapsadas == 0


def test_agregar_separa_por_version():
    """Append-only: un TXR nunca debe fundirse con el TX2 que corrige."""
    a = _fila("contrato de venta", 10.0)
    b = dict(_fila("contrato de venta", 99.0), version="txr")
    filas, colapsadas = agregar_por_clave_natural([a, b])
    assert len(filas) == 2
    assert colapsadas == 0


def test_agregar_no_muta_la_entrada():
    entrada = [_fila("contrato de venta", 10.0), _fila("contrato de venta", 5.0)]
    agregar_por_clave_natural(entrada)
    assert entrada[0]["valor"] == 10.0


def test_agregar_vacio():
    assert agregar_por_clave_natural([]) == ([], 0)


def test_agregar_deja_la_lista_lista_para_insertar():
    """Tras agregar, ninguna clave natural puede repetirse: eso es lo que exige
    uq_xm_medida_natural y lo que rompio la primera carga en Postgres."""
    entrada = [_fila("contrato de venta", i) for i in range(50)]
    entrada += [_fila("contrato de venta", i, hora=2) for i in range(50)]
    filas, colapsadas = agregar_por_clave_natural(entrada)
    claves = [(f["tipo"], f["fecha_documento"], f["hora"], f["entidad"],
               f["concepto"], f["version"]) for f in filas]
    assert len(claves) == len(set(claves))
    assert colapsadas == 98
