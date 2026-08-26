"""curva_respaldo_a_reportar() / actualizar_respaldo_final() (utils.py).

Hasta ahora /enviar SIEMPRE estimaba el "Backup" con una fórmula ±1% sobre
curva_final, aunque para fronteras normales (no terceros) ya tuviéramos el
dato REAL del medidor de respaldo guardado (curva_medidor_respaldo) y fuera
válido -- mala práctica reportando estimado teniendo el dato real (pedido
2026-08-25).

Ahora se usa el dato real del medidor de respaldo cuando: curva_final vino
del medidor principal (medidor_usado empieza con 'principal'), ambos
medidores quedaron completos ese día, y el respaldo está a
TOLERANCIA_RESPALDO_REAL_KWH (1.5 kWh, la peor de las 24 horas) o menos de
diferencia -- umbral confirmado con el equipo de campo y contrastado contra
el histórico real. Si no, sigue cayendo al ±1% de siempre.

Matriz de medidor_usado verificada contra clasificador.py/
clasificador_consumo.py/editar_curva (grep exhaustivo 2026-08-25): SOLO
'principal' y 'principal_sin_cgm' deben activar el camino 'medidor' -- todo
lo demás (cgm, respaldo, respaldo_sin_cgm, revisar, inversores,
reconectador, solenium_power, ninguno, crudos, crudos_parcial, externo,
relleno_horario, excluida, excel_terceros, historico, editado_manualmente)
debe seguir cayendo al ±1%."""
from types import SimpleNamespace

import pytest

from app.services.reporte_energia.utils import (
    curva_respaldo_a_reportar, actualizar_respaldo_final, TOLERANCIA_RESPALDO_REAL_KWH,
)


def _rep(**kw):
    base = dict(
        curva_final=[100.0] * 24,
        medidor_usado="principal",
        curva_respaldo_terceros=None,
        medidor_principal_completo=True,
        medidor_respaldo_completo=True,
        curva_medidor_respaldo=[100.0] * 24,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_terceros_gana_siempre_sin_importar_medidor_usado():
    rep = _rep(medidor_usado="cgm", curva_respaldo_terceros=[9.9] * 24)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "terceros"
    assert curva == [9.9] * 24


def test_medidor_respaldo_real_cuando_coincide_dentro_de_tolerancia():
    rep = _rep(curva_final=[100.0] * 24, curva_medidor_respaldo=[101.0] * 24)  # 1 kWh de diferencia
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "medidor"
    assert curva == [101.0] * 24


def test_medidor_respaldo_en_el_limite_exacto_de_tolerancia_pasa():
    dif = TOLERANCIA_RESPALDO_REAL_KWH
    rep = _rep(curva_final=[100.0] * 24, curva_medidor_respaldo=[100.0 + dif] * 24)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "medidor"


def test_medidor_respaldo_fuera_de_tolerancia_cae_a_estimado():
    dif = TOLERANCIA_RESPALDO_REAL_KWH + 0.01
    rep = _rep(curva_final=[100.0] * 24, curva_medidor_respaldo=[100.0 + dif] * 24)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"
    # Estimado ±1% sobre 100 -> entre 99 y 101
    assert all(99.0 <= v <= 101.0 for v in curva)


def test_una_sola_hora_fuera_de_tolerancia_ya_descarta_el_dia_completo():
    """max_dif es la PEOR de las 24 horas, no el total ni el promedio --
    una sola hora mal ya es motivo para no confiar en el medidor ese día."""
    curva_resp = [100.0] * 23 + [200.0]  # 1 hora con 100 kWh de diferencia
    rep = _rep(curva_final=[100.0] * 24, curva_medidor_respaldo=curva_resp)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"


@pytest.mark.parametrize("medidor_usado", [
    "cgm", "respaldo", "respaldo_sin_cgm", "revisar", "inversores", "reconectador",
    "solenium_power", "ninguno", "crudos", "crudos_parcial", "externo",
    "relleno_horario", "excluida", "excel_terceros", "historico", "editado_manualmente",
])
def test_solo_principal_activa_el_camino_medidor_el_resto_cae_a_estimado(medidor_usado):
    rep = _rep(medidor_usado=medidor_usado, curva_final=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado", f"{medidor_usado!r} no deberia activar el camino 'medidor'"


@pytest.mark.parametrize("medidor_usado", ["principal", "principal_sin_cgm"])
def test_las_dos_variantes_de_principal_si_activan_el_camino_medidor(medidor_usado):
    rep = _rep(medidor_usado=medidor_usado, curva_final=[100.0] * 24, curva_medidor_respaldo=[100.0] * 24)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "medidor"


def test_medidor_principal_incompleto_cae_a_estimado_aunque_respaldo_coincida():
    rep = _rep(medidor_principal_completo=False)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"


def test_medidor_respaldo_incompleto_cae_a_estimado_aunque_principal_coincida():
    rep = _rep(medidor_respaldo_completo=False)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"


def test_sin_curva_medidor_respaldo_cae_a_estimado():
    rep = _rep(curva_medidor_respaldo=None)
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"


def test_objeto_tipo_consumo_sin_los_campos_nuevos_no_revienta():
    """ReporteEnergiaConsumo no tiene medidor_*_completo/curva_respaldo_terceros
    -- getattr con default debe caer a estimado sin lanzar AttributeError."""
    rep = SimpleNamespace(curva_final=[50.0] * 24, medidor_usado="principal")
    curva, origen = curva_respaldo_a_reportar(rep)
    assert origen == "estimado"
    assert len(curva) == 24


def test_actualizar_respaldo_final_persiste_en_el_objeto():
    rep = _rep(curva_final=[100.0] * 24, curva_medidor_respaldo=[100.5] * 24)
    actualizar_respaldo_final(rep)
    assert rep.respaldo_final_origen == "medidor"
    assert rep.curva_respaldo_final == [100.5] * 24
