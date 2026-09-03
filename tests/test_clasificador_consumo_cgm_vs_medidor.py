"""clasificar_consumo() -- segunda validación del CGM contra el medidor del
día cuando el histórico no alcanza para respaldarlo solo: el total se salió
del rango, o no hay mediana todavía (frontera nueva).

El cruce contra el histórico detecta que el día se salió de lo normal, pero
no sabe si el raro es el día (consumo real distinto) o el dato (glitch de
Quoia). El medidor sí lo sabe: es el MISMO medidor físico leído por el canal
de monitoreo, un camino de telecomunicaciones independiente del canal CGM.

Los dos casos reales que motivan la regla, con lados opuestos:

  · Valencia Oriente Consumo -- CGM fuera del ±30% de su mediana, pero el
    medidor del día coincide con él: el día de verdad fue distinto. Antes
    quedaba en revisión manual sin razón; ahora pasa limpio.
  · Paso Norte Consumo -- CGM reporta intermitentemente el DOBLE del
    consumo real con el estado en OK/WARNING (bug de Quoia). El medidor lo
    contradice, así que el CGM se descarta y se reporta el medidor -- que
    además envía matriz de corrección a Quoia, algo que el Caso 'CGM' no
    hace. Esto reemplaza la lista VALIDAR_CGM_VS_MEDIDOR = {111} que
    existía por frontera.

Sin mediana el 'contradice' NO descarta el CGM, solo lo marca: no hay
tercero que arbitre cuál de los dos canales es el roto, y un medidor
"completo" puede venir doblado igual que el CGM (MGS 0032 El Paso Norte).

Un medidor INCOMPLETO no opina en ninguna dirección: lee de menos por
definición (le faltan horas), así que su diferencia contra el CGM no dice
nada del CGM.
"""
from datetime import date

import pandas as pd
import pytest

import app.services.reporte_energia.clasificador_consumo as mod

FECHA = date(2026, 9, 2)


class _GaiaFake:
    def __init__(self, total_cgm: float, status: str = "OK"):
        self._total = total_cgm
        self._status = status

    def get_border_report_status(self, border_id, fecha_str):
        return {"status": self._status, "reported_data_main": [self._total / 24] * 24}


def _curva(total: float, horas_con_dato: int = 24) -> pd.Series:
    """Curva plana que suma `total`, con las horas restantes en NaN."""
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


@pytest.fixture
def espia(monkeypatch):
    """Registra cada llamada a curvas_de_frontera -- el costo que la regla no
    debe pagar en el día normal."""
    llamadas = []

    def _fake(*args, **kwargs):
        llamadas.append(kwargs.get("mediana_referencia"))
        return espia.curvas

    monkeypatch.setattr(mod.curvas, "curvas_de_frontera", _fake)
    espia.llamadas = llamadas
    espia.curvas = _curvas()
    return espia


def _clasificar(gaia, mediana, monkeypatch, dias=20, forma=None):
    monkeypatch.setattr(mod.historial, "get_mediana_consumo", lambda db, fid, f: (mediana, dias))
    monkeypatch.setattr(mod.historial, "get_forma_consumo", lambda db, fid, f: (forma, dias))
    return mod.clasificar_consumo(
        db=None, gaia=gaia, frontera_id=111, frt_code="frt00111",
        border_meta={"border_id": 1, "main_meter": 10, "backup_meter": 11},
        mapa_medidor_nodo={10: 100, 11: 101}, fecha=FECHA,
    )


