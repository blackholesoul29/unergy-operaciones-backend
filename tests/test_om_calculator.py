"""
Tests del calculador O&M:
- Algoritmo del factor IPC (fecha_base = max(firma, om), excepción primer aniversario,
  IPC por año de aplicación directo).
- Verificación contra la tabla esperada de Junio 2026 (22 proyectos) y el total.
- Override manual del valor a facturar.
"""
from datetime import date
from app.services.om_calculator import calcular_proyecto

# Tabla IPC por AÑO DE APLICACIÓN directo
IPC = {2024: 0.0928, 2025: 0.0520, 2026: 0.0510}

PERIODO = "2026-06"


def _calc(*, firma, om, base, valor_manual=None):
    """Helper: corre calcular_proyecto para Junio 2026 y devuelve el dict."""
    return calcular_proyecto(
        contrato_id=1,
        nombre_proyecto="Demo",
        fecha_firma_contrato=date.fromisoformat(firma) if firma else None,
        fecha_inicio_om=date.fromisoformat(om) if om else None,
        valor_base_anual=base,
        periodo=PERIODO,
        ipc_tasas=IPC,
        valor_manual=valor_manual,
    )


def _mensual(*, firma, om, base):
    return _calc(firma=firma, om=om, base=base)["valor_calculado"]


# ── Tabla esperada Junio 2026 ────────────────────────────────────────────────
# (nombre, fecha_firma_contrato, fecha_inicio_om, base, mensual_esperado)
TABLA_JUNIO_2026 = [
    ("Uruaco",             "2022-09-10", "2023-11-15", 48_000_000, 4_833_026),
    ("Cañahuate",          "2023-09-19", None,         48_000_000, 4_833_026),
    ("Gandalf",            "2023-09-19", None,         48_000_000, 4_833_026),
    ("La Paz Vallenata",   "2024-08-23", "2024-08-13", 48_000_000, 4_422_608),
    ("Perijá",             "2024-08-23", None,         48_000_000, 4_422_608),
    ("El Molino",          "2024-08-23", "2024-02-20", 48_000_000, 4_422_608),
    ("La Paz Verso",       "2024-08-23", "2024-09-30", 48_000_000, 4_422_608),
    ("Esmeralda",          "2024-08-23", "2025-02-26", 48_000_000, 4_204_000),
    ("La Puya",            "2024-08-23", "2025-02-19", 48_000_000, 4_204_000),
    ("Villanueva",         "2024-08-23", "2025-07-25", 48_000_000, 4_204_000),
    ("Merengue",           "2026-03-18", "2025-04-16", 54_000_000, 4_500_000),
    ("La Reserva",         "2025-05-10", "2025-04-25", 36_880_000, 3_230_073),
    ("Nestlé",             "2025-12-09", None,         78_000_000, 6_831_500),
    ("Ibirico",            "2024-12-20", "2025-07-21", 48_000_000, 4_204_000),
    ("El Olimpo",          "2024-08-23", "2025-07-20", 48_000_000, 4_204_000),
    ("La Mesa",            "2024-08-23", "2025-09-12", 48_000_000, 4_204_000),
    # San Diego Sur: firma oct-2025 NO es > 1-ene-2026 → la excepción NO aplica →
    # añoBase 2025 → IPC 2026 → 4.729.500 (coincide con el total declarado).
    ("San Diego Sur",      "2025-10-20", "2025-10-30", 54_000_000, 4_729_500),
    ("Valencia Oriente 1", "2026-03-18", "2026-01-18", 54_000_000, 4_500_000),
    ("La Cacica",          "2026-01-19", "2026-01-28", 54_000_000, 4_500_000),
    ("Las Piloneras",      "2026-01-19", "2026-02-04", 54_000_000, 4_500_000),
    ("Valencia Oriente 2", "2026-03-18", "2026-01-18", 54_000_000, 4_500_000),
    # Cumbia: firma 2025-01-01 (no excepción), om 2026-02-06 → fechaBase 2026 → factor 1.0
    ("Cumbia",             "2025-01-01", "2026-02-06", 48_000_000, 4_000_000),
    ("Copey",              "2025-01-01", "2026-03-05", 48_000_000, 4_000_000),
]

