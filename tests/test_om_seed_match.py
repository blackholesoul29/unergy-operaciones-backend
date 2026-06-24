"""
Verifica que el emparejamiento seed↔contrato (om_match_seed) asigne cada contrato
existente a la entrada correcta del seed, usando los nombres reales de producción
(con código MGS) y los huérfanos creados por seeds previos.
"""
from app.services.om_calculator import om_keys, om_match_seed

# Réplica de los nombres del seed (debe coincidir con _OM_PROYECTOS_SEED en main.py)
SEED_NOMBRES = [
    "Minigranja Solar Uruaco", "Minigranja Solar Baraya", "Minigranja Solar Cañahuate",
    "Minigranja Solar Gandalf", "Minigranja Solar La Paz Vallenata", "Minigranja Solar Perijá",
    "Minigranja Solar El Molino", "Minigranja Solar La Paz Verso", "Minigranja Solar Esmeralda",
    "Minigranja Solar El Son", "Minigranja Solar La Puya", "Minigranja Solar Villanueva",
    "Minigranja Solar Merengue", "Minigranja Solar La Reserva", "Nestlé",
    "Minigranja Solar Ibirico", "Minigranja Solar El Olimpo", "Minigranja Solar La Mesa",
    "Minigranja Solar San Diego Sur", "Minigranja Solar Valencia Oriente 1",
    "Minigranja Solar La Cacica", "Minigranja Solar Las Piloneras",
    "Minigranja Solar Valencia Oriente 2", "Minigranja Solar Cumbia",
    "Minigranja Solar Copey", "Minigranja Solar Chiriguana 2", "Minigranja Solar Chiriguana 4",
]

SEED_KEYS = [({"nombre": n}, om_keys(n)) for n in SEED_NOMBRES]

# Nombre de contrato en producción (display) → nombre de seed esperado
CASOS = {
    "MGS 0005 Cañahuate": "Minigranja Solar Cañahuate",
    "MGS 0004 Valle de Gandalf": "Minigranja Solar Gandalf",
    "MGS 0007 La Paz Vallenata": "Minigranja Solar La Paz Vallenata",
    "MGS 0006 Perija": "Minigranja Solar Perijá",
    "MGS 0009 El Molino": "Minigranja Solar El Molino",
    "MGS 0008 La Paz Verso": "Minigranja Solar La Paz Verso",
    "MGS 0017- Esmeralda": "Minigranja Solar Esmeralda",
    "MGS 0016 - Puya": "Minigranja Solar La Puya",
    "MGS 0010 - Villanueva": "Minigranja Solar Villanueva",
    "MGS 0019 El Merengue": "Minigranja Solar Merengue",
    "MGS 0012 La Reserva": "Minigranja Solar La Reserva",
    "MGS 0021 Ibirico": "Minigranja Solar Ibirico",
    "MGS 0014 - El Olimpo": "Minigranja Solar El Olimpo",
    "MGS 0013 La Mesa": "Minigranja Solar La Mesa",
    "MGS 0024 - San Diego Sur": "Minigranja Solar San Diego Sur",
    "MGS 0026 Valencia Oriente 1": "Minigranja Solar Valencia Oriente 1",
    "MGS 0027 Valencia Oriente 2": "Minigranja Solar Valencia Oriente 2",
    "MGS 0040 Cacica": "Minigranja Solar La Cacica",
    "MGS 0041 Piloneras": "Minigranja Solar Las Piloneras",
    "MGS 0075 - Chiriguana Norte 2": "Minigranja Solar Chiriguana 2",
    "MGS 0077 - Chiriguana Norte 4": "Minigranja Solar Chiriguana 4",
    "Nestlé": "Nestlé",
    # Huérfanos creados por seeds previos (sin código MGS)
    "Minigranja Solar Uruaco": "Minigranja Solar Uruaco",
    "Minigranja Solar Baraya": "Minigranja Solar Baraya",
    "Minigranja Solar El Son": "Minigranja Solar El Son",
}


def test_cada_contrato_mapea_a_su_seed():
    for nombre_contrato, esperado in CASOS.items():
        it = om_match_seed(nombre_contrato, SEED_KEYS)
        assert it is not None, f"{nombre_contrato!r} no hizo match"
        assert it["nombre"] == esperado, (
            f"{nombre_contrato!r} → {it['nombre']!r}, esperado {esperado!r}"
        )


def test_no_colision_valencia_1_vs_2():
    v1 = om_match_seed("MGS 0026 Valencia Oriente 1", SEED_KEYS)
    v2 = om_match_seed("MGS 0027 Valencia Oriente 2", SEED_KEYS)
    assert v1["nombre"] == "Minigranja Solar Valencia Oriente 1"
    assert v2["nombre"] == "Minigranja Solar Valencia Oriente 2"


def test_no_colision_chiriguana_2_vs_4():
    c2 = om_match_seed("MGS 0075 - Chiriguana Norte 2", SEED_KEYS)
    c4 = om_match_seed("MGS 0077 - Chiriguana Norte 4", SEED_KEYS)
    assert c2["nombre"] == "Minigranja Solar Chiriguana 2"
    assert c4["nombre"] == "Minigranja Solar Chiriguana 4"


def test_nombre_no_seed_no_mapea():
    # "Tibú" no está en el seed → no debe mapear a nada
    assert om_match_seed("Minigranja - Tibú", SEED_KEYS) is None
