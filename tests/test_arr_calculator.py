"""Tests del calculador de Arriendos (convención IPC DANE año-1)."""
from datetime import date
from app.services.arr_calculator import calcular_arriendo

# Claves = año DANE (diciembre). Se aplica ipc[añoC-1] al pasar a añoC.
IPC = {2023: 0.0928, 2024: 0.0520, 2025: 0.0510}


def _c(**kw):
    base = dict(
        proyecto_id=1, nombre="Demo", codigo="X",
        fecha_firma_contrato=date(2023, 1, 1),
        valor_base=1_000_000,
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


def test_sin_base_deshabilitada():
    f = _c(valor_base=None)
    assert f["habilitado"] is False
    assert f["canon_a_facturar"] is None
    assert f["historial_texto"] == "Sin valor base"


def test_valor_congelado_tiene_prioridad():
    # Fase A: canon congelado al facturar gana sobre el calculado/archivo.
    f = _c(valor_congelado=777_000)
    assert f["canon_a_facturar"] == 777_000
    assert f["valor_facturado_congelado"] == 777_000


def test_ipc_incompleto_marca_flag():
    # Falta la tasa de un año intermedio → ipc_incompleto True (no cambia el monto).
    f = _c(periodo="2026-06", ipc_tasas={2023: 0.0928})   # faltan 2024 y 2025
    assert f["ipc_incompleto"] is True


def test_ipc_completo_no_marca_flag():
    f = _c(periodo="2026-06", ipc_tasas=IPC)
    assert f["ipc_incompleto"] is False


def test_sin_ninguna_fecha_deshabilitada():
    # Sin fecha de firma de contrato → no hay fecha base → deshabilitada.
    f = _c(fecha_firma_contrato=None)
    assert f["habilitado"] is False
    assert f["historial_texto"] == "Sin fecha de contrato"


def test_periodicidad_trimestral_no_aplica_algunos_meses():
    from datetime import date as _d
    # base ene-2024, trimestral → aplica ene, abr, jul, oct. Mayo NO aplica.
    f = _c(fecha_firma_contrato=_d(2024, 1, 1), periodo="2024-05",
           periodicidad="trimestral", ipc_tasas=IPC)
    assert f["aplica_este_mes"] is False
    f2 = _c(fecha_firma_contrato=_d(2024, 1, 1), periodo="2024-04",
            periodicidad="trimestral", ipc_tasas=IPC)
    assert f2["aplica_este_mes"] is True


# ── Indexación por AÑO CALENDARIO (decisión de negocio, revierte fix aniversario) ──
# El incremento se aplica cada 1 de enero, usando solo el AÑO de
# fecha_firma_contrato (no el mes/día de la firma). Convención DANE: en enero
# del año Y se aplica ipc[Y-1].

def test_firma_marzo_indexa_en_enero_siguiente_sin_esperar_aniversario():
    # Firmado 2024-03-15; en enero-2025 YA indexa (año calendario), aunque
    # el aniversario real (marzo) todavía no haya llegado.
    f = _c(fecha_firma_contrato=date(2024, 3, 15), periodo="2025-01",
           ipc_tasas={2024: 0.10})
    assert f["n_indexaciones"] == 1
    assert f["factor_acumulado"] == 1.10
    assert f["canon_calculado"] == 1_100_000


def test_tres_incrementos_a_julio_del_tercer_anio():
    # Firmado 2023-09-01; a julio-2026 ya pasaron 3 1-eneros: 2024, 2025, 2026.
    ipc = {2023: 0.0928, 2024: 0.0520, 2025: 0.0510}
    f = _c(fecha_firma_contrato=date(2023, 9, 1), periodo="2026-07",
           valor_base=4_300_000, ipc_tasas=ipc)
    assert f["n_indexaciones"] == 3
    assert round(f["factor_acumulado"], 6) == round(1.0928 * 1.0520 * 1.0510, 6)
    assert f["canon_calculado"] == round(4_300_000 * 1.0928 * 1.0520 * 1.0510)


def test_serie_indexacion_coincide_con_calcular_arriendo():
    from app.services.arr_calculator import calcular_arriendo, serie_indexacion
    ipc = {2023: 0.0928, 2024: 0.0520, 2025: 0.0510}
    fila = calcular_arriendo(
        proyecto_id=1, nombre="X", codigo=None,
        fecha_firma_contrato=date(2023, 9, 1),
        valor_base=4_300_000,
        periodo="2026-07", ipc_tasas=ipc,
    )
    serie = serie_indexacion(date(2023, 9, 1), 4_300_000, ipc, 2026, 7)
    assert serie[-1]["valor_mensual"] == fila["canon_calculado"]
