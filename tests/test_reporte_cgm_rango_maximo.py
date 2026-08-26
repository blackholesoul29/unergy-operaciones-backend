"""EnviarReporteCGMRequest -- tope de rango de fechas (RANGO_MAXIMO_DIAS).

Sin esto, un rango de meses/años multiplicado por "Operaciones Unergy"
(~300 fronteras, ver CLIENTES_TODAS_LAS_FRONTERAS) puede disparar cientos
de llamadas paginadas a Quoia y armar un Excel/correo gigante sin ningún
guardrail del lado del servidor (auditoría CGM 2026-08-26, finding #5)."""
from datetime import date, timedelta

import pytest

from app.schemas.reporte_cgm import EnviarReporteCGMRequest, RANGO_MAXIMO_DIAS


def test_un_solo_dia_es_valido():
    req = EnviarReporteCGMRequest(fecha_inicio=date(2026, 8, 25), fecha_fin=date(2026, 8, 25), destinatarios=[])
    assert req.fecha_inicio == req.fecha_fin


def test_rango_justo_en_el_limite_es_valido():
    inicio = date(2026, 1, 1)
    fin = inicio + timedelta(days=RANGO_MAXIMO_DIAS - 1)  # RANGO_MAXIMO_DIAS días inclusive
    req = EnviarReporteCGMRequest(fecha_inicio=inicio, fecha_fin=fin, destinatarios=[])
    assert req.fecha_fin == fin


def test_rango_que_excede_el_limite_es_rechazado():
    inicio = date(2026, 1, 1)
    fin = inicio + timedelta(days=RANGO_MAXIMO_DIAS)  # un día de más
    with pytest.raises(ValueError, match="no puede superar"):
        EnviarReporteCGMRequest(fecha_inicio=inicio, fecha_fin=fin, destinatarios=[])


def test_rango_invertido_tambien_se_valida_por_su_tamano():
    """fecha_fin < fecha_inicio se corrige más adelante en el endpoint
    (swap), pero el validador debe rechazar un rango grande sin importar
    el orden en que llegaron las fechas."""
    inicio = date(2026, 1, 1)
    fin = inicio + timedelta(days=RANGO_MAXIMO_DIAS)
    with pytest.raises(ValueError, match="no puede superar"):
        EnviarReporteCGMRequest(fecha_inicio=fin, fecha_fin=inicio, destinatarios=[])
