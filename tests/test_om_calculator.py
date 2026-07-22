"""
Tests del calculador O&M:
- Algoritmo del factor IPC (fecha_base = max(firma, om), indexación por ANIVERSARIO REAL
  del contrato — no por año calendario —, IPC por año de aplicación directo).
- Helpers de aniversario (_fecha_aniversario, _aniversarios_cumplidos), incl. clamp 29-feb.
- Verificación contra la tabla esperada de Junio 2026 (22 proyectos) y el total.
- Override manual del valor a facturar.
"""
from datetime import date
from app.services.om_calculator import (
    calcular_proyecto,
    _fecha_aniversario,
    _aniversarios_cumplidos,
)

# Tabla IPC por AÑO DE APLICACIÓN directo
IPC = {2024: 0.0928, 2025: 0.0520, 2026: 0.0510}

PERIODO = "2026-06"


# ── Aniversario real (helpers nuevos) ────────────────────────────────────────

def test_fecha_aniversario_mismo_mes_dia():
    assert _fecha_aniversario(date(2023, 11, 15), 1) == date(2024, 11, 15)
    assert _fecha_aniversario(date(2023, 11, 15), 3) == date(2026, 11, 15)

def test_fecha_aniversario_clamp_29_feb_en_año_no_bisiesto():
    # 2024 es bisiesto (29-feb existe); 2025 no lo es → clamp a 28-feb
    assert _fecha_aniversario(date(2024, 2, 29), 1) == date(2025, 2, 28)
    # 2028 sí es bisiesto → no hace falta clamp
    assert _fecha_aniversario(date(2024, 2, 29), 4) == date(2028, 2, 29)

def test_aniversarios_cumplidos_limite_exacto_del_periodo():
    # Aniversario cae exactamente el último día del período → cuenta
    aniversarios = _aniversarios_cumplidos(date(2025, 6, 30), 2026, 6)
    assert aniversarios == [date(2026, 6, 30)]

def test_aniversarios_cumplidos_un_dia_despues_no_cuenta():
    # Aniversario un día después del fin del período → no cuenta todavía
    aniversarios = _aniversarios_cumplidos(date(2025, 7, 1), 2026, 6)
    assert aniversarios == []

def test_aniversarios_cumplidos_varios_años():
    aniversarios = _aniversarios_cumplidos(date(2023, 11, 15), 2026, 6)
    assert aniversarios == [date(2024, 11, 15), date(2025, 11, 15)]


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


# ── Tabla esperada Junio 2026 (regla de ANIVERSARIO REAL) ────────────────────
# (nombre, fecha_firma_contrato, fecha_inicio_om, base, mensual_esperado)
# Valores regenerados corriendo calcular_proyecto() con la regla nueva; los que
# cambian respecto a la regla vieja (año calendario) son los que dejan de
# indexar antes de que el aniversario real del contrato realmente llegue.
TABLA_JUNIO_2026 = [
    ("Uruaco",             "2022-09-10", "2023-11-15", 48_000_000, 4_598_502),
    ("Cañahuate",          "2023-09-19", None,         48_000_000, 4_598_502),
    ("Gandalf",            "2023-09-19", None,         48_000_000, 4_598_502),
    ("La Paz Vallenata",   "2024-08-23", "2024-08-13", 48_000_000, 4_208_000),
    # Perijá: sin om → fecha_base = firma (2024-08-23). Aniversario 2025-08-23
    # ya llegó al 30-jun-2026, pero el de 2026-08-23 todavía no → 1 indexación
    # (antes 2, porque la regla vieja indexaba desde 1-enero-2026 sin esperar
    # a que llegara agosto).
    ("Perijá",             "2024-08-23", None,         48_000_000, 4_208_000),
    ("El Molino",          "2024-08-23", "2024-02-20", 48_000_000, 4_208_000),
    ("La Paz Verso",       "2024-08-23", "2024-09-30", 48_000_000, 4_208_000),
    ("Esmeralda",          "2024-08-23", "2025-02-26", 48_000_000, 4_204_000),
    ("La Puya",            "2024-08-23", "2025-02-19", 48_000_000, 4_204_000),
    # Villanueva: fecha_base = om (2025-07-25). Su aniversario real es 2026-07-25,
    # todavía no llegó en el período de junio → 0 indexaciones (antes 1).
    ("Villanueva",         "2024-08-23", "2025-07-25", 48_000_000, 4_000_000),
    ("Merengue",           "2026-03-18", "2025-04-16", 54_000_000, 4_500_000),
    ("La Reserva",         "2025-05-10", "2025-04-25", 36_880_000, 3_230_073),
    # Nestlé: fecha_base = firma (2025-12-09). Aniversario real 2026-12-09, muy
    # posterior a junio-2026 → 0 indexaciones (antes 1, indexaba desde enero).
    ("Nestlé",             "2025-12-09", None,         78_000_000, 6_500_000),
    ("Ibirico",            "2024-12-20", "2025-07-21", 48_000_000, 4_000_000),
    ("El Olimpo",          "2024-08-23", "2025-07-20", 48_000_000, 4_000_000),
    ("La Mesa",            "2024-08-23", "2025-09-12", 48_000_000, 4_000_000),
    # San Diego Sur: aniversario real 2026-10-30 aún no llega en junio-2026 →
    # 0 indexaciones (antes 1: la regla vieja indexaba desde 1-enero-2026 sin
    # esperar al aniversario real de octubre).
    ("San Diego Sur",      "2025-10-20", "2025-10-30", 54_000_000, 4_500_000),
    ("Valencia Oriente 1", "2026-03-18", "2026-01-18", 54_000_000, 4_500_000),
    ("La Cacica",          "2026-01-19", "2026-01-28", 54_000_000, 4_500_000),
    ("Las Piloneras",      "2026-01-19", "2026-02-04", 54_000_000, 4_500_000),
    ("Valencia Oriente 2", "2026-03-18", "2026-01-18", 54_000_000, 4_500_000),
    ("Cumbia",             "2025-01-01", "2026-02-06", 48_000_000, 4_000_000),
    ("Copey",              "2025-01-01", "2026-03-05", 48_000_000, 4_000_000),
]

