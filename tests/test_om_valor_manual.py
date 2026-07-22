"""Fix #6: si un valor_manual (override) difiere del valor recalculado —p.ej.
tras corregir la tasa IPC—, marcarlo con el flag valor_manual_desactualizado."""
from datetime import date

from app.services.om_calculator import calcular_proyecto


def _calc(valor_manual):
    # Firma 2026-01-01, período 2026-06 → sin aniversarios (factor 1.0), sin IPC:
    # valor_calculado = 48_000_000 / 12 = 4_000_000 (mes completo).
    return calcular_proyecto(
        contrato_id=1, nombre_proyecto="Demo",
        fecha_firma_contrato=date(2026, 1, 1), fecha_inicio_om=None,
        valor_base_anual=48_000_000, periodo="2026-06", ipc_tasas={},
        valor_manual=valor_manual,
    )


def test_sin_override_no_desactualizado():
    assert _calc(None)["valor_manual_desactualizado"] is False


def test_override_igual_al_calculado_no_desactualizado():
    assert _calc(4_000_000)["valor_manual_desactualizado"] is False


def test_override_distinto_del_calculado_desactualizado():
    # El override (3.5M) ya no coincide con el cálculo (4M) → aviso.
    r = _calc(3_500_000)
    assert r["editado_manual"] is True
    assert r["valor_a_facturar"] == 3_500_000     # sigue respetando el override
    assert r["valor_manual_desactualizado"] is True
