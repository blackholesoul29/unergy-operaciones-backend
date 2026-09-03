"""clasificar_consumo() -- el CGM que reportó genuinamente 0.

`cgm_ok = reporte_valido and e_cgm > 0` hacía que un cero real del canal
oficial nunca pudiera ser Caso 'CGM'. Caía al Camino 2 con la energía en 0 y,
si la mediana histórica de la frontera era distinta de 0, ese 0 quedaba fuera
de rango -- así que terminaba en Caso 'Histórico' **reportando la estimación**
en un día en el que el CGM decía 0, o en 'Sin dato' sin reportar nada.

Las filas del snapshot de agosto 2026 con estado automático y CGM en 0 que
mostraron el problema:

    MINIGRANJA LA PAZ VALLENATA SER AUX  2026-08-15  WARNING  -> 36,54 kWh
    MGS 0025 El Copey Occidente Consumo  2026-08-24  WARNING  -> 28,75 kWh
    MINIGRANJA LA PAZ VALLENATA SER AUX  2026-08-28  WARNING  -> 36,81 kWh
    GD Garza Consumo                     2026-08-28  OK       -> 'Sin dato'
    GD Garza Consumo                     2026-08-29  OK       -> 'Sin dato'
    GD Garza Consumo                     2026-08-30  OK       -> 'Sin dato'

GD Garza es la misma frontera que motivó el Caso 5 de Generación (2026-09-02):
el mismo agujero, del lado de Consumo, que aquel arreglo no cubrió.

`cgm_tiene_dato` es lo que separa "el canal trajo 24 horas reales que suman 0"
de "Quoia no respondió" -- ambos colapsan a e_cgm = 0 pero solo el primero es
un dato.

A diferencia de Generación, acá el 0 se cruza contra el medidor antes de
aceptarlo: un 0 de consumo diario afirma que el sitio no tomó nada de la red
en 24 horas, ni de madrugada, o sea que estuvo apagado. Un 0 de generación
diario, en cambio, es normal (día nublado, planta detenida).
"""
from datetime import date

import pandas as pd
import pytest

import app.services.reporte_energia.clasificador_consumo as mod

FECHA = date(2026, 8, 28)


class _Gaia:
    """`datos` = lo que trae reported_data_main; None = Quoia no respondió."""

    def __init__(self, datos, status="OK", sin_reporte=False):
        self._datos = datos
        self._status = status
        self._sin_reporte = sin_reporte

    def get_border_report_status(self, border_id, fecha_str):
        if self._sin_reporte:
            return None
        reporte = {"status": self._status}
        if self._datos is not None:
            reporte["reported_data_main"] = self._datos
        return reporte


def _curva(total: float, horas_con_dato: int = 24) -> pd.Series:
    valores = [total / horas_con_dato] * horas_con_dato + [None] * (24 - horas_con_dato)
    return pd.Series(valores, index=mod.HORAS, dtype=float)


def _curvas(ppal=None, resp=None) -> dict:
    vacia = pd.Series([None] * 24, index=mod.HORAS, dtype=float)
    return {
        "consumo_ppal": ppal if ppal is not None else vacia,
        "consumo_resp": resp if resp is not None else vacia,
        "consumo_ppal_completo": ppal is not None,
        "consumo_resp_completo": resp is not None,
        "recuperacion_datos": None,
    }


@pytest.fixture
def espia(monkeypatch):
    llamadas = []

    def _fake(*args, **kwargs):
        llamadas.append(True)
        return espia.curvas

    monkeypatch.setattr(mod.curvas, "curvas_de_frontera", _fake)
    espia.llamadas = llamadas
    espia.curvas = _curvas()
    return espia


def _clasificar(gaia, mediana, monkeypatch, forma=None):
    monkeypatch.setattr(mod.historial, "get_mediana_consumo", lambda db, fid, f: (mediana, 20))
    monkeypatch.setattr(mod.historial, "get_forma_consumo", lambda db, fid, f: (forma, 20))
    return mod.clasificar_consumo(
        db=None, gaia=gaia, frontera_id=133, frt_code="frt00133",
        border_meta={"border_id": 1, "main_meter": 10, "backup_meter": 11},
        mapa_medidor_nodo={10: 100, 11: 101}, fecha=FECHA,
    )


