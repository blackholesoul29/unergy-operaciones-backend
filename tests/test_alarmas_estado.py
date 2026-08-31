"""Tests de la decisión pura de anti-spam compartida (app.services.alarmas.estado),
sin BD -- decidir_notificar() solo lee/escribe el cache y la lista de pendientes
que se le pasan."""
from datetime import date, timedelta

from app.services.alarmas.estado import decidir_notificar

HOY = date(2026, 8, 31)
AYER = HOY - timedelta(days=1)


def test_primera_vez_no_ok_notifica():
    cache, pending = {}, []
    notify, recovery = decidir_notificar(cache, pending, 1, "runtime", "sin_datos", HOY)
    assert notify is True
    assert recovery is False
    assert pending == [{"p": 1, "c": "runtime", "e": "sin_datos", "d": HOY}]
    assert cache[(1, "runtime")] == ("sin_datos", HOY)


def test_primera_vez_ok_no_notifica():
    """Nunca hubo alarma y el estado nuevo ya es 'ok' -- nada que avisar."""
    cache, pending = {}, []
    notify, recovery = decidir_notificar(cache, pending, 1, "runtime", "ok", HOY)
    assert notify is False
    assert pending == []


def test_mismo_estado_mismo_dia_no_reavisa():
    cache = {(1, "runtime"): ("sin_datos", HOY)}
    pending = []
    notify, _ = decidir_notificar(cache, pending, 1, "runtime", "sin_datos", HOY)
    assert notify is False
    assert pending == []


def test_mismo_estado_persiste_dia_distinto_reavisa():
    """Re-aviso diario: mismo estado, pero la última vez fue ayer."""
    cache = {(1, "runtime"): ("sin_datos", AYER)}
    pending = []
    notify, recovery = decidir_notificar(cache, pending, 1, "runtime", "sin_datos", HOY)
    assert notify is True
    assert recovery is False
    assert pending == [{"p": 1, "c": "runtime", "e": "sin_datos", "d": HOY}]


def test_cambia_a_ok_es_recuperacion():
    cache = {(1, "runtime"): ("sin_datos", HOY)}
    pending = []
    notify, recovery = decidir_notificar(cache, pending, 1, "runtime", "ok", HOY)
    assert notify is True
    assert recovery is True
    # dia queda en None para un estado 'ok' -- no aplica el re-aviso diario
    assert pending == [{"p": 1, "c": "runtime", "e": "ok", "d": None}]
    assert cache[(1, "runtime")] == ("ok", None)


def test_reactivacion_el_mismo_dia_tras_recuperacion_si_notifica():
    """El caso que fallaba antes de compartir este módulo (ver auditoría
    2026-08-31 en fallas/alarmas.py): una alarma se resuelve (pasa a 'ok')
    y se vuelve a activar el MISMO día -- debe notificar de nuevo, no
    quedar en silencio hasta el día siguiente."""
    cache, pending = {}, []
    # 1) se activa en la mañana
    decidir_notificar(cache, pending, 1, "comunicacion_frontera", "activa", HOY)
    # 2) se resuelve al mediodía
    decidir_notificar(cache, pending, 1, "comunicacion_frontera", "ok", HOY)
    # 3) se vuelve a activar en la tarde, mismo día
    notify, recovery = decidir_notificar(cache, pending, 1, "comunicacion_frontera", "activa", HOY)
    assert notify is True
    assert recovery is False
    assert pending[-1] == {"p": 1, "c": "comunicacion_frontera", "e": "activa", "d": HOY}
