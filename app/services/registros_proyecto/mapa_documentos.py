"""Que parametros contiene cada documento. Este es el mapa de la deduplicacion.

Aqui vive la relacion documento <-> parametro que en un modelo ingenuo seria una
tabla puente. No es una tabla porque no es un dato de operacion: es una
definicion regulatoria. Que la hoja de vida contenga la serie del medidor no
depende del proyecto ni cambia por proyecto -- lo fija el formato CREG 038/2014.
Guardarlo en la base obligaria a sembrar miles de filas identicas para todos los
proyectos y a mantenerlas sincronizadas con el codigo que dibuja los
formularios. Vive en codigo, se revisa en un pull request. Ver decision D-15.

Lo que SI es dato de operacion, y por eso si esta en la base, es de que
documento se saco el valor concreto de un proyecto: `parametros_proyecto.
documento_origen_id`. Esa es la fuente de verdad de cada dato.

Leer el mapa asi: PARAMETROS_POR_ITEM[("SIC", "13")] son las claves que el Acta
de instalacion repite. Ninguna de ellas se transcribe dos veces: el Acta las
muestra, la Hoja de vida las muestra, y las dos apuntan al mismo parametro.
"""

from __future__ import annotations

from app.services.registros_proyecto.catalogo_items import Proceso
from app.services.registros_proyecto.catalogo_parametros import PARAMETROS
from app.services.registros_proyecto.catalogo_parametros_cnd import (
    PARAMETROS_CND,
    REUSADOS_DE_SIC,
)


def _grupo(*grupos: str) -> list[str]:
    """Todas las claves SIC de los grupos indicados."""
    return [p["clave"] for p in PARAMETROS if p["grupo"] in grupos]


def _cnd_grupo(*grupos: str) -> list[str]:
    return [p["clave"] for p in PARAMETROS_CND if p["grupo"] in grupos]


def _prefijo(grupo: str, *sufijos: str) -> list[str]:
    return [f"{grupo}.{s}" for s in sufijos]


# Identidad de un equipo: lo que permite reconocerlo en cualquier documento.
_ID_MEDIDOR = _prefijo("medidor", "numero_de_serie", "marca", "modelo")
_ID_TC = _prefijo("tc", "numero_de_serie", "fabricante", "modelo")
_ID_TP = _prefijo("tp", "numero_de_serie", "fabricante", "modelo")


