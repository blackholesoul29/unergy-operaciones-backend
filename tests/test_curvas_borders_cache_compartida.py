"""construir_mapa_borders() (curvas.py) y resolver_borders() (reporte_cgm.py)
comparten el mismo catálogo cacheado de gaia.get_all_borders() -- antes cada
uno tenía su propia caché independiente, así que una request que dispara
ambos (ej. destinatario "Cliente" en /reporte-cgm/enviar, que arma el
resumen mensual via construir_mapa_borders Y resuelve borders via
resolver_borders) podía pagar el fetch completo del catálogo dos veces
(auditoría CGM 2026-08-26, finding #2)."""
from app.services.reporte_energia import curvas
from app.services.reporte_cgm import resolver_borders

BORDERS_CRUDOS = [
    {
        "name": "Test Frontera",
        "frt_generation": {"frt_code": "Frt001", "id": 10, "category": 1, "main_meter": 1, "backup_meter": 2},
    },
]


class _GaiaContador:
    def __init__(self):
        self.llamadas = 0

    def get_all_borders(self):
        self.llamadas += 1
        return BORDERS_CRUDOS


def test_resolver_borders_y_construir_mapa_borders_comparten_una_sola_llamada(monkeypatch):
    monkeypatch.setattr(curvas, "_borders_crudos_cache", None)
    monkeypatch.setattr(curvas, "_borders_crudos_ts", 0.0)
    gaia = _GaiaContador()

    mapa = curvas.construir_mapa_borders(gaia)
    borders = resolver_borders(gaia, {"frt001"})

    assert gaia.llamadas == 1  # segunda llamada sirvió del cache compartido
    assert mapa["frt001"]["border_id"] == 10
    assert borders["frt001"]["id"] == 10


def test_usar_cache_false_fuerza_traer_de_nuevo(monkeypatch):
    monkeypatch.setattr(curvas, "_borders_crudos_cache", None)
    monkeypatch.setattr(curvas, "_borders_crudos_ts", 0.0)
    gaia = _GaiaContador()

    curvas.construir_mapa_borders(gaia)
    curvas.construir_mapa_borders(gaia, usar_cache=False)

    assert gaia.llamadas == 2
