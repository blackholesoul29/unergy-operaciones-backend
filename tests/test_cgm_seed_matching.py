"""Pruebas del matching y la normalizacion del seed CGM/Representacion.

Los dos casos que estas pruebas fijan son los que ensuciaron produccion:

1. El matcher asignaba contratos a plantas ajenas. Tomaba la primera palabra de
   mas de 4 letras del nombre de referencia y devolvia el PRIMER proyecto que la
   contuviera como substring, asi que "GD Yuan Solar" caia en "Minigranja Solar
   Baraya" por la palabra "solar".

2. El dedup comparaba strings exactos y los dos seeds escriben el mismo
   inversionista con y sin tilde ("SOMOS BOGOTA USME SAS" vs "SOMOS BOGOTÁ USME
   SAS"), asi que cada variante insertaba un contrato duplicado.
"""
import pytest

from app.main import _cgm_norm, _cgm_buscar_proyecto


# Catalogo de plantas como aparecen en produccion: sin el numero de 4 digitos
# que si traen los nombres de referencia de los contratos.
PLANTAS = {
    _cgm_norm("Minigranja Solar Baraya"): 1,
    _cgm_norm("GD Yuan Solar"): 2,
    _cgm_norm("MGS Naos 2"): 3,
    _cgm_norm("Minigranja 0021 - Ibirico"): 4,
}
TSF = {
    _cgm_norm("COLSUCT17P2"): 1,
    _cgm_norm("COLCEST49P2"): 4,
}


class TestNormalizacion:
    @pytest.mark.parametrize("a, b", [
        # Las cuatro variantes de tilde que hay hoy entre los dos seeds y que
        # generaban 9 contratos duplicados en produccion.
        ("SOMOS BOGOTÁ USME SAS", "SOMOS BOGOTA USME SAS"),
        ("Ayurá S.A.S.", "Ayura S.A.S."),
        ("QUANTUM ENERGY INGENIERÍA S.A.S", "QUANTUM ENERGY INGENIERIA S.A.S"),
        ("FEM ENERGÍA S.A.S.", "FEM ENERGIA S.A.S."),
        # Caja, puntuacion final y dobles espacios tampoco distinguen.
        ("Solenium  S.A.S", "SOLENIUM S.A.S."),
    ])
    def test_variantes_del_mismo_nombre_colapsan(self, a, b):
        """Tilde, puntuacion, mayusculas y dobles espacios no distinguen."""
        assert _cgm_norm(a) == _cgm_norm(b)

    def test_nombres_distintos_no_colapsan(self):
        assert _cgm_norm("Solenium S.A.S") != _cgm_norm("Unergy S.A.S")

    def test_limite_conocido_siglas_pegadas_no_colapsan(self):
        """"S.A.S" y "SAS" siguen siendo distintos, a proposito.

        Colapsarlos exige borrar los espacios, y eso volveria espuria la busqueda
        por numero de planta (pegar digitos crea secuencias que no existen). Hoy
        no hace falta: los 39 nombres de inversionista de los dos seeds producen
        los mismos 35 grupos con o sin espacios, o sea que no existe ni un par que
        difiera solo en esto. Si aparece, este test es el lugar donde cambiarlo.
        """
        assert _cgm_norm("Quantum Energy SAS") != _cgm_norm("Quantum Energy S.A.S")

    def test_vacio_y_none(self):
        assert _cgm_norm(None) == ""
        assert _cgm_norm("   ") == ""


