"""Figura 'Uso del recurso': flags exclusivos y clasificación doble (a+c).

Una planta cuyo cliente está en bolsa pero que Unergy mete a un contrato para
cumplir (pagándole al cliente a precio bolsa) clasifica DOBLE: fila estándar en
(a) PPA Venta + fila espejo en (c) Compra en Bolsa con vendedor = el cliente.
Es distinta del duplicado clásico (compra real en bolsa), que solo vive en (c).
"""
import pytest
from fastapi import HTTPException


def test_flags_exclusivos_rechaza_ambos_true():
    from app.api.v1.asic import _validar_flags_exclusivos
    with pytest.raises(HTTPException) as exc:
        _validar_flags_exclusivos(es_duplicado=True, uso_del_recurso=True)
    assert exc.value.status_code == 422


def test_flags_exclusivos_acepta_combinaciones_validas():
    from app.api.v1.asic import _validar_flags_exclusivos
    _validar_flags_exclusivos(True, False)
    _validar_flags_exclusivos(False, True)
    _validar_flags_exclusivos(False, False)