PARAMETROS_POR_ITEM: dict[tuple[str, str], list[str]] = {

    # ---------------------------------------------------------------- SIC --
    # El documento ancla: contiene TODO el catalogo del sistema de medida.
    # Los demas items del proceso SIC son subconjuntos suyos.
    (Proceso.SIC, "01"): _grupo("novedad", "frontera", "medidor", "tc", "tp",
                                "conductor", "celda", "bornera", "modem",
                                "responsable"),

    (Proceso.SIC, "02"): _ID_MEDIDOR + _prefijo(
        "medidor", "cert_conformidad_numero", "cert_conformidad_fecha_de_emision",
        "cert_conformidad_ente_emisor"),

    (Proceso.SIC, "03"): _ID_TC + _ID_TP + [
        "tc.cert_calibracion_conformidad", "tp.cert_calibracion_conformidad"],

    (Proceso.SIC, "04"): _prefijo(
        "bornera", "tipo_bornera", "fabricante", "cert_conformidad_numero",
        "cert_conformidad_fecha_de_emision", "cert_conformidad_ente_emisor",
        "cert_conformidad_tipo_de_conformidad_de_producto"),

    (Proceso.SIC, "05"): _prefijo(
        "conductor", "calibre", "denominacion", "fabricante",
        "cert_conformidad_numero", "cert_conformidad_fecha_de_emision",
        "cert_conformidad_ente_emisor"),

    (Proceso.SIC, "06"): _prefijo(
        "celda", "fabricante", "cert_conformidad_numero",
        "cert_conformidad_fecha_de_emision", "cert_conformidad_ente_emisor",
        "cert_conformidad_tipo_de_conformidad_de_producto"),

    # El numero de este certificado es el mismo dato que la hoja de vida pide
    # en 3.40.1 / 5.45.1. Un solo parametro, dos documentos que lo muestran.
    (Proceso.SIC, "07"): _ID_MEDIDOR + _prefijo(
        "medidor", "cert_calibracion_numero", "cert_calibracion_fecha_de_emision",
        "cert_calibracion_laboratorio", "fecha_calibracion", "indice_clase_activa",
        "indice_clase_reactiva"),

    # Seis certificados (tres TC, tres TP): el numero de cada uno es el mismo
    # dato que la hoja de vida pide en 6.20.1 y 7.16.1, y que el Acta repite.
    (Proceso.SIC, "08"): _ID_TC + _ID_TP + _prefijo(
        "tc", "cert_calibracion_numero_certificado_1ra_relacion",
        "cert_calibracion_fecha_de_emision", "cert_calibracion_ente_emisor",
        "clase_de_exactitud", "relacion_transformacion") + _prefijo(
        "tp", "cert_calibracion_numero", "cert_calibracion_fecha_de_emision",
        "cert_calibracion_ente_emisor", "clase_de_exactitud",
        "relacion_transformacion"),

    (Proceso.SIC, "09"): _ID_TC + _ID_TP + _prefijo(
        "tc", "cert_pruebas_rutina_numero", "cert_pruebas_rutina_fecha_de_emision"
    ) + _prefijo(
        "tp", "cert_pruebas_rutina_numero", "cert_pruebas_rutina_fecha_de_emision"),

    (Proceso.SIC, "10"): _prefijo(
        "frontera", "fecha_planificada", "fecha_ejecutada",
        "calibracion_del_medidor", "pruebas_de_rutina", "estado_mto"),

    (Proceso.SIC, "11"): ["frontera.nombre_frontera", "frontera.conexion",
                          "frontera.tension_de_servicio"],

    (Proceso.SIC, "12"): ["frontera.factor_de_ajuste_del_punto_de_medicion",
                          "conductor.error_asociado_al_cableado",
                          "conductor.longitud", "conductor.calibre"],

    # El Acta comparte con la hoja de vida todo lo que sigue. Verificado contra
    # el acta real del expediente de muestra (Acta_SanLuisdeSince_58.xlsx):
    # serie/marca/modelo/clase/constante de los dos medidores, numeros de
    # certificado de los seis transformadores, y serie/IP/IMEI de los modems.
    (Proceso.SIC, "13"): _prefijo(
        "frontera", "nombre_frontera", "nombre_de_usuario", "direccion",
        "ciudad_municipio", "departamento", "codigo_sic_rf",
        "tension_de_servicio", "capacidad_instalada",
    ) + _ID_MEDIDOR + _prefijo(
        "medidor", "numero_de_elementos_de_la_conexion", "indice_clase_activa",
        "indice_clase_reactiva", "constante_activa", "constante_reactiva",
        "ano_de_fabricacion", "imax", "tens_nominal", "sellos",
    ) + _ID_TC + _ID_TP + [
        "tc.cert_calibracion_numero_certificado_1ra_relacion",
        "tc.cert_calibracion_ente_emisor", "tc.ano_de_fabricacion",
        "tc.clase_de_exactitud", "tc.relacion_transformacion_en_servicio",
        "tp.cert_calibracion_numero", "tp.cert_calibracion_ente_emisor",
        "tp.ano_de_fabricacion", "tp.clase_de_exactitud",
        "tp.relacion_transformacion",
    ] + _prefijo("modem", "numero_de_serie_modem", "marca_modem", "ip", "imei"),

    (Proceso.SIC, "14"): _ID_MEDIDOR + _prefijo(
        "medidor", "canal_impor_activa", "canal_expor_activa",
        "canal_impor_reactiva", "canal_expor_reactiva", "constante_activa",
        "constante_reactiva", "software_de_lectura_local",
        "software_de_lectura_remota", "puertos_de_comunicacion"),

    (Proceso.SIC, "15"): _prefijo("medidor", "marca", "modelo", "fabricante"
                                  ) + _prefijo("modem", "marca_modem"),

    # Items 16 a 23: carpetas vacias en el expediente de muestra. No se les
    # asigna parametro hasta validar que contienen. Ver D-11.
    (Proceso.SIC, "16"): [],
    (Proceso.SIC, "17"): [],
    (Proceso.SIC, "18"): [],
    (Proceso.SIC, "19"): [],
    (Proceso.SIC, "20"): [],
    (Proceso.SIC, "21"): [],
    (Proceso.SIC, "22"): [],
    (Proceso.SIC, "23"): [],

    # Consumo y generacion sale de la simulacion, que todavia no es una fuente
    # conectada. Sin parametros propios por ahora. Ver D-12.
    (Proceso.SIC, "24"): [],

    (Proceso.SIC, "25"): _grupo("responsable"),

    (Proceso.SIC, "26"): (_prefijo("medidor", "numero_de_serie")
                          + _prefijo("tc", "numero_de_serie")
                          + _prefijo("tp", "numero_de_serie")
                          + _prefijo("modem", "numero_de_serie_modem")),

    (Proceso.SIC, "27"): [],   # no existe todavia; hay que crearlo. Ver D-11.

    (Proceso.SIC, "28"): (_prefijo("medidor", "numero_de_serie", "proveedor_o_representante")
                          + _prefijo("tc", "numero_de_serie", "proveedor_o_representante")
                          + _prefijo("tp", "numero_de_serie", "proveedor_o_representante")),

    # ---------------------------------------------------------------- CND --
    (Proceso.CND, "9.1"): [
        "frontera.nombre_frontera", "frontera.ciudad_municipio",
        "frontera.departamento",
        "conexion.fpo", "conexion.vigencia_aprobacion", "conexion.promotor",
        "conexion.punto_conexion", "conexion.barra_stn_str",
        "conexion.capacidad_transporte_mw", "conexion.tecnologia",
        "conexion.sistema", "conexion.operador_red",
    ],

    (Proceso.CND, "9.2"): [
        "frontera.nombre_frontera", "conexion.agente_representante",
        "planta.capacidad_efectiva_neta",
    ],

    # El Anexo 4 completo. Los seis primeros son los mismos datos que ya pidio
    # la hoja de vida del proceso SIC: se reusan, no se vuelven a pedir.
    (Proceso.CND, "9.3"): (list(REUSADOS_DE_SIC)
                           + _cnd_grupo("planta", "unidad")),

    (Proceso.CND, "9.4"): [
        "frontera.nombre_frontera", "conexion.punto_conexion",
        "conexion.operador_red", "planta.potencia_nominal",
        "protecciones.ajustes", "protecciones.tipo_anti_isla",
    ],

    (Proceso.CND, "9.5"): [],   # pendiente de identificar
    (Proceso.CND, "9.6"): [],   # pendiente de identificar

    (Proceso.CND, "9.7"): [
        "frontera.nombre_frontera", "conexion.punto_conexion",
        "conexion.capacidad_transporte_mw", "conexion.operador_red",
    ],

    (Proceso.CND, "9.8"): [],   # pendiente de identificar

    (Proceso.CND, "9.9"): ["frontera.nombre_frontera", "conexion.operador_red"],

    (Proceso.CND, "9.10"): [
        "frontera.nombre_frontera", "conexion.fecha_entrada_operacion",
        "conexion.agente_representante", "planta.potencia_maxima",
    ],
}


