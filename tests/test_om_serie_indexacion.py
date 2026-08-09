"""Serie de indexación automática (Proyecto>Servicios>Operación>Mantenimiento).

Misma regla que el panel de Costos: aniversario real + IPC por año, solo
aniversarios cumplidos. El último valor mensual de la serie debe coincidir con
el valor_calculado de calcular_proyecto para el mismo período."""
from datetime import date
from app.services.om_calculator import serie_indexacion

IPC = {2024: 0.0928, 2025: 0.0520, 2026: 0.0510}


def test_serie_uruaco_dos_aniversarios():
    # fecha_base = om 2023-11-15; hasta jun-2026 → aniversarios 2024 y 2025.
    s = serie_indexacion(date(2023, 11, 15), 48_000_000, IPC, 2026, 6)
    anios = [f["anio"] for f in s]
    assert anios == [2023, 2024, 2025]
    assert s[0]["ipc_aplicado"] is None
    assert s[0]["valor_anual"] == 48_000_000
    assert s[1]["ipc_aplicado"] == 9.28
    # último valor mensual == valor_calculado de Costos para Uruaco jun-2026
    assert s[-1]["valor_mensual"] == 4_598_502


def test_serie_sin_firma_pero_con_om():
    # El Son: om 2025-02-16, sin firma → 1 aniversario (2026) cumplido en jun-2026.
    s = serie_indexacion(date(2025, 2, 16), 48_000_000, IPC, 2026, 6)
    assert [f["anio"] for f in s] == [2025, 2026]
    assert s[-1]["ipc_aplicado"] == 5.10
    assert s[-1]["valor_mensual"] == 4_204_000


def test_serie_aniversario_no_cumplido_solo_base():
    # om 2025-10-30: en jun-2026 su aniversario (2026-10-30) aún no llega → solo base.
    s = serie_indexacion(date(2025, 10, 30), 54_000_000, IPC, 2026, 6)
    assert len(s) == 1
    assert s[0]["anio"] == 2025
    assert s[0]["valor_mensual"] == 4_500_000


def test_serie_vacia_sin_fecha_o_sin_valor():
    assert serie_indexacion(None, 48_000_000, IPC, 2026, 6) == []
    assert serie_indexacion(date(2024, 1, 1), None, IPC, 2026, 6) == []