def test_cero_genuino_corroborado_por_el_medidor_es_caso_cgm(espia, monkeypatch):
    """El sitio estuvo apagado y los dos canales lo dicen."""
    espia.curvas = _curvas(ppal=_curva(0.0), resp=_curva(0.0))
    resultado = _clasificar(_Gaia([0.0] * 24), mediana=30.0, monkeypatch=monkeypatch)

    assert resultado["caso"] == "CGM", "un 0 real del canal oficial es un dato, no ausencia de dato"
    assert resultado["energia_final_kwh"] == 0.0
    assert resultado["medidor_usado"] == "cgm", "medidor_usado 'cgm' es lo que suprime la matriz a Quoia"
    assert not resultado.get("revisar_manualmente"), "el medidor confirma el apagado"


def test_cero_genuino_no_termina_reportando_la_mediana(espia, monkeypatch):
    """LA PAZ VALLENATA 2026-08-28: antes se reportaban 36,81 kWh inventados
    porque el 0 quedaba fuera del rango de una mediana de ~36."""
    forma = pd.Series([1 / 24] * 24, index=mod.HORAS, dtype=float)
    espia.curvas = _curvas(ppal=_curva(0.0))
    resultado = _clasificar(_Gaia([0.0] * 24), mediana=36.81, monkeypatch=monkeypatch, forma=forma)

    assert resultado["caso"] != "Histórico", "no se fabrica consumo en un día que el CGM reportó en 0"
    assert resultado["energia_final_kwh"] == 0.0


def test_cero_genuino_sin_medidor_que_confirme_se_reporta_pero_se_marca(espia, monkeypatch):
    """GD Garza: antes quedaba en 'Sin dato' sin reportar nada. Ahora se
    reporta el 0 del canal oficial, pero nadie confirmó el apagado."""
    espia.curvas = _curvas()
    resultado = _clasificar(_Gaia([0.0] * 24), mediana=None, monkeypatch=monkeypatch)

    assert resultado["caso"] == "CGM"
    assert resultado["energia_final_kwh"] == 0.0
    assert resultado["revisar_manualmente"] is True, (
        "24 horas sin tomar nada de la red es una afirmación fuerte -- sin testigo, que la mire alguien"
    )


def test_medidor_con_consumo_real_desmiente_el_cero(espia, monkeypatch):
    """El medidor midió 28 kWh: el 0 del CGM es un hueco disfrazado de dato."""
    espia.curvas = _curvas(ppal=_curva(28.0))
    resultado = _clasificar(_Gaia([0.0] * 24), mediana=28.0, monkeypatch=monkeypatch)

    assert resultado["caso"] == "Medidor", "no se acepta un 0 que el medidor contradice"
    assert resultado["energia_final_kwh"] == pytest.approx(28.0)
    assert len(espia.llamadas) == 1, "el Camino 2 reusa las curvas que ya se pidieron para juzgar el 0"


def test_quoia_sin_reported_data_main_no_es_un_cero_genuino(espia, monkeypatch):
    """Estado automático pero el canal no trajo nada: eso es ausencia de dato,
    y tiene que seguir cayendo al medidor."""
    espia.curvas = _curvas(ppal=_curva(28.0))
    resultado = _clasificar(_Gaia(None), mediana=28.0, monkeypatch=monkeypatch)

    assert resultado["caso"] == "Medidor"
    assert resultado["energia_final_kwh"] == pytest.approx(28.0)


def test_quoia_no_respondio_no_es_un_cero_genuino(espia, monkeypatch):
    espia.curvas = _curvas(ppal=_curva(28.0))
    resultado = _clasificar(_Gaia(None, sin_reporte=True), mediana=28.0, monkeypatch=monkeypatch)

    assert resultado["caso"] == "Medidor"


def test_estado_no_automatico_no_habilita_el_cero_genuino(espia, monkeypatch):
    """Un ERROR2 con 24 ceros no alcanza: el trámite no se completó, así que
    el 0 no está avalado por nadie."""
    espia.curvas = _curvas(ppal=_curva(28.0))
    resultado = _clasificar(_Gaia([0.0] * 24, status="ERROR2"), mediana=28.0, monkeypatch=monkeypatch)

    assert resultado["caso"] == "Medidor"


def test_residuo_de_medicion_cuenta_como_cero():
    """0,2 kWh en un día entero no es "consumir poquísimo", es estar apagado --
    exigir el 0,0 exacto rompería la corroboración por un residuo."""
    assert mod._es_cero(_curva(0.2)) is True
    assert mod._es_cero(_curva(0.0)) is True
    assert mod._es_cero(_curva(5.0)) is False