def test_cgm_en_rango_no_pide_los_medidores(espia, monkeypatch):
    """El día normal no paga ninguna llamada extra a Quoia."""
    resultado = _clasificar(_GaiaFake(26.0), 26.0, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert not resultado.get("revisar_manualmente")
    assert espia.llamadas == [], "dentro del ±30% la segunda validación no debe dispararse"


def test_sin_mediana_tambien_pregunta_al_medidor(espia, monkeypatch):
    """Frontera nueva: sin historial, el status de Quoia era el único
    respaldo del CGM -- y es justo lo que falla en los casos que motivaron la
    regla. El medidor del día sí puede respaldarlo."""
    espia.curvas = _curvas(ppal=_curva(26.0), resp=_curva(26.0))
    resultado = _clasificar(_GaiaFake(26.0), None, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert not resultado.get("revisar_manualmente"), "el medidor completo lo respalda"
    assert espia.llamadas == [None], "sin mediana no hay valor de referencia que pasar"


def test_sin_mediana_contradice_marca_pero_no_descarta_el_cgm(espia, monkeypatch):
    """Sin histórico no hay tercero que arbitre: un medidor 'completo' puede
    venir doblado igual que el CGM (MGS 0032 El Paso Norte). Se conserva el
    canal oficial y decide una persona."""
    espia.curvas = _curvas(ppal=_curva(13.0), resp=_curva(13.0))
    resultado = _clasificar(_GaiaFake(26.0), None, monkeypatch)

    assert resultado["caso"] == "CGM", "sin mediana no se puede preferir el medidor sin evidencia"
    assert resultado["energia_final_kwh"] == pytest.approx(26.0)
    assert resultado["revisar_manualmente"] is True, "dos canales independientes en desacuerdo y nadie arbitra"


def test_sin_mediana_sin_medidor_no_marca_nada(espia, monkeypatch):
    """Frontera nueva sin telemetría de nodo: marcar todo lo que arranca sin
    historial es justo lo que se quitó el 2026-09-02."""
    espia.curvas = _curvas()
    resultado = _clasificar(_GaiaFake(26.0), None, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert not resultado.get("revisar_manualmente")


def test_medidor_completo_corrobora_cgm_desviado_pasa_sin_revision(espia, monkeypatch):
    """Valencia Oriente: el día fue distinto de verdad, no es un glitch."""
    espia.curvas = _curvas(ppal=_curva(6.2), resp=_curva(6.2))
    resultado = _clasificar(_GaiaFake(6.2), 2.5, monkeypatch)

    assert resultado["caso"] == "CGM", "corroborado por el medidor, el CGM se mantiene"
    assert resultado["medidor_usado"] == "cgm"
    assert not resultado.get("revisar_manualmente"), (
        "un medidor completo del mismo día respalda el valor -- no hay nada que revisar a mano"
    )
    assert espia.llamadas == [2.5], "se piden los medidores una sola vez, con la mediana de referencia"


def test_medidor_completo_contradice_cgm_doblado_cae_en_medidor(espia, monkeypatch):
    """Paso Norte: CGM 52,4 kWh = exactamente 2x los 26,2 del medidor."""
    espia.curvas = _curvas(ppal=_curva(26.2), resp=_curva(26.2))
    resultado = _clasificar(_GaiaFake(52.4), 26.0, monkeypatch)

    assert resultado["caso"] == "Medidor", "el CGM doblado se descarta"
    assert resultado["medidor_usado"] == "principal"
    assert abs(resultado["energia_final_kwh"] - 26.2) < 0.01, "se reporta el medidor, no el CGM"
    assert resultado["energia_cgm_kwh"] == pytest.approx(52.4), "el CGM descartado igual queda registrado"
    assert not resultado.get("revisar_manualmente"), (
        "el medidor quedó validado contra la mediana -- es un dato bueno, no una estimación"
    )
    assert len(espia.llamadas) == 1, "el Camino 2 debe reusar las curvas ya pedidas, no volver a pedirlas"


def test_medidor_incompleto_no_puede_contradecir_al_cgm(espia, monkeypatch):
    """6 de 24 horas leen ~1/4 del CGM, pero eso es el hueco, no un glitch."""
    espia.curvas = _curvas(ppal=_curva(6.5, horas_con_dato=6), ppal_completo=False)
    resultado = _clasificar(_GaiaFake(26.0), 13.0, monkeypatch)

    assert resultado["caso"] == "CGM", "un medidor con huecos no alcanza para descartar el CGM"
    assert resultado["revisar_manualmente"] is True, "nadie pudo opinar -- queda la revisión de siempre"


def test_medidor_incompleto_no_puede_corroborar_al_cgm(espia, monkeypatch):
    """Coincidir por casualidad con horas faltantes no es corroborar."""
    espia.curvas = _curvas(ppal=_curva(26.0, horas_con_dato=12), ppal_completo=False)
    resultado = _clasificar(_GaiaFake(26.0), 13.0, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert resultado["revisar_manualmente"] is True


def test_sin_medidor_con_dato_mantiene_la_revision(espia, monkeypatch):
    espia.curvas = _curvas()
    resultado = _clasificar(_GaiaFake(52.4), 26.0, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert resultado["revisar_manualmente"] is True


def test_basta_un_medidor_que_corrobore(espia, monkeypatch):
    """El respaldo coincide con el CGM aunque el principal no -- ahí el
    sospechoso es el principal, no el CGM."""
    espia.curvas = _curvas(ppal=_curva(13.0), resp=_curva(26.0))
    resultado = _clasificar(_GaiaFake(26.0), 13.0, monkeypatch)

    assert resultado["caso"] == "CGM"
    assert not resultado.get("revisar_manualmente")


def test_rango_de_corroboracion_no_deja_pasar_medio_ni_doble():
    """El ±2% es lo bastante estrecho para que ni la mitad ni el doble
    cuenten como coincidencia."""
    c = _curvas(ppal=_curva(26.0))
    assert mod._veredicto_medidor_vs_cgm(26.3, c) == "corrobora", "1,2% de diferencia sí corrobora"
    assert mod._veredicto_medidor_vs_cgm(52.0, c) == "contradice"
    assert mod._veredicto_medidor_vs_cgm(13.0, c) == "contradice"
    assert mod._veredicto_medidor_vs_cgm(28.0, c) == "contradice", "7,7% ya es demasiado para el mismo medidor"
