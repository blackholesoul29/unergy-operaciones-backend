"""La API de Liquidaciones pagina sus listados desde agosto de 2026.

Antes devolvía la lista pelada; ahora manda un sobre ``{count, next, previous,
results}`` de 50 registros (máximo 500). Quedarse con la primera página pasa
inadvertido -- no da error, solo faltan filas -- así que el recorrido tiene
prueba propia.
"""
import pytest

from app.services import liquidaciones_api as api


@pytest.fixture(autouse=True)
def _sin_cache():
    api.invalidar_cache()
    yield
    api.invalidar_cache()


def _sobre(filas, hay_mas):
    return {"count": 999, "next": "..." if hay_mas else None, "previous": None, "results": filas}


def test_recorre_todas_las_paginas(monkeypatch):
    paginas = [
        _sobre([{"id": 1}, {"id": 2}], hay_mas=True),
        _sobre([{"id": 3}], hay_mas=False),
    ]
    vistos = []

    def fake(method, path, params=None, **kw):
        vistos.append(params["offset"])
        return paginas[len(vistos) - 1]

    monkeypatch.setattr(api, "_request", fake)
    assert api._listar("/x/") == [{"id": 1}, {"id": 2}, {"id": 3}]
    # El offset avanza por filas recibidas, no por número de página: si la API
    # devuelve menos de `limit`, saltar de a `limit` se comería registros.
    assert vistos == [0, 2]


def test_pide_el_maximo_por_pagina(monkeypatch):
    capturado = {}

    def fake(method, path, params=None, **kw):
        capturado.update(params)
        return _sobre([], hay_mas=False)

    monkeypatch.setattr(api, "_request", fake)
    api._listar("/x/")
    assert capturado["limit"] == api._LIMITE_PAGINA == 500


def test_acepta_lista_pelada(monkeypatch):
    """Rutas que todavía responden sin sobre siguen funcionando."""
    monkeypatch.setattr(api, "_request", lambda *a, **k: [{"id": 1}])
    assert api._listar("/viejo/") == [{"id": 1}]


def test_next_vacio_corta_aunque_haya_filas(monkeypatch):
    llamadas = []

    def fake(method, path, params=None, **kw):
        llamadas.append(1)
        return _sobre([{"id": 1}], hay_mas=False)

    monkeypatch.setattr(api, "_request", fake)
    assert len(api._listar("/x/")) == 1
    assert len(llamadas) == 1


def test_pagina_vacia_no_cicla(monkeypatch):
    """Un `next` que nunca se apaga con `results` vacío colgaría el proceso."""
    monkeypatch.setattr(api, "_request", lambda *a, **k: _sobre([], hay_mas=True))
    assert api._listar("/x/") == []


def test_respeta_el_tope_de_paginas(monkeypatch):
    """Sin tope, un listado de 26.000 filas se traería entero por accidente."""
    llamadas = []

    def fake(method, path, params=None, **kw):
        llamadas.append(1)
        return _sobre([{"id": len(llamadas)}], hay_mas=True)

    monkeypatch.setattr(api, "_request", fake)
    api._listar("/x/")
    assert len(llamadas) == api._MAX_PAGINAS


def test_quita_filtros_vacios(monkeypatch):
    capturado = {}

    def fake(method, path, params=None, **kw):
        capturado.update(params)
        return _sobre([], hay_mas=False)

    monkeypatch.setattr(api, "_request", fake)
    api._listar("/x/", project="uno", version=None, data_type="")
    assert "version" not in capturado and "data_type" not in capturado
    assert capturado["project"] == "uno"


def test_proyectar_expone_los_ids_de_quoia():
    """Los tres ids no son del proyecto: vienen de sus subproyectos."""
    crudo = {
        "nombre_topico": "agustin_3",
        "nombre_proyecto": "Agustín 3",
        "ac_power": 100.0,
        "subprojects": [{
            "topic": "agustin_3", "name": "Agustín 3",
            "quoia_report_gen_id": "191", "quoia_report_con_id": "190",
            "quoia_node_id": "1651", "campo_que_no_nos_importa": 1,
        }],
    }
    salida = api._proyectar(crudo)
    assert salida["subproyectos"] == [{
        "topic": "agustin_3", "name": "Agustín 3",
        "quoia_report_gen_id": "191", "quoia_report_con_id": "190",
        "quoia_node_id": "1651",
    }]


def test_proyecto_sin_subproyectos_no_revienta():
    assert api._proyectar({"nombre_topico": "x"})["subproyectos"] == []


@pytest.mark.parametrize("campo,valor", [
    ("quoia_report_gen_id", "12345"),   # máximo 4
    ("quoia_report_con_id", "12345"),
    ("quoia_node_id", "n" * 51),        # máximo 50
])
def test_rechaza_ids_de_quoia_largos(campo, valor, monkeypatch):
    """Mejor un mensaje claro aquí que un 400 opaco de la API externa."""
    monkeypatch.setattr(api, "_request", lambda *a, **k: pytest.fail("no debió llamarse"))
    with pytest.raises(api.LiquidacionesAPIError, match="caracteres"):
        api.actualizar_subproyecto("agustin_3", {campo: valor})


def test_ids_de_quoia_en_el_limite_pasan(monkeypatch):
    monkeypatch.setattr(api, "_request", lambda *a, **k: {"topic": "x"})
    api.actualizar_subproyecto("x", {"quoia_report_gen_id": "1234", "quoia_node_id": "n" * 50})


def test_ignora_campos_ajenos_al_actualizar_quoia(monkeypatch):
    enviado = {}

    def fake(method, path, json=None, **kw):
        enviado.update(json)
        return {"topic": "x"}

    monkeypatch.setattr(api, "_request", fake)
    api.actualizar_subproyecto("x", {"quoia_node_id": "5", "ac_power": 999})
    assert enviado == {"quoia_node_id": "5"}


def test_ipp_del_mes_toma_la_consulta_mas_reciente(monkeypatch):
    """Hay una fila por consulta al DANE, no una por mes."""
    filas = [
        {"id": 42, "year": 2026, "month": 7, "ipp": 186.35, "date": "2026-07-10T15:46:07-05:00"},
        {"id": 45, "year": 2026, "month": 7, "ipp": 186.99, "date": "2026-07-19T08:27:29-05:00"},
        {"id": 43, "year": 2026, "month": 7, "ipp": 186.00, "date": "2026-07-11T11:05:54-05:00"},
    ]
    monkeypatch.setattr(api, "_listar", lambda *a, **k: filas)
    assert api.ipp_del_mes(2026, 7)["id"] == 45


def test_ipp_del_mes_sin_datos(monkeypatch):
    monkeypatch.setattr(api, "_listar", lambda *a, **k: [])
    assert api.ipp_del_mes(2026, 1) is None
