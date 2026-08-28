"""Tests del catalogo de la seccion "Registros" (funciones puras, sin base de datos).

Lo que protegen, en orden de importancia:

 1. Que el mapa documento->parametro no referencie claves inexistentes. Un typo
    ahi deja un campo fuera de un formulario y no se nota hasta produccion.
 2. Que no vuelvan a aparecer dos parametros para el mismo dato, que es el
    unico defecto que este modulo existe para evitar.
 3. Que el alcance (equipo/posicion) se normalice igual siempre, porque de eso
    depende que la restriccion de unicidad de la base sirva de algo.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.registros_proyecto import mapa_documentos as mapa
from app.services.registros_proyecto import service
from app.services.registros_proyecto.catalogo_items import (
    ITEMS, ITEMS_POR_PROCESO, Proceso, item as definicion_item,
)
from app.services.registros_proyecto.catalogo_parametros import PARAMETROS
from app.services.registros_proyecto.catalogo_parametros_cnd import (
    PARAMETROS_CND, REUSADOS_DE_SIC,
)


# ---------------------------------------------------------------------------
# Catalogo de items
# ---------------------------------------------------------------------------
def test_sic_tiene_los_28_items_de_la_carpeta_real():
    codigos = [i["codigo"] for i in ITEMS_POR_PROCESO[Proceso.SIC]]
    assert codigos == [f"{n:02d}" for n in range(1, 29)]


def test_cnd_tiene_los_10_numerales():
    codigos = [i["codigo"] for i in ITEMS_POR_PROCESO[Proceso.CND]]
    assert codigos == [f"9.{n}" for n in range(1, 11)]


def test_no_hay_items_repetidos():
    claves = [(i["proceso"], i["codigo"]) for i in ITEMS]
    assert len(claves) == len(set(claves))


def test_todo_item_pendiente_explica_por_que():
    """Un item sin validar tiene que decirlo; si no, se da por bueno sin serlo."""
    for i in ITEMS:
        if i["estado_base"] == "PENDIENTE":
            assert i.get("nota"), f"{i['proceso']} {i['codigo']} sin nota de pendiente"


# ---------------------------------------------------------------------------
# Catalogo de parametros
# ---------------------------------------------------------------------------
def test_claves_de_parametro_unicas_en_los_dos_catalogos():
    claves = [p["clave"] for p in PARAMETROS] + [p["clave"] for p in PARAMETROS_CND]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    assert repetidas == [], f"claves duplicadas: {repetidas}"


def test_el_medidor_principal_y_el_de_respaldo_comparten_definicion():
    """La serie del medidor es UN parametro con dos equipos, no dos parametros."""
    p = service.DEFINICIONES["medidor.numero_de_serie"]
    assert p["ambito"] == "EQUIPO"
    assert set(p["equipo_tipos"]) == {"MEDIDOR_PRINCIPAL", "MEDIDOR_RESPALDO"}


def test_los_tc_y_tp_tienen_tres_instancias():
    for clave in ("tc.numero_de_serie", "tp.numero_de_serie"):
        assert service.DEFINICIONES[clave]["instancias"] == 3


def test_latitud_y_longitud_no_se_colapsaron():
    """Los dos comparten el titulo 'Coordenadas (...)' en el formato oficial."""
    assert "frontera.latitud" in service.DEFINICIONES
    assert "frontera.longitud" in service.DEFINICIONES


def test_los_sellos_son_una_tabla_y_no_49_campos():
    p = service.DEFINICIONES["medidor.sellos"]
    assert p["tipo"] == "TABLA"
    assert "serie" in p["columnas"]


def test_cnd_reusa_parametros_del_sic_en_vez_de_redefinirlos():
    """El Anexo 4 pide seis datos que la hoja de vida ya pidio: son los mismos."""
    for clave in REUSADOS_DE_SIC:
        assert clave in {p["clave"] for p in PARAMETROS}, f"{clave} no es del catalogo SIC"
        assert clave not in {p["clave"] for p in PARAMETROS_CND}, (
            f"{clave} se redefinio en el catalogo CND en vez de reusarse")


# ---------------------------------------------------------------------------
# Mapa documento -> parametro
# ---------------------------------------------------------------------------
def test_el_mapa_no_referencia_claves_inexistentes():
    assert mapa.validar() == []


def test_todos_los_items_estan_en_el_mapa():
    faltan = [(i["proceso"], i["codigo"]) for i in ITEMS
              if (i["proceso"], i["codigo"]) not in mapa.PARAMETROS_POR_ITEM]
    assert faltan == []


def test_la_hoja_de_vida_contiene_todo_el_catalogo_sic():
    """Es el documento ancla: los demas items del SIC son subconjuntos suyos."""
    hoja = set(mapa.parametros_de(Proceso.SIC, "01"))
    assert hoja == {p["clave"] for p in PARAMETROS}


def test_el_acta_y_la_hoja_de_vida_comparten_datos_sin_duplicarlos():
    """Prueba el principio del modulo con el caso real del expediente."""
    hoja = set(mapa.parametros_de(Proceso.SIC, "01"))
    acta = set(mapa.parametros_de(Proceso.SIC, "13"))
    compartidos = hoja & acta
    assert "medidor.numero_de_serie" in compartidos
    assert "tc.cert_calibracion_numero_certificado_1ra_relacion" in compartidos
    assert "modem.imei" in compartidos
    # Y siguen siendo la misma clave: no hay una version "del acta".
    assert not any(c.endswith("_acta") for c in acta)


def test_el_nombre_de_la_frontera_se_diligencia_una_vez_para_muchos_documentos():
    usos = mapa.items_que_usan("frontera.nombre_frontera")
    assert len(usos) >= 8
    assert (Proceso.SIC, "01") in usos
    assert (Proceso.CND, "9.1") in usos


def test_items_sin_validar_no_declaran_parametros():
    """No inventar contenido para las carpetas que estan vacias."""
    for proceso, codigo in [(Proceso.SIC, c) for c in
                            ("16", "17", "18", "19", "20", "21", "22", "23", "27")]:
        assert mapa.parametros_de(proceso, codigo) == []


# ---------------------------------------------------------------------------
# Normalizacion de alcance y tipado de valores
# ---------------------------------------------------------------------------
def test_un_dato_del_proyecto_siempre_queda_sin_equipo():
    """Si no se forzara, el mismo dato podria entrar dos veces con alcances distintos."""
    assert service._normalizar_alcance("frontera.nombre_frontera", "MEDIDOR_PRINCIPAL", 2) == ("", 0)


def test_un_dato_de_equipo_sin_posicion_va_a_la_primera():
    assert service._normalizar_alcance("medidor.numero_de_serie", "MEDIDOR_RESPALDO", 0) == (
        "MEDIDOR_RESPALDO", 1)


def test_rechaza_un_equipo_que_no_corresponde_al_parametro():
    with pytest.raises(ValueError, match="no aplica al equipo"):
        service._normalizar_alcance("medidor.numero_de_serie", "TC", 1)


def test_rechaza_una_posicion_fuera_de_rango():
    with pytest.raises(ValueError, match="fuera de rango"):
        service._normalizar_alcance("tc.numero_de_serie", "TC", 4)


def test_rechaza_una_clave_desconocida():
    with pytest.raises(ValueError, match="desconocido"):
        service._normalizar_alcance("medidor.inventado", "", 0)


def test_tipa_numeros_y_fechas_segun_el_catalogo():
    assert service._tipar("frontera.latitud", "9.21189898") == (Decimal("9.21189898"), None)
    assert service._tipar("medidor.fecha_calibracion", "2026-05-19") == (None, date(2026, 5, 19))


def test_un_numero_con_formato_raro_no_rompe_el_guardado():
    """El acta trae 'Imax 1(10)A'. Se conserva el texto y la columna tipada queda vacia."""
    assert service._tipar("medidor.imax", "1(10)A") == (None, None)


def test_el_texto_nunca_se_pierde_al_tipar():
    """_tipar solo deriva columnas auxiliares; el valor exacto vive en `valor`."""
    assert service._tipar("frontera.nombre_frontera", "MGS 0092 - San Luis") == (None, None)


# ---------------------------------------------------------------------------
# Coherencia catalogo <-> items
# ---------------------------------------------------------------------------
def test_el_item_de_matricula_apunta_a_la_persona_designada():
    claves = mapa.parametros_de(Proceso.SIC, "25")
    assert "responsable.nombre" in claves
    assert "responsable.documento" in claves


def test_el_94_lleva_la_tabla_de_ajustes_de_protecciones():
    claves = mapa.parametros_de(Proceso.CND, "9.4")
    assert "protecciones.ajustes" in claves
    assert service.DEFINICIONES["protecciones.ajustes"]["tipo"] == "TABLA"


def test_el_93_lleva_el_anexo_4_completo():
    claves = set(mapa.parametros_de(Proceso.CND, "9.3"))
    assert "planta.rata_descarga" in claves            # ultimo de la hoja PLANTA
    assert "unidad.icc_secuencia_negativa" in claves   # ultimo de la hoja UNIDAD
    assert "frontera.latitud" in claves                # reusado del SIC


def test_definicion_item_devuelve_none_para_lo_que_no_existe():
    assert definicion_item(Proceso.SIC, "99") is None
    assert definicion_item("OTRO", "01") is None
