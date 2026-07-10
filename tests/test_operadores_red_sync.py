from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto
from app.services.operadores_red_sync import sincronizar_operador_red


def _proyecto_con_fronteras(operador_red_id, *fronteras_operador_ids):
    p = Proyecto(nombre_comercial="Test", operador_red_id=operador_red_id)
    p.fronteras = [Frontera(operador_red_id=oid, nombre_frontera="F", tipo_frontera="generacion")
                   for oid in fronteras_operador_ids]
    return p


def test_rellena_fronteras_desde_proyecto():
    p = _proyecto_con_fronteras(1, None, None)
    sincronizar_operador_red(None, p)
    assert [f.operador_red_id for f in p.fronteras] == [1, 1]


def test_rellena_proyecto_desde_primera_frontera_con_valor():
    p = _proyecto_con_fronteras(None, None, 2, 3)
    sincronizar_operador_red(None, p)
    assert p.operador_red_id == 2


def test_no_pisa_valor_ya_diligenciado_en_frontera():
    # El proyecto dice 1, pero esta frontera ya tenía 9 -- no se pisa.
    p = _proyecto_con_fronteras(1, 9)
    sincronizar_operador_red(None, p)
    assert p.fronteras[0].operador_red_id == 9


def test_sin_nada_que_sincronizar_no_hace_nada():
    p = _proyecto_con_fronteras(None, None, None)
    sincronizar_operador_red(None, p)
    assert p.operador_red_id is None
    assert all(f.operador_red_id is None for f in p.fronteras)
