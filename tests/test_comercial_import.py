"""Semilla de prospección del CRM (data/comercial_seed.json).

Este archivo probaba `comercial.importar_hojas`, el endpoint
`POST /comercial/importar-hojas` de la migración inicial del CRM. Ese endpoint
se eliminó a propósito (commit 4385152, "Eliminar POST /comercial/importar-hojas
(migracion inicial del CRM)") pero los tests se quedaron, y desde entonces
fallaban con `AttributeError: module 'app.api.v1.comercial' has no attribute
'importar_hojas'`, dejando CI en rojo.

Se eliminaron los seis tests que ejercitaban esa función. Uno de ellos,
`test_no_admin_rechazado`, venía pasando en verde por la razón equivocada: su
`pytest.raises(Exception)` atrapaba el AttributeError de la función inexistente,
así que reportaba éxito sin probar nada.

Sobrevive la validación de la semilla, que sigue siendo relevante: `app/main.py`
lee `data/comercial_seed.json` en el arranque.
"""
import json
from pathlib import Path


def test_seed_existe_y_bien_formada():
    data = json.loads(Path("data/comercial_seed.json").read_text(encoding="utf-8"))
    assert len(data) >= 150
    assert {"empresa", "tipo"} <= set(data[0].keys())
    assert {d["tipo"] for d in data} <= {
        "servicios_operacionales", "compra_energia", "comunidad_energetica"}
