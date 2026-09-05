"""El numero de la minigranja decide el parecido de nombres.

`apps/comun/nombre_matching` lo comparten CINCO dominios --fronteras, proyectos,
portafolios, operadores de red y los backfills-- para avisar de posibles
duplicados antes de crear. Un aviso de mas no bloquea (se puede forzar), pero
cansa y entrena a la gente a ignorarlo; un aviso de menos deja crear la fila
duplicada.

Medido el 2026-09-05, antes de este cambio, TODOS estos pares avisaban:

    0,688  Minigranja 0091 - San Luis de Since  vs  Minigranja 0088 - San Luis
    0,688  Minigranja 0091 - San Luis de Since  vs  MGS 0034 San Luis
    0,727  Minigranja 0075 - El Carmen          vs  Minigranja 0112 - El Carmen
    0,600  GD San Pelayo                        vs  GD San Marcos

Son minigranjas y municipios DISTINTOS. Pasaba porque el numero contaba como
una palabra mas --con el mismo peso que "carmen"-- y porque "San" es el primer
token de casi todo municipio del portafolio, asi que compartirlo inflaba el
solapamiento.

Dos correcciones, las dos con la misma idea: separar lo que IDENTIFICA de lo que
solo acompana.

  · El numero de la minigranja es un identificador. Si los dos nombres lo
    traen, decide y no se negocia. Misma convencion que `_mgs_number` en
    app/services/mgs/gaia_client.py: exige el prefijo explicito, asi que no
    confunde un ano ni un numero suelto de una razon social.
  · "san" y "santa" pasan a ser ruido, igual que ya lo son en el pipeline del
    Reporte de Energia para mapear Quoia contra Solenium.
"""
from apps.comun.nombre_matching import (
    UMBRAL_ACEPTAR,
    core_tokens,
    numero_mgs,
    score_nombre,
)


def avisa(a: str, b: str) -> bool:
    return score_nombre(a, [b]) >= UMBRAL_ACEPTAR


# ── El numero como identificador ──────────────────────────────────────────

def test_numeros_distintos_son_minigranjas_distintas():
    """El caso reportado: 0091 no es 0088 por mas que compartan el municipio."""
    assert not avisa("Minigranja 0091 - San Luis de Since",
                     "Minigranja 0088 - San Luis")


def test_numeros_distintos_aunque_el_resto_del_nombre_sea_identico():
    assert not avisa("Minigranja 0075 - El Carmen", "Minigranja 0112 - El Carmen")


def test_el_prefijo_puede_ser_distinto_el_numero_es_el_que_manda():
    assert not avisa("Minigranja 0091 - San Luis de Since", "MGS 0034 San Luis")


def test_el_mismo_numero_es_la_misma_aunque_este_escrita_distinto():
    """Antes daba 0,850 por parecido de texto; ahora es certeza, no parecido."""
    assert score_nombre("Minigranja 0091 - San Luis de Since",
                        ["Minigranja 0091 San Luis"]) == 1.0


def test_el_numero_se_lee_con_ceros_a_la_izquierda_y_con_tildes():
    assert numero_mgs("Minigranja 0091 - San Luis de Sincé") == 91
    assert numero_mgs("MGS 34 San Luis") == 34


def test_un_numero_suelto_no_cuenta_como_codigo_de_minigranja():
    """Exige el prefijo: sin el, un ano en una razon social vetaria matches
    correctos en operadores, que comparten este mismo algoritmo."""
    assert numero_mgs("Frontera 2024 Consumo") is None
    assert numero_mgs("GD San Pelayo") is None


def test_si_solo_uno_trae_numero_se_sigue_comparando_por_nombre():
    """Sin los dos ids no se puede descartar, y ante la duda se avisa: el aviso
    se puede forzar, la fila duplicada hay que borrarla a mano."""
    assert avisa("Minigranja 0091 San Luis", "Sol Y Cielo San Luis")


# ── "San"/"Santa" como ruido ──────────────────────────────────────────────

def test_compartir_san_no_hace_parecidos_a_dos_municipios_distintos():
    assert not avisa("GD San Pelayo", "GD San Marcos")


def test_pero_el_mismo_municipio_si_sigue_avisando():
    assert avisa("GD San Pelayo", "GD San Pelayo Consumo")


def test_san_y_santa_ya_no_son_tokens_significativos():
    assert core_tokens("GD San Pelayo") == {"pelayo"}
    assert core_tokens("Santa Marta Consumo") == {"marta"}