def parametros_de(proceso: str, codigo: str) -> list[str]:
    return PARAMETROS_POR_ITEM.get((proceso, codigo), [])


def items_que_usan(clave: str) -> list[tuple[str, str]]:
    """En que documentos aparece un parametro. Lo contrario del mapa.

    Sirve para responder en la UI "este dato tambien sale en el Acta y en el
    certificado de calibracion", que es lo que justifica diligenciarlo una vez.
    """
    return [k for k, claves in PARAMETROS_POR_ITEM.items() if clave in claves]


def claves_validas() -> set[str]:
    return ({p["clave"] for p in PARAMETROS}
            | {p["clave"] for p in PARAMETROS_CND})


def validar() -> list[str]:
    """Comprueba que el mapa no referencie claves inexistentes.

    Se ejecuta en los tests: un typo aqui deja un formulario sin campo y no se
    nota hasta produccion.
    """
    validas = claves_validas()
    errores = []
    for (proceso, codigo), claves in PARAMETROS_POR_ITEM.items():
        for c in claves:
            if c not in validas:
                errores.append(f"{proceso} {codigo}: clave inexistente {c!r}")
        if len(claves) != len(set(claves)):
            repes = sorted({c for c in claves if claves.count(c) > 1})
            errores.append(f"{proceso} {codigo}: claves repetidas {repes}")
    return errores
