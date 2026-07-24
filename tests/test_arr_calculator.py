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
    # Sin firma y sin inicio O&M → no hay fecha base → deshabilitada.
    f = _c(fecha_firma_contrato=None)
    assert f["habilitado"] is False
    assert f["historial_texto"] == "Sin fecha de inicio O&M ni de firma"


def test_indexa_desde_inicio_om_si_existe():
    # Con inicio O&M anterior a la firma, indexa desde el inicio O&M (más antiguo).
    from datetime import date as _d
    f = _c(fecha_firma_contrato=_d(2025, 1, 1), fecha_inicio_om=_d(2023, 1, 1),
           periodo="2026-06", ipc_tasas=IPC)
    # base 2023 → aniversarios 2024, 2025, 2026 (DANE ipc[año-1])
    assert f["n_indexaciones"] == 3


def test_periodicidad_trimestral_no_aplica_algunos_meses():
    from datetime import date as _d
    # base ene-2024, trimestral → aplica ene, abr, jul, oct. Mayo NO aplica.
    f = _c(fecha_firma_contrato=_d(2024, 1, 1), periodo="2024-05",
           periodicidad="trimestral", ipc_tasas=IPC)
    assert f["aplica_este_mes"] is False
    f2 = _c(fecha_firma_contrato=_d(2024, 1, 1), periodo="2024-04",
            periodicidad="trimestral", ipc_tasas=IPC)
    assert f2["aplica_este_mes"] is True


def test_deshabilitada_redondea_canon_archivo():
    # Ibirico: sin firma pero con canon_archivo fraccional → debe redondear a int
    # (si no, Pydantic Optional[int] revienta el endpoint /calculo).
    f = _c(fecha_firma_contrato=None, canon_archivo=1024604.167)
    assert f["habilitado"] is False
    assert f["canon_archivo"] == 1024604
    assert isinstance(f["canon_archivo"], int)


# ── Indexación por ANIVERSARIO real del contrato (fix 2026-07) ────────────────
# Antes se indexaba por año calendario (incremento cada enero). Ahora el
# incremento se aplica en el aniversario del contrato, preservando la
# convención DANE: en el aniversario del año Y se aplica ipc[Y-1].

def test_firma_marzo_no_indexa_antes_del_aniversario():
    # Firmado 2024-03-15; en enero-2025 aún NO cumple el primer año → sin indexar.
    f = _c(fecha_firma_contrato=date(2024, 3, 15), periodo="2025-01",
           ipc_tasas={2024: 0.10})
    assert f["n_indexaciones"] == 0
    assert f["factor_acumulado"] == 1.0
    assert f["canon_calculado"] == 1_000_000


def test_firma_marzo_indexa_desde_el_aniversario():
    # Mismo contrato; en junio-2025 ya pasó el aniversario (marzo) → 1 indexación
    # con ipc[2024] (DANE: año anterior al aniversario 2025).
    f = _c(fecha_firma_contrato=date(2024, 3, 15), periodo="2025-06",
           ipc_tasas={2024: 0.10})
    assert f["n_indexaciones"] == 1
    assert f["factor_acumulado"] == 1.10
    assert f["canon_calculado"] == 1_100_000


def test_firma_marzo_segundo_aniversario_aun_no_cumplido():
    # En enero-2026 solo se cumplió UN aniversario (marzo-2025); el de marzo-2026
    # todavía no → 1 indexación (ipc[2024]), no 2.
    f = _c(fecha_firma_contrato=date(2024, 3, 15), periodo="2026-01",
           ipc_tasas={2024: 0.0520, 2025: 0.0510})
    assert f["n_indexaciones"] == 1
    assert round(f["factor_acumulado"], 6) == 1.052