TOTAL_ESPERADO = 99_765_579


def test_tabla_completa_junio_2026():
    for nombre, firma, om, base, esperado in TABLA_JUNIO_2026:
        got = _mensual(firma=firma, om=om, base=base)
        assert got == esperado, f"{nombre}: esperado {esperado:,}, obtuvo {got:,}"


def test_total_mensual_junio_2026():
    total = sum(_mensual(firma=f, om=o, base=b) for _, f, o, b, _ in TABLA_JUNIO_2026)
    assert total == TOTAL_ESPERADO, f"total {total:,} != {TOTAL_ESPERADO:,}"


# ── 7 tests nombrados requeridos ─────────────────────────────────────────────

def test_uruaco_usa_om_dos_aniversarios():
    # firma(2022) < om(2023) → fecha_base = om (2023-11-15). Aniversarios
    # cumplidos al 30-jun-2026: 2024-11-15 y 2025-11-15 (el de 2026-11-15
    # todavía no llega) → 2 indexaciones, no 3.
    f = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000)
    assert f["n_indexaciones"] == 2
    assert f["valor_calculado"] == 4_598_502


def test_la_paz_vallenata_usa_firma_un_aniversario():
    # firma(2024-08-23) > om(2024-08-13) → fecha_base = firma. Su aniversario
    # 2025-08-23 ya llegó, pero el de 2026-08-23 todavía no (agosto es
    # posterior a junio) → 1 indexación, no 2.
    f = _calc(firma="2024-08-23", om="2024-08-13", base=48_000_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 4_208_000


def test_esmeralda_usa_om_un_ipc():
    # fecha_base = om (2025-02-26). Su aniversario 2026-02-26 ya llegó (feb <
    # junio) → 1 indexación — coincide con la regla vieja en este caso porque
    # el aniversario cae antes de junio.
    f = _calc(firma="2024-08-23", om="2025-02-26", base=48_000_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 4_204_000


def test_san_diego_sur_aun_no_llega_su_aniversario():
    # fecha_base = om (2025-10-30). Su aniversario real es 2026-10-30 — no ha
    # llegado en el período de junio-2026 → 0 indexaciones (la regla vieja
    # indexaba igual desde el 1-enero-2026, sin esperar al aniversario real).
    f = _calc(firma="2025-10-20", om="2025-10-30", base=54_000_000)
    assert f["n_indexaciones"] == 0
    assert f["factor_acumulado"] == 1.0
    assert f["valor_calculado"] == 4_500_000


def test_merengue_primer_aniversario_factor_uno():
    # firma 2026-03-18 → su primer aniversario (2027-03-18) es muy posterior
    # a cualquier período de 2026 → sin aniversarios cumplidos → factor 1.0.
    f = _calc(firma="2026-03-18", om="2025-04-16", base=54_000_000)
    assert f["n_indexaciones"] == 0
    assert f["factor_acumulado"] == 1.0
    assert f["valor_calculado"] == 4_500_000


def test_la_reserva_usa_firma_un_ipc():
    # fecha_base = firma (2025-05-10). Su aniversario 2026-05-10 ya llegó
    # (mayo < junio) → 1 indexación — coincide con la regla vieja en este caso.
    f = _calc(firma="2025-05-10", om="2025-04-25", base=36_880_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 3_230_073


def test_perija_fallback_a_firma_un_aniversario():
    # sin fecha_inicio_om → fallback a firma (2024-08-23). Aniversario
    # 2025-08-23 ya llegó, el de 2026-08-23 todavía no → 1 indexación, no 2.
    f = _calc(firma="2024-08-23", om=None, base=48_000_000)
    assert f["n_indexaciones"] == 1
    assert f["valor_calculado"] == 4_208_000


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
    assert f["valor_calculado"] == 4_598_502


def test_override_none_equivale_a_sin_override():
    a = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000, valor_manual=None)
    b = _calc(firma="2022-09-10", om="2023-11-15", base=48_000_000)
    assert a == b
