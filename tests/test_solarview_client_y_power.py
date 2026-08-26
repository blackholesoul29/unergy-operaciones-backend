"""SolarViewClient (Fase 1 de la migración de Solenium a SolarView) --
auth por token estático, y curva_de_power() sin el loop de suma manual por
inversor (con total_power=1 la API ya entrega la potencia sumada, ver
SolarViewClient.get_power)."""
import pandas as pd

from app.services.mgs import solarview_client as sv_client_module
from app.services.mgs.solarview_client import SolarViewClient
from app.services.reporte_energia.solarview import curva_de_power


def _cliente(token="abc123"):
    client = SolarViewClient.__new__(SolarViewClient)
    client._base_url = "https://api.sole.tech"
    client._token = token
    return client


def test_headers_usan_token_estatico_sin_bearer():
    client = _cliente()
    assert client._headers() == {"Authorization": "Token abc123"}


def test_enabled_es_falso_sin_token():
    client = _cliente(token="")
    assert client.enabled is False


def test_get_power_pide_total_power_1():
    client = _cliente()
    llamados = []
    client._get = lambda url, params=None: (llamados.append((url, params)) or {"results": {}})

    client.get_power(7, "2026-08-20", "2026-08-20")

    url, params = llamados[0]
    assert url.endswith("/solarview/measurements/power/")
    assert params["total_power"] == 1
    assert params["project_id"] == 7


def test_get_relay_historical_usa_recloser_como_nombre_de_parametro():
    """El parámetro se llama 'recloser' pero recibe el project_id (mismo
    gotcha que ya existía en la API vieja) -- ver plan de migración."""
    client = _cliente()
    llamados = []
    client._get = lambda url, params=None: (llamados.append((url, params)) or {"results": {}})

    client.get_relay_historical(7, "2026-08-20 00:00:00", "2026-08-20 23:59:59")

    url, params = llamados[0]
    assert url.endswith("/solarview/config/recloser/historical/")
    assert params["recloser"] == 7
    assert params["start_date"] == "2026-08-20 00:00:00"


def test_curva_de_power_ya_viene_sumada_sin_loop_por_inversor():
    """Con total_power=1, resp['results']['power'] es {ts: kw} plano --
    a diferencia de la API vieja de Solenium ({inversor: {ts: kw}})."""
    resp = {
        "message": "OK", "error": None, "success": True,
        "results": {
            "unit": "kW",
            "power": {
                "2026-08-20 10:00": 100.0,
                "2026-08-20 11:00": 200.0,
            },
        },
    }
    curva, horas_con_dato = curva_de_power(resp)

    assert horas_con_dato == {10, 11}
    # Riemann con 1h de separación entre los dos puntos: 100 kW * 1h = 100 kWh en la hora 10
    assert curva[10] == 100.0


def test_curva_de_power_vacia_si_no_hay_power():
    curva, horas_con_dato = curva_de_power({"results": {}})
    assert horas_con_dato == set()
    assert curva.isna().all()


def test_curva_de_power_descarta_hora_implausible():
    """Mismo criterio que curva_generacion() (ver limite_plausible_kwh()
    en utils.py) -- acá el riesgo es mayor: curva_de_power() se reporta
    DIRECTO como curva_final en el rescate de Caso 6/7, sin ningún FP ni
    comparación de por medio."""
    resp = {
        "results": {
            "power": {
                "2026-08-20 10:00": 500.0,      # 500 kWh en 1h -- plausible
                "2026-08-20 11:00": 250000.0,   # implausible para 0,99 MW
            },
        },
    }
    curva, horas_con_dato = curva_de_power(resp, capacidad_efectiva_mw=0.99)

    assert curva[10] == 500.0
    assert curva[11] is None or curva[11] != curva[11]  # NaN -- descartada
    assert 11 not in horas_con_dato


def test_curva_de_power_sin_capacidad_efectiva_no_filtra():
    resp = {
        "results": {
            "power": {
                "2026-08-20 11:00": 250000.0,
                "2026-08-20 12:00": 250000.0,
            },
        },
    }
    curva, _ = curva_de_power(resp)
    assert curva[11] == 250000.0


class _RespuestaFalsa:
    def __init__(self, status_code, headers=None, data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._data = data or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_reintenta_ante_429_con_pausa(monkeypatch):
    client = _cliente()
    respuestas = [
        _RespuestaFalsa(429, headers={"Retry-After": "5"}),
        _RespuestaFalsa(200, data={"ok": True}),
    ]
    client._http = type("_HttpFalso", (), {"get": lambda self, url, headers=None, params=None: respuestas.pop(0)})()

    esperas = []
    monkeypatch.setattr(sv_client_module.time, "sleep", lambda s: esperas.append(s))

    resultado = client._get("https://api.sole.tech/solarview/measurements/generation/")

    assert resultado == {"ok": True}
    assert esperas == [5.0]  # respeta Retry-After en vez de la pausa fija


def test_429_sin_retry_after_usa_pausa_fija(monkeypatch):
    client = _cliente()
    respuestas = [_RespuestaFalsa(429), _RespuestaFalsa(200, data={"ok": True})]
    client._http = type("_HttpFalso", (), {"get": lambda self, url, headers=None, params=None: respuestas.pop(0)})()

    esperas = []
    monkeypatch.setattr(sv_client_module.time, "sleep", lambda s: esperas.append(s))

    client._get("https://api.sole.tech/solarview/measurements/generation/")

    assert esperas == [sv_client_module.BACKOFF_SECONDS]
