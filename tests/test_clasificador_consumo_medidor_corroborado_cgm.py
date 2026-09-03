"""_decidir_medidor_o_historico() -- el CGM como testigo del MEDIDOR cuando
no hay mediana histórica con qué validarlo (frontera nueva).

Es el cruce de `_veredicto_medidor_vs_cgm` en la dirección contraria: allá la
lectura a respaldar es la del CGM y el testigo es el medidor; acá la lectura a
respaldar es la del medidor y el testigo es el CGM.

Cierra una asimetría real: la rama CGM sin mediana pregunta al otro canal
antes de marcar revisión, pero la rama Medidor sin mediana marcaba revisión
siempre, sin preguntarle nada a nadie -- ni siquiera cuando había un valor de
CGM a mano. Se llega a esa rama porque el CGM no servía como FUENTE (status no
automático, o e_cgm en 0), pero un status no automático no quiere decir que el
valor esté mal: solo que el trámite de Quoia hacia el ASIC no se completó
(mismo razonamiento que los Casos 9/10 de Generación).

Las cuatro filas del snapshot de agosto 2026 que tenían un CGM disponible en
esta rama muestran por qué el criterio tiene que ser la corroboración y no el
`estado_reporte`:

    frontera                  fecha        estado    medidor     CGM   dif
    MGS 0032 El Paso Norte    2026-08-06   WARNING     33,35   60,72   45%
    MGS 0032 El Paso Norte    2026-08-07   WARNING     33,35   66,70   50%
    MGS 0032 El Paso Norte    2026-08-08   WARNING     31,62   63,25   50%
    MGS 0022 La Cumbia        2026-08-20   PENDING     28,86   28,86    0%

Confiar porque el `estado_reporte` es automático habría aceptado las tres
filas de Paso Norte -- justo las del CGM doblado (WARNING está dentro de
ESTADOS_AUTOMATICO). Confiar porque otro canal corrobora acierta en las
cuatro: rescata La Cumbia de una revisión innecesaria y deja las de Paso Norte
marcadas.
"""
from datetime import date

import pandas as pd
import pytest

import app.services.reporte_energia.clasificador_consumo as mod

FECHA = date(2026, 8, 20)


def _curva(total: float, horas_con_dato: int = 24) -> pd.Series:
    valores = [total / horas_con_dato] * horas_con_dato + [None] * (24 - horas_con_dato)
    return pd.Series(valores, index=mod.HORAS, dtype=float)


def _curvas(ppal=None, resp=None, ppal_completo=True, resp_completo=True) -> dict:
    vacia = pd.Series([None] * 24, index=mod.HORAS, dtype=float)
    return {
        "consumo_ppal": ppal if ppal is not None else vacia,
        "consumo_resp": resp if resp is not None else vacia,
        "consumo_ppal_completo": ppal_completo and ppal is not None,
        "consumo_resp_completo": resp_completo and resp is not None,
        "recuperacion_datos": None,
    }


@pytest.fixture(autouse=True)
def sin_mediana(monkeypatch):
    """Toda esta rama existe solo cuando no hay mediana histórica."""
    monkeypatch.setattr(mod.historial, "get_mediana_consumo", lambda db, fid, f: (None, 0))
    monkeypatch.setattr(mod.historial, "get_forma_consumo", lambda db, fid, f: (None, 0))


def _decidir(c, e_cgm, estado="PENDING"):
    return mod._decidir_medidor_o_historico(
        db=None, frontera_id=44, fecha=FECHA, e_cgm=e_cgm, estado_reporte=estado, c=c,
    )


def test_cgm_corrobora_un_solo_medidor_no_marca_revision():
    """La Cumbia 2026-08-20: medidor 28,86 y CGM 28,86, status PENDING."""
    resultado = _decidir(_curvas(ppal=_curva(28.86)), e_cgm=28.86)

    assert resultado["caso"] == "Medidor"
    assert resultado["medidor_usado"] == "principal_sin_historico"
    assert resultado["revisar_manualmente"] is False, (
        "dos canales independientes dicen lo mismo -- no hay nada que revisar a mano"
    )


def test_cgm_doblado_no_corrobora_y_la_revision_queda():
    """Paso Norte 2026-08-07: medidor 33,35 y CGM 66,70, status WARNING
    (automático). El status solo no puede ser el criterio."""
    resultado = _decidir(_curvas(ppal=_curva(33.35)), e_cgm=66.70, estado="WARNING")

    assert resultado["revisar_manualmente"] is True
    assert resultado["energia_final_kwh"] == pytest.approx(33.35), "se reporta el medidor, no el CGM"


def test_sin_cgm_disponible_la_revision_queda():
    """El caso mayoritario: 82 de las 86 filas sin historial no tienen ningún
    CGM con qué cruzar."""
    resultado = _decidir(_curvas(ppal=_curva(28.86)), e_cgm=0.0)

    assert resultado["revisar_manualmente"] is True


def test_medidor_incompleto_no_se_puede_corroborar():
    """Sumar lo mismo con 12 de 24 horas es casualidad, no confirmación."""
    resultado = _decidir(_curvas(ppal=_curva(28.86, horas_con_dato=12), ppal_completo=False), e_cgm=28.86)

    assert resultado["revisar_manualmente"] is True


def test_cgm_corrobora_con_dos_medidores_parecidos():
    """Dos medidores con diferencia chica -- se prefiere el principal (regla
    ya existente) y el CGM lo respalda."""
    resultado = _decidir(_curvas(ppal=_curva(28.86), resp=_curva(27.0)), e_cgm=28.86)

    assert resultado["medidor_usado"] == "principal_sin_historico"
    assert resultado["revisar_manualmente"] is False


def test_cgm_corrobora_con_dos_medidores_muy_distintos():
    """Diferencia alta entre medidores -- se prefiere el de mayor valor (regla
    ya existente, Baraya AUX) y acá el CGM confirma que era el correcto."""
    resultado = _decidir(_curvas(ppal=_curva(4.0), resp=_curva(28.86)), e_cgm=28.86)

    assert resultado["medidor_usado"] == "respaldo_sin_historico"
    assert resultado["revisar_manualmente"] is False


def test_cgm_no_rescata_al_medidor_que_no_se_eligio():
    """El CGM coincide con el respaldo, pero la regla de diferencia alta ya
    eligió el principal por ser mayor. No se cambia la elección acá -- solo se
    pregunta si el elegido está respaldado, y no lo está."""
    resultado = _decidir(_curvas(ppal=_curva(50.0), resp=_curva(28.86)), e_cgm=28.86)

    assert resultado["medidor_usado"] == "principal_sin_historico"
    assert resultado["revisar_manualmente"] is True
