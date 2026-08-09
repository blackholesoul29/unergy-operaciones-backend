"""Fix #5: un año sin tasa IPC no debe omitirse en silencio; debe verse en el
historial y marcarse con el flag ipc_incompleto."""
from datetime import date

from app.services.om_calculator import (
    calcular_proyecto, historial_indexaciones, ipc_incompleto, _aniversarios_cumplidos,
)


def _calc(ipc_tasas):
    # Firma 2023-06-15, período 2026-06 → aniversarios en 2024, 2025 y 2026.
    return calcular_proyecto(
        contrato_id=1, nombre_proyecto="Demo",
        fecha_firma_contrato=date(2023, 6, 15), fecha_inicio_om=None,
        valor_base_anual=48_000_000, periodo="2026-06", ipc_tasas=ipc_tasas,
    )


COMPLETO = {2024: 0.09, 2025: 0.06, 2026: 0.05}
FALTA_2025 = {2024: 0.09, 2026: 0.05}   # falta 2025


# ── flag ipc_incompleto ───────────────────────────────────────────────────────

def test_ipc_incompleto_true_si_falta_un_anio():
    assert _calc(FALTA_2025)["ipc_incompleto"] is True


def test_ipc_incompleto_false_si_estan_todos():
    assert _calc(COMPLETO)["ipc_incompleto"] is False


# ── función pura ipc_incompleto ───────────────────────────────────────────────

def test_ipc_incompleto_pura():
    aniv = _aniversarios_cumplidos(date(2023, 6, 15), 2026, 6)
    assert ipc_incompleto(aniv, FALTA_2025) is True
    assert ipc_incompleto(aniv, COMPLETO) is False


# ── historial visible ─────────────────────────────────────────────────────────

def test_historial_muestra_ano_faltante():
    h = _calc(FALTA_2025)["historial_indexaciones"]
    assert "2025" in h
    assert "⚠" in h
    assert "sin tasa" in h.lower()


def test_historial_completo_sin_advertencia():
    h = _calc(COMPLETO)["historial_indexaciones"]
    assert "⚠" not in h
    assert "parcial" not in h.lower()