class TestBuscarProyecto:
    def test_codigo_sun_factory_manda(self):
        assert _cgm_buscar_proyecto("Minigranja 0002 - Baraya", "COLSUCT17P2",
                                    PLANTAS, TSF) == 1

    def test_codigo_sun_factory_normalizado(self):
        """El codigo llega con otra caja o espacios sobrantes y sigue matcheando."""
        assert _cgm_buscar_proyecto("lo que sea", " colsuct17p2 ", PLANTAS, TSF) == 1

    def test_numero_de_cuatro_digitos_cuando_es_unico(self):
        assert _cgm_buscar_proyecto("Minigranja 0021 - Ibirico", None,
                                    PLANTAS, TSF) == 4

    def test_nombre_exacto_normalizado(self):
        """El criterio que recupera los aciertos legitimos del viejo matcher.

        Muchos contratos se llaman igual que su planta (GD Delta 1, Taurus VIII).
        Se asignan por igualdad de nombre normalizado, sin depender del orden en
        que la consulta devuelva los proyectos.
        """
        assert _cgm_buscar_proyecto("GD YUAN SOLAR", None, PLANTAS, TSF) == 2
        assert _cgm_buscar_proyecto("mgs  naos 2", None, PLANTAS, TSF) == 3

    def test_no_asigna_por_palabra_suelta(self):
        """El caso que metia contratos en plantas ajenas.

        "GD Yuan Solar" comparte la palabra "solar" con "Minigranja Solar Baraya"
        (id 1). Si su propia planta no esta en la base, el resultado correcto es
        None -- pendiente visible -- y no la planta ajena que comparte la palabra.
        """
        plantas_sin_yuan = {k: v for k, v in PLANTAS.items()
                            if v != 2}          # se quita "GD Yuan Solar"
        assert _cgm_buscar_proyecto("GD Yuan Solar", None,
                                    plantas_sin_yuan, TSF) is None

    def test_no_asigna_por_la_palabra_minigranja(self):
        """Casi todo nombre de referencia empieza por "Minigranja"; si eso
        matcheara, todos los contratos caerian en la misma planta."""
        assert _cgm_buscar_proyecto("Minigranja 9999 - Planta Nueva", None,
                                    PLANTAS, TSF) is None

    def test_nombre_de_cuatro_letras_queda_huerfano_no_mal_asignado(self):
        """"Naos" tiene 4 letras y nunca califico como palabra clave, asi que
        estos tres contratos salian "Sin proyecto".

        Con el criterio de nombre exacto, "MGS Naos 2" si encuentra su planta.
        Los otros dos siguen sin planta porque no estan en la base, y eso es lo
        correcto: pendiente visible, no una planta al azar.
        """
        assert _cgm_buscar_proyecto("MGS Naos 2", None, PLANTAS, TSF) == 3
        for nombre in ("GD NAOS 1", "MGS Naos 3"):
            assert _cgm_buscar_proyecto(nombre, None, PLANTAS, TSF) is None

    def test_numero_ambiguo_no_se_adivina(self):
        """Si el numero aparece en dos plantas, elegir la primera es arbitrario."""
        plantas = {
            _cgm_norm("Minigranja 0007 - Norte"): 10,
            _cgm_norm("Minigranja 0007 - Sur"): 11,
        }
        assert _cgm_buscar_proyecto("Minigranja 0007 - Algo", None, plantas, {}) is None

    def test_sf_desconocido_cae_al_numero(self):
        """Un codigo que no existe en la BD no bloquea el criterio del numero."""
        assert _cgm_buscar_proyecto("Minigranja 0021 - Ibirico", "COLNOEXISTE9",
                                    PLANTAS, TSF) == 4


# ─────────────────────────────────────────────────────────────────────────────
# Dedup: por que produccion termino con 112 contratos donde hay muchos menos.
# ─────────────────────────────────────────────────────────────────────────────

from types import SimpleNamespace

from app.main import _CgmIndice


def registro(inv=None, sf=None, ref=None, pid=None, numero=None):
    """Un contrato de representacion ya existente en la base."""
    return SimpleNamespace(inversionista_nombre=inv, codigo_sun_factory=sf,
                           nombre_proyecto_ref=ref, proyecto_id=pid,
                           numero_contrato=numero)


def indice_con(*registros):
    idx = _CgmIndice()
    for r in registros:
        idx.indexar(r)
    return idx


