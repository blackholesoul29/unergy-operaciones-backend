"""Tests del calculador de Arriendos (convención IPC DANE año-1)."""
from datetime import date
from app.services.arr_calculator import calcular_arriendo

# Claves = año DANE (diciembre). Se aplica ipc[añoC-1] al pasar a añoC.
IPC = {2023: 0.0928, 2024: 0.0520, 2025: 0.0510}


def _c(**kw):
    base = dict(
        proyecto_id=1, nombre="Demo", codigo="X",
        fecha_firma_contrato=date(2023, 1, 1),
        valor_base=1_000_000, canon_archivo=None,
        periodo="2024-06", ipc_tasas={2023: 0.10},
    )
    base.update(kw)
    return calcular_arriendo(**base)


def test_factor_un_ipc():
    f = _c()
    assert f["n_indexaciones"] == 1
    assert f["factor_acumulado"] == 1.10
    assert f["canon_calculado"] == 1_100_000
    assert f["canon_a_facturar"] == 1_100_000


def test_tres_ipcs_convencion_dane():
    f = _c(periodo="2026-06", ipc_tasas=IPC)
    assert f["n_indexaciones"] == 3
    assert round(f["factor_acumulado"], 6) == round(1.0928 * 1.0520 * 1.0510, 6)


def test_canon_archivo_gana():
    f = _c(canon_archivo=900_000)
    assert f["canon_a_facturar"] == 900_000
    assert f["canon_calculado"] == 1_100_000
    assert f["difiere_archivo"] is True


def test_sin_base_deshabilitada():
    f = _c(valor_base=None)
    assert f["habilitado"] is False
    assert f["canon_a_facturar"] is None
    assert f["historial_texto"] == "Sin valor base"


def test_sin_firma_deshabilitada():
    f = _c(fecha_firma_contrato=None)
    assert f["habilitado"] is False
    assert f["historial_texto"] == "Sin fecha de firma"
