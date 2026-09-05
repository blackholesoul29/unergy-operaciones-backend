"""`ya_registrada()` -- que borders de Quoia siguen siendo pendientes.

Contexto (2026-09-05): al agregar la minigranja de San Luis de Since desde
"Fronteras nuevas en Quoia" salia "No se pudo agregar la frontera", sin
explicacion y sin salida. Detras habia un aviso difuso por parecido de nombre
--un 409 reintentable con ?forzar=true-- que el frontend nunca cableo.

Ese aviso tapaba un hueco real: preguntando solo por `codigo_frontera`, una
frontera ya registrada a la que le cambiaran o le borraran el codigo reaparecia
como "nueva". La decision fue resolver la identidad por id en vez de por
parecido de nombre: el `quoia_border_id` es unico y no se repite, y con eso el
aviso difuso deja de tener sentido en este camino.

El ultimo test fija el limite honesto de la regla: una frontera creada a mano
no tiene ninguno de los dos ids, y esta pregunta no la ve.
"""
import pytest

from apps.fronteras.services.quoia import ya_registrada


def test_la_reconoce_por_su_codigo():
    assert ya_registrada("frt01097", 5511, {"frt01097"}, set()) is True


def test_el_codigo_se_compara_sin_importar_mayusculas():
    """Quoia devuelve `Frt01097` y aca se guarda en minusculas."""
    assert ya_registrada("Frt01097", None, {"frt01097"}, set()) is True


def test_la_reconoce_por_el_border_aunque_le_hayan_cambiado_el_codigo():
    """El caso que el codigo solo no veia: confirmarla creaba una fila
    duplicada para el mismo punto fisico."""
    assert ya_registrada("frt01097", 5511, codigos_vivos=set(),
                         borders_vivos={5511}) is True


def test_la_reconoce_por_el_border_aunque_le_hayan_borrado_el_codigo():
    """`codigo_frontera` es null=True en el modelo, asi que puede no estar."""
    assert ya_registrada(None, 5511, set(), {5511}) is True


def test_un_border_nuevo_sigue_siendo_pendiente():
    assert ya_registrada("frt01097", 5511, {"frt99999"}, {9999}) is False


def test_sin_ninguno_de_los_dos_ids_no_la_reconoce():
    """El limite de la regla, dicho a proposito.

    `quoia_border_id` solo se escribe al confirmar desde Quoia: una frontera
    creada a mano no lo tiene, y si ademas quedo sin codigo no tiene ningun id
    con que ser reconocida. Su border sigue apareciendo como pendiente y
    confirmarlo crea una segunda fila para el mismo punto fisico.

    Es el unico caso que el aviso por nombre atajaba y que este cambio NO
    cubre. Se cierra de verdad exigiendo `codigo_frontera` al crear a mano, o
    poblando `quoia_border_id` en ese camino.
    """
    assert ya_registrada(None, None, {"frt01097"}, {5511}) is False


@pytest.mark.parametrize("border_id", [None, 0])
def test_un_border_sin_id_no_empareja_por_id(border_id):
    """`0` no puede colarse como "sin id": se compara por pertenencia, no por
    verdad-falsedad."""
    assert ya_registrada("frt01097", border_id, set(), {5511}) is False