class TestDedup:
    def test_reconoce_por_codigo_sun_factory(self):
        ya = registro(inv="Solenium S.A.S", sf="COLSUCT17P2", ref="Minigranja 0002 - Baraya")
        idx = indice_con(ya)
        assert idx.buscar("Solenium S.A.S", "Minigranja 0002 - Baraya",
                          "COLSUCT17P2", None) is ya

    def test_reconoce_variante_con_tilde(self):
        """El duplicado de "Somos Bogota/Bogotá Usme" en Baraya.

        El seed viejo lo escribio con tilde y el de arranque sin ella; el dedup
        comparaba strings exactos y metia una segunda copia.
        """
        ya = registro(inv="SOMOS BOGOTÁ USME SAS", sf="COLSUCT17P2",
                      ref="Minigranja 0002 - Baraya")
        idx = indice_con(ya)
        assert idx.buscar("SOMOS BOGOTA USME SAS", "Minigranja 0002 - Baraya",
                          "COLSUCT17P2", None) is ya

    def test_reconoce_registro_sin_nombre_de_referencia(self):
        """Lo que sembro scripts/seed_contratos_cgm.py.

        Ese script hace `c.pop("proyecto_nombre")` y nunca persiste
        nombre_proyecto_ref, asi que el registro solo tiene proyecto_id. El dedup
        preguntaba por el campo vacio y siempre insertaba una copia: es el caso de
        los 34 contratos sin codigo Sun Factory.
        """
        ya = registro(inv="GD EL REMOLINO 1 S.A.S. E.S.P", pid=3)   # sin sf ni ref
        idx = indice_con(ya)
        assert idx.buscar("GD EL REMOLINO 1 S.A.S. E.S.P", "MGS Naos 2",
                          None, 3) is ya

    def test_no_confunde_dos_inversionistas_de_la_misma_planta(self):
        """Baraya tiene tres inversionistas: la planta sola no identifica nada."""
        solenium = registro(inv="Solenium S.A.S", sf="COLSUCT17P2", pid=1)
        idx = indice_con(solenium)
        assert idx.buscar("Unergy S.A.S", "Minigranja 0002 - Baraya",
                          "COLSUCT17P2", 1) is None

    def test_contrato_del_wizard_no_absorbe_una_entrada_del_seed(self):
        """La fila UNERGY-RC-002-2025 de Naos 2.

        La creo alguien a mano: trae numero y fechas pero no inversionista. No se
        puede emparejar con una entrada del seed sin adivinar cual de los
        inversionistas de la planta le corresponde, asi que queda fuera del indice
        y se revisa a mano. Lo que NO debe pasar es que el seed la tome por suya y
        se salte la siembra.
        """
        wizard = registro(inv=None, pid=3, numero="UNERGY-RC-002-2025")
        idx = indice_con(wizard)
        assert idx.buscar("GD EL REMOLINO 1 S.A.S. E.S.P", "MGS Naos 2",
                          None, 3) is None

    def test_no_reconoce_nada_cuando_la_base_esta_vacia(self):
        idx = indice_con()
        assert idx.buscar("Solenium S.A.S", "Minigranja 0002 - Baraya",
                          "COLSUCT17P2", 1) is None

    def test_idempotente_al_indexar_lo_recien_creado(self):
        """Segunda vuelta del mismo contrato: se encuentra, no se duplica."""
        idx = _CgmIndice()
        assert idx.buscar("Ayurá S.A.S.", "Minigranja 0040 - La Cacica", None, 7) is None
        nuevo = registro(inv="Ayurá S.A.S.", ref="Minigranja 0040 - La Cacica", pid=7)
        idx.indexar(nuevo)
        # misma entrada, escrita sin tilde como en el otro seed
        assert idx.buscar("Ayura S.A.S.", "Minigranja 0040 - La Cacica", None, 7) is nuevo
