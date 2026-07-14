import pytest
from datetime import date
from app.services.xm.plan_descarga import construir_plan_descarga


def test_plan_diario_un_solo_mes():
    plan = construir_plan_descarga("grip", "txf", date(2026, 5, 1), date(2026, 5, 3))
    assert [p["nombre_archivo"] for p in plan] == ["grip0501.txf", "grip0502.txf", "grip0503.txf"]
    assert plan[0]["fecha_documento"] == "2026-05-01"
    assert plan[0]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_plan_diario_cruza_meses():
    plan = construir_plan_descarga("grip", "txf", date(2026, 4, 29), date(2026, 5, 2))
    nombres = [p["nombre_archivo"] for p in plan]
    assert nombres == ["grip0429.txf", "grip0430.txf", "grip0501.txf", "grip0502.txf"]
    assert plan[0]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-04"
    assert plan[-1]["directorio"] == "/INFORMACION_XM/PUBLICOK/SIC/COMERCIA/2026-05"


def test_plan_mensual_cxcsb():
    plan = construir_plan_descarga("cxcsb", "txf", date(2026, 3, 15), date(2026, 5, 20))
    assert [p["nombre_archivo"] for p in plan] == ["cxcsb03.txf", "cxcsb04.txf", "cxcsb05.txf"]
    assert [p["fecha_documento"] for p in plan] == ["2026-03", "2026-04", "2026-05"]


def test_fecha_fin_antes_de_inicio_lanza():
    with pytest.raises(ValueError):
        construir_plan_descarga("grip", "txf", date(2026, 5, 10), date(2026, 5, 1))
