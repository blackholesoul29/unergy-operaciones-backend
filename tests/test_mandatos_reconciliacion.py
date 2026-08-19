"""Reconciliación por conteo -- lógica pura, sin BD.

Responde "de los N que se enviaron, cuáles no han vuelto". Es la capacidad que
hoy solo tiene el script local de Jessica, y la condición para retirarlo.
"""
from datetime import date
from types import SimpleNamespace as NS

from app.services.mandatos.reconciliacion import reconciliar

PERIODO = date(2026, 7, 1)


def _m(cmu, estado, enviado=True, firmado=False):
    return NS(cmu=cmu, estado=estado, periodo=PERIODO, tipo="costo",
              proyecto=f"Proyecto {cmu}", tercero="P.A X",
              fecha_envio=PERIODO if enviado else None,
              fecha_firma=PERIODO if firmado else None)


def test_todo_devuelto():
    filas = [_m("CMU1", "firmado", firmado=True), _m("CMU2", "firmado", firmado=True)]
    r = reconciliar(filas)
    assert r["enviados"] == 2
    assert r["devueltos"] == 2
    assert r["pendientes"] == []
    assert r["completo"] is True


def test_faltan_dos_y_dice_cuales():
    filas = [_m("CMU1", "firmado", firmado=True),
             _m("CMU2", "sin_firma"),
             _m("CMU3", "sin_firma")]
    r = reconciliar(filas)
    assert r["enviados"] == 3
    assert r["devueltos"] == 1
    assert sorted(r["pendientes"]) == ["CMU2", "CMU3"]
    assert r["completo"] is False


def test_con_comentarios_cuenta_como_devuelto_pero_se_lista_aparte():
    """Volvió, pero con observaciones: no está pendiente de retorno, sí de trabajo."""
    filas = [_m("CMU1", "con_comentarios")]
    r = reconciliar(filas)
    assert r["devueltos"] == 1
    assert r["pendientes"] == []
    assert r["con_comentarios"] == ["CMU1"]
    assert r["completo"] is True


def test_enviado_inversionista_tambien_es_devuelto():
    filas = [_m("CMU1", "enviado_inversionista", firmado=True)]
    r = reconciliar(filas)
    assert r["devueltos"] == 1
    assert r["completo"] is True


def test_una_fila_sin_fecha_envio_no_cuenta_como_enviada():
    """Si apareció sin haberse enviado, es una anomalía -- se reporta aparte
    en vez de inflar el denominador."""
    filas = [_m("CMU1", "firmado", enviado=False, firmado=True)]
    r = reconciliar(filas)
    assert r["enviados"] == 0
    assert r["sin_registro_de_envio"] == ["CMU1"]


def test_periodo_vacio():
    r = reconciliar([])
    assert r == {"enviados": 0, "devueltos": 0, "pendientes": [],
                 "con_comentarios": [], "sin_registro_de_envio": [],
                 "completo": True}
