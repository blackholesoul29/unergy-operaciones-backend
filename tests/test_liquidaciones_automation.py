"""Tests de la automatización de liquidación XM.

Cubren:
  - `mem_ingestion_service`: parseo de payloads, reintentos/backoff y errores.
  - `liquidaciones_orchestrator`: cálculo puro (generación × precio) y ramas de
    resolución de proyectos/período, sin tocar DB ni red.
"""
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from app.services import mem_ingestion_service as mem
from app.services import liquidaciones_orchestrator as orch


# ── mem_ingestion_service: parseo ────────────────────────────────────────────

def test_parse_precios_normaliza_kwh():
    payload = {"Items": [
        {"Date": "2026-05-01", "Value": "200.5"},
        {"Date": "2026-05-02T00:00:00", "Value": 300},
    ]}
    precios = mem._parse_precios(payload)
    assert len(precios) == 2
    assert precios[0].fecha == date(2026, 5, 1)
    assert precios[0].precio_cop_kwh == 200.5
    assert precios[1].fecha == date(2026, 5, 2)


def test_parse_precios_convierte_mwh_a_kwh():
    # Un precio en cientos de miles es COP/MWh; debe quedar en COP/kWh (÷1000).
    payload = {"Items": [{"Date": "2026-05-01", "Value": 250000}]}
    precios = mem._parse_precios(payload)
    assert precios[0].precio_cop_kwh == 250.0


def test_parse_precios_ignora_filas_incompletas():
    payload = {"Items": [
        {"Date": "2026-05-01"},              # sin valor
        {"Value": 100},                       # sin fecha
        {"Date": "no-fecha", "Value": 100},  # fecha inválida
        {"Date": "2026-05-03", "Value": 150},
    ]}
    precios = mem._parse_precios(payload)
    assert len(precios) == 1 and precios[0].fecha == date(2026, 5, 3)


def test_get_precios_bolsa_usa_request_fn_inyectado():
    llamadas = []

    def fake_request(endpoint, body):
        llamadas.append((endpoint, body))
        return {"Items": [{"Date": "2026-05-01", "Value": 210.0}]}

    precios = mem.get_precios_bolsa(
        date(2026, 5, 1), date(2026, 5, 31), request_fn=fake_request
    )
    assert len(precios) == 1
    assert llamadas[0][0] == mem.ENDPOINT_PRECIO_BOLSA
    assert llamadas[0][1]["StartDate"] == "2026-05-01"
    assert llamadas[0][1]["EndDate"] == "2026-05-31"


# ── mem_ingestion_service: reintentos / errores ──────────────────────────────

class _FakeResp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.request = httpx.Request("POST", "http://x/test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=self
            )


class _FakeClient:
    def __init__(self, respuestas):
        self._respuestas = list(respuestas)
        self.n_posts = 0

    def post(self, url, json=None, headers=None):
        self.n_posts += 1
        r = self._respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def close(self):
        pass


def test_request_fn_reintenta_ante_500_y_luego_exito():
    esperas = []
    cli = _FakeClient([_FakeResp(500), _FakeResp(200, {"ok": True})])
    fn = mem._default_request_fn(
        base_url="http://x", api_key="k", timeout=1.0, max_retries=3,
        client=cli, sleep_fn=esperas.append,
    )
    out = fn("EndpointX", {"a": 1})
    assert out == {"ok": True}
    assert cli.n_posts == 2
    assert esperas == [1]  # un backoff antes del segundo intento


def test_request_fn_no_reintenta_ante_4xx():
    cli = _FakeClient([_FakeResp(404)])
    fn = mem._default_request_fn(
        base_url="http://x", api_key="", timeout=1.0, max_retries=3,
        client=cli, sleep_fn=lambda s: None,
    )
    with pytest.raises(mem.MEMIngestionError):
        fn("EndpointX", {})
    assert cli.n_posts == 1  # no reintenta


def test_request_fn_agota_reintentos_y_lanza():
    cli = _FakeClient([httpx.ConnectError("boom")] * 3)
    fn = mem._default_request_fn(
        base_url="http://x", api_key="", timeout=1.0, max_retries=3,
        client=cli, sleep_fn=lambda s: None,
    )
    with pytest.raises(mem.MEMIngestionError):
        fn("EndpointX", {})
    assert cli.n_posts == 3


# ── orchestrator: cálculo puro ───────────────────────────────────────────────

def test_calcular_ingesta_valor_liquidado():
    gen = [(10, date(2026, 5, 1), 1000.0), (10, date(2026, 5, 2), 500.0)]
    precios = {date(2026, 5, 1): 200.0, date(2026, 5, 2): 300.0}
    filas = orch.calcular_ingesta(99, gen, precios)
    assert len(filas) == 2
    assert filas[0].valor_liquidado_cop == 200000.0
    assert filas[0].estado_proceso == "procesado"
    assert filas[0].informe_id == 99
    assert filas[1].valor_liquidado_cop == 150000.0


def test_calcular_ingesta_sin_precio_queda_pendiente():
    gen = [(10, date(2026, 5, 1), 1000.0)]
    filas = orch.calcular_ingesta(1, gen, {})  # sin precios
    assert filas[0].estado_proceso == "sin_precio"
    assert filas[0].valor_liquidado_cop is None
    assert filas[0].precio_bolsa_cop_kwh is None


def test_calcular_ingesta_omite_energia_none():
    gen = [(10, date(2026, 5, 1), None), (10, date(2026, 5, 2), 100.0)]
    filas = orch.calcular_ingesta(1, gen, {date(2026, 5, 2): 100.0})
    assert len(filas) == 1 and filas[0].fecha == date(2026, 5, 2)


def test_calcular_ingesta_mapea_contrato():
    gen = [(10, date(2026, 5, 1), 100.0)]
    filas = orch.calcular_ingesta(1, gen, {}, contrato_por_proyecto={10: 77})
    assert filas[0].ppa_contrato_id == 77


# ── orchestrator: helpers de resolución ──────────────────────────────────────

def test_sub_projects_individual():
    inf = SimpleNamespace(sub_project="PLANTA_A", tipo="op", miembros=None)
    assert orch._sub_projects_del_informe(inf) == ["PLANTA_A"]


def test_sub_projects_portafolio_incluye_miembros_sin_duplicar():
    inf = SimpleNamespace(
        sub_project="PORT_X", tipo="port",
        miembros=[{"sub_project": "A"}, {"sub_project": "B"}, {"sub_project": "A"}],
    )
    assert orch._sub_projects_del_informe(inf) == ["PORT_X", "A", "B"]


def test_parse_periodo():
    inf = SimpleNamespace(periodo_desde="2026-05-01", periodo_hasta="2026-05-31")
    desde, hasta = orch._parse_periodo(inf)
    assert desde == date(2026, 5, 1) and hasta == date(2026, 5, 31)


def test_parse_periodo_invalido_devuelve_none():
    inf = SimpleNamespace(periodo_desde="", periodo_hasta="basura")
    assert orch._parse_periodo(inf) == (None, None)


def test_run_proceso_informe_inexistente_devuelve_error():
    fake_db = SimpleNamespace(get=lambda model, pk: None)
    resumen = orch.run_liquidacion_proceso(fake_db, 12345)
    assert resumen.liquidacion_status == "ERROR"
    assert "no encontrado" in (resumen.error or "").lower()
