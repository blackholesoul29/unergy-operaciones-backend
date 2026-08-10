"""Pruebas de la vista de contratos (GET /cumplimiento/vista-contratos).

Se prueba contra un `get_plantas_contratos` simulado: lo que importa acá no es
volver a verificar GESCON —eso ya tiene sus propias pruebas— sino las dos reglas
que esta capa agrega y que son fáciles de romper: el filtro por día y el filtro
por responsable.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import vista_contratos as vc

F = date(2026, 8, 20)


def planta(nombre, ini="2026-08-01", fin="2026-08-31", pid=1, pct=1.0, **kw):
    d = {"id": pid, "nombre": nombre, "pct_despacho": pct,
         "segmento_inicio": ini, "segmento_fin": fin}
    d.update(kw)
    return d


def contrato(nombre, plantas, cid=1, responsable="Unergy"):
    return {"id": cid, "nombre": nombre, "numero_codigo_contrato": f"COD-{cid}",
            "comprador_nombre": "Comprador X", "responsable": responsable,
            "plantas": plantas}


@pytest.fixture
def montar(monkeypatch):
    """Devuelve una función que arma la vista con datos simulados."""
    def _montar(contratos, proyectos=None, compromisos=None):
        monkeypatch.setattr(
            "app.api.v1.cumplimiento.get_plantas_contratos",
            lambda **kw: {"year": 2026, "month": 8, "venta": contratos},
        )

        class QueryFalsa:
            def __init__(self, filas): self._f = filas
            def filter(self, *a, **k): return self
            def outerjoin(self, *a, **k): return self
            def all(self): return self._f

        class DBFalsa:
            def query(self, *entidades):
                nombre = getattr(entidades[0], "__name__", "")
                if nombre == "PPACompromisoEnergia":
                    return QueryFalsa(compromisos or [])
                return QueryFalsa(proyectos or [])

        return vc.construir(DBFalsa(), fecha=F, responsable="Unergy")
    return _montar


def proyecto(pid, nombre, fpo=None, promedio=None, origen=None, portafolio=None):
    p = SimpleNamespace(id=pid, nombre_comercial=nombre, deleted_at=None,
                        fecha_entrada_operacion=date.fromisoformat(fpo) if fpo else None,
                        gen_mensual_promedio_mwh=promedio, gen_promedio_origen=origen)
    return (p, portafolio)


def compromiso(cid, minimo=None, maximo=None):
    return SimpleNamespace(contrato_id=cid, energia_minima=minimo, energia_maxima=maximo)


# ── el filtro por día ────────────────────────────────────────────────────────

def test_solo_entran_las_plantas_vigentes_ese_dia(montar):
    v = montar([contrato("C", [
        planta("Sigue", "2026-08-01", "2026-08-31", pid=1),
        planta("Salió", "2026-08-01", "2026-08-19", pid=2),
        planta("Entra luego", "2026-08-21", "2026-08-31", pid=3),
    ])])
    assert [p["planta"] for p in v["contratos"][0]["plantas"]] == ["Sigue"]


def test_las_que_se_mueven_dentro_del_mes_quedan_marcadas(montar):
    v = montar([contrato("C", [planta("Entrante", "2026-08-12", "2026-08-25")])])
    assert v["contratos"][0]["plantas"][0]["marcas"] == ["entra el 12", "sale el 25", "falta promedio"]


def test_una_fila_sin_ventana_no_se_descarta(montar):
    """Un payload sin segmento_* no debe hacer desaparecer la planta."""
    v = montar([contrato("C", [{"id": 1, "nombre": "X", "pct_despacho": 1.0}])])
    assert v["contratos"][0]["n_plantas"] == 1


# ── el filtro por responsable ────────────────────────────────────────────────

def test_deja_solo_el_responsable_pedido_y_reporta_lo_excluido(montar):
    v = montar([contrato("Mío", [planta("A")], cid=1, responsable="Unergy"),
                contrato("Ajeno", [planta("B", pid=2)], cid=2, responsable="Externo")])
    assert [c["contrato"] for c in v["contratos"]] == ["Mío"]
    assert v["excluidos"] == [{"contrato": "Ajeno", "responsable": "Externo",
                               "n_plantas": 1, "motivo": "responsable"}]


def test_un_contrato_sin_responsable_no_pasa_pero_se_lista(montar):
    v = montar([contrato("Huérfano", [planta("A")], responsable=None)])
    assert v["contratos"] == []
    assert v["excluidos"][0]["responsable"] is None


def test_el_filtro_ignora_mayusculas_y_tildes(montar):
    v = montar([contrato("C", [planta("A")], responsable="UNERGY")])
    assert len(v["contratos"]) == 1


# ── columnas ─────────────────────────────────────────────────────────────────

def test_gen_prom_sale_del_campo_del_proyecto(montar):
    v = montar([contrato("C", [planta("Gandalf", pid=7)])],
               proyectos=[proyecto(7, "Gandalf", fpo="2024-02-22", promedio=213.3, origen="api")])
    p = v["contratos"][0]["plantas"][0]
    assert p["gen_prom_mwh_mes"] == 213.3
    assert p["gen_prom_origen"] == "api"
    assert p["fpo"] == "2024-02-22"
    assert "falta promedio" not in p["marcas"]


def test_sin_promedio_calculado_queda_en_null_y_se_avisa(montar):
    """No se rellena con otra cifra: un número de otra escala se lee como bueno."""
    v = montar([contrato("C", [planta("Gandalf", pid=7)])],
               proyectos=[proyecto(7, "Gandalf")])
    p = v["contratos"][0]["plantas"][0]
    assert p["gen_prom_mwh_mes"] is None
    assert "falta promedio" in p["marcas"]
    assert v["totales"]["plantas_sin_promedio"] == 1


def test_el_total_del_contrato_pondera_por_el_porcentaje(montar):
    v = montar([contrato("C", [planta("A", pid=7, pct=0.5)])],
               proyectos=[proyecto(7, "A", promedio=200.0)])
    assert v["contratos"][0]["gen_prom_total_mwh"] == 100.0


def test_si_falta_el_promedio_de_una_planta_no_se_suma_a_medias(montar):
    """Una suma incompleta comparada contra el mínimo daría un déficit falso."""
    v = montar([contrato("C", [planta("A", pid=7), planta("B", pid=8)])],
               proyectos=[proyecto(7, "A", promedio=200.0), proyecto(8, "B")],
               compromisos=[compromiso(1, minimo=150.0)])
    c = v["contratos"][0]
    assert c["gen_prom_total_mwh"] is None
    assert c["estado"] == "sin_datos"


def test_min_y_max_salen_de_los_compromisos_del_mes(montar):
    v = montar([contrato("C", [planta("A", pid=7)])],
               proyectos=[proyecto(7, "A", promedio=200.0)],
               compromisos=[compromiso(1, minimo=1345.0, maximo=2201.0)])
    c = v["contratos"][0]
    assert (c["min_mes_mwh"], c["max_mes_mwh"]) == (1345.0, 2201.0)


def test_portafolio_dominante_y_mezcla(montar):
    v = montar([contrato("C", [planta("A", pid=7), planta("B", pid=8), planta("C", pid=9)])],
               proyectos=[proyecto(7, "A", portafolio="Ayurá"),
                          proyecto(8, "B", portafolio="Ayurá"),
                          proyecto(9, "C", portafolio="FMO")])
    assert v["contratos"][0]["portafolio"] == "Ayurá (+1)"


@pytest.mark.parametrize("mn,mx,gen,esperado", [
    (1345.0, 2201.0, 1863.0, "ok"),
    (1345.0, None, 900.0, "deficit"),
    (100.0, 500.0, 900.0, "excedente"),
    (None, None, 900.0, "sin_compromisos"),
    (1345.0, None, None, "sin_datos"),
])
def test_estado(mn, mx, gen, esperado):
    assert vc._estado(mn, mx, gen) == esperado


def test_el_porcentaje_en_escala_0_100_se_convierte_y_se_marca(montar):
    v = montar([contrato("C", [planta("A", pid=7, pct=100)])],
               proyectos=[proyecto(7, "A", promedio=200.0)])
    p = v["contratos"][0]["plantas"][0]
    assert p["pct_asignado"] == 1.0
    assert "% dudoso" in p["marcas"]


# ── totales y huecos ─────────────────────────────────────────────────────────

def test_un_contrato_sin_minimo_no_suma_cero(montar):
    v = montar([contrato("C", [planta("A", pid=7)])],
               proyectos=[proyecto(7, "A", promedio=200.0)])
    assert v["totales"]["min_mes_mwh"] is None
    assert v["totales"]["contratos_sin_minimo"] == 1


def test_un_contrato_sin_plantas_ese_dia_aparece_con_aviso(montar):
    v = montar([contrato("Vacío", [planta("A", "2026-08-01", "2026-08-05")])])
    assert v["contratos"][0]["n_plantas"] == 0
    assert "sin plantas asignadas el 2026-08-20" in v["avisos"][0]


def test_sin_contratos_no_revienta(montar):
    v = montar([])
    assert v["contratos"] == [] and v["totales"]["min_mes_mwh"] is None


# ── el endpoint ──────────────────────────────────────────────────────────────

def test_una_fecha_mal_escrita_da_422_con_un_mensaje_util():
    from fastapi import HTTPException
    from app.api.v1.cumplimiento import get_vista_contratos
    with pytest.raises(HTTPException) as e:
        get_vista_contratos(fecha="20/08/2026", responsable="Unergy",
                            incluir_todos=False, db=None, _=None)
    assert e.value.status_code == 422
    assert "YYYY-MM-DD" in e.value.detail


@pytest.mark.parametrize("valor", ["", "todos", "TODOS", "  "])
def test_responsable_vacio_o_todos_desactiva_el_filtro(valor, monkeypatch):
    """Sin esto habría que adivinar cómo pedir "todos los responsables"."""
    from app.api.v1 import cumplimiento
    visto = {}
    monkeypatch.setattr("app.services.vista_contratos.construir",
                        lambda db, fecha, responsable, incluir_todos: visto.update(r=responsable))
    cumplimiento.get_vista_contratos(fecha="2026-08-20", responsable=valor,
                                     incluir_todos=False, db=None, _=None)
    assert visto["r"] is None