TOTAL_ESPERADO = 102_704_583


def test_tabla_completa_junio_2026():
    for nombre, firma, om, base, esperado in TABLA_JUNIO_2026:
        got = _mensual(firma=firma, om=om, base=base)
        assert got == esperado, f"{nombre}: esperado {esperado:,}, obtuvo {got:,}"


def test_total_mensual_junio_2026():
    total = sum(_mensual(firma=f, om=o, base=b) for _, f, o, b, _ in TABLA_JUNIO_2026)
    assert total == TOTAL_ESPERADO, f"total {total:,} != {TOTAL_ESPERADO:,}"


# ── 7 tests nombrados requeridos ─────────────────────────────────────────────

def test_uruaco_usa_om_tres_ipcs():
    # firma(2022) < om(2023) → usa om → IPCs 2024+2025+2026
    f = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000)
    assert f["n_indexaciones"] == 3
    assert f["valor_calculado"] == 4_833_026


def test_la_paz_vallenata_usa_firma_dos_ipcs():
    # firma(2024-08-23) > om(2024-08-13) → usa firma → IPCs 2025+2026
    f = _calc(firma="2024-08-23", om="2024-08-13", base=48_000_000)
    assert f["n_indexaciones"] == 2
    assert f["valor_calculado"] == 4_422_608


def test_esmeralda_usa_om_un_ipc():
    # firma(2024) < om(2025) → usa om → IPC 2026
    f = _calc(firma="2024-08-23", om="2025-02-26", base=48_000_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 4_204_000


def test_san_diego_sur_sigue_la_regla():
    # firma oct-2025 NO es posterior al 1-ene-2026 → la excepción de primer
    # aniversario NO aplica → añoBase 2025 → IPC 2026 → 4.729.500
    f = _calc(firma="2025-10-20", om="2025-10-30", base=54_000_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 4_729_500


def test_merengue_primer_aniversario_factor_uno():
    # firma 2026 → posterior al 1-ene-2026 → excepción → factor 1.0
    f = _calc(firma="2026-03-18", om="2025-04-16", base=54_000_000)
    assert f["n_indexaciones"] == 0
    assert f["factor_acumulado"] == 1.0
    assert f["valor_calculado"] == 4_500_000


def test_la_reserva_usa_firma_un_ipc():
    # firma(may-2025) > om(abr-2025) → usa firma → IPC 2026
    f = _calc(firma="2025-05-10", om="2025-04-25", base=36_880_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 3_230_073


def test_perija_fallback_a_firma_sin_om():
    # sin fecha_inicio_om → fallback a firma(2024) → IPCs 2025+2026
    f = _calc(firma="2024-08-23", om=None, base=48_000_000)
    assert f["n_indexaciones"] == 2
    assert f["valor_calculado"] == 4_422_608


# ── Advertencias (datos incompletos) ─────────────────────────────────────────

def test_sin_valor_base_deshabilitada():
    f = _calc(firma="2024-08-23", om="2025-01-01", base=None)
    assert f["habilitado"] is False
    assert f["valor_a_facturar"] is None
    assert f["historial_indexaciones"] == "Sin valor base"


def test_sin_firma_deshabilitada():
    # El Son: tiene om pero no firma → no se puede indexar → advertencia
    f = _calc(firma=None, om="2025-02-16", base=48_000_000)
    assert f["habilitado"] is False
    assert f["valor_a_facturar"] is None
    assert f["historial_indexaciones"] == "Sin fecha de suscripción"


# ── Override manual ──────────────────────────────────────────────────────────

def test_override_manual_gana_y_conserva_calculado():
    f = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000, valor_manual=5_000_000)
    assert f["editado_manual"] is True
    assert f["valor_a_facturar"] == 5_000_000
    assert f["valor_calculado"] == 4_833_026


def test_override_none_equivale_a_sin_override():
    a = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000, valor_manual=None)
    b = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000)
    assert a == b
