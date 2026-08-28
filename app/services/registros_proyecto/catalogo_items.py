"""Catalogo de items documentales por proceso. Fuente de verdad del timeline.

Un "item" es una casilla del expediente: el numeral 07 del proceso SIC, el 9.3
del proceso CND. No es un archivo: un item puede tener varios archivos montados
(el 08 lleva seis certificados de calibracion, el 26 lleva las fotos de cada
equipo) o ninguno todavia.

Los nombres y la numeracion del proceso SIC estan tomados de las carpetas reales
del expediente (Contexto_registros/ASIC/), no de una lista teorica. Los del
proceso CND, del Anexo 1 del Acuerdo CNO 1937 y de las cartas reales
(Contexto_registros/CND/).

Campos de cada item:
  proceso      SIC | CND
  codigo       "01".."28" para SIC, "9.1".."9.10" para CND
  titulo       nombre del item tal como aparece en el expediente
  descripcion  que contiene y de donde sale
  emisor       quien lo produce (UNERGY | OR | XM | LABORATORIO | FABRICANTE)
  multiple     admite varios archivos (uno por equipo, por fase, por foto...)
  estado_base  CONFIRMADO  el item esta validado contra la carpeta real
               PENDIENTE   falta validar contenido o no existe todavia
  nota         solo para los PENDIENTE: que falta y por que
"""

from __future__ import annotations


class Proceso:
    SIC = "SIC"
    CND = "CND"


ETIQUETAS_PROCESO = {
    Proceso.SIC: "SIC / ASIC - registro de frontera comercial",
    Proceso.CND: "CND - conexion ante XM (Acuerdo CNO 1937)",
}


# ---------------------------------------------------------------------------
# Proceso SIC: carpetas 01..28 del expediente de frontera comercial.
# Verificado contra Contexto_registros/ASIC/ el 2026-08-27.
# ---------------------------------------------------------------------------
ITEMS_SIC: list[dict] = [
    {"codigo": "01", "titulo": "Hoja de vida del sistema de medicion",
     "descripcion": "Documento ancla del expediente. Concentra la informacion de la "
                    "frontera y de cada equipo (medidores, TC, TP, conductores, celdas, "
                    "bornera, modems). Formato oficial CREG 038/2014.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "02", "titulo": "Certificado de conformidad del medidor",
     "descripcion": "Certificado de producto del medidor emitido por un organismo "
                    "acreditado (CIDET en el expediente de muestra).",
     "emisor": "FABRICANTE", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "03", "titulo": "Certificados de conformidad de transformadores de medida",
     "descripcion": "Certificados de producto de los TC y TP.",
     "emisor": "FABRICANTE", "multiple": True, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra; el item existe y aplica."},

    {"codigo": "04", "titulo": "Certificado de conformidad de la bornera de pruebas",
     "descripcion": "Certificado RETIE / de producto del bloque o bornera de pruebas.",
     "emisor": "FABRICANTE", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "05", "titulo": "Certificado de producto de cables",
     "descripcion": "Certificado de conformidad de los conductores de senal de "
                    "corriente y de tension.",
     "emisor": "FABRICANTE", "multiple": True, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra."},

    {"codigo": "06", "titulo": "Certificado de producto de la celda",
     "descripcion": "Certificado de conformidad de la celda o caja de seguridad.",
     "emisor": "FABRICANTE", "multiple": True, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra."},

    {"codigo": "07", "titulo": "Certificados de calibracion de medidores",
     "descripcion": "Certificado de calibracion del medidor principal y del de respaldo.",
     "emisor": "LABORATORIO", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "08", "titulo": "Certificados de calibracion de transformadores",
     "descripcion": "Un certificado por cada TC y cada TP (seis en el expediente de "
                    "muestra: tres de corriente y tres de tension).",
     "emisor": "LABORATORIO", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "09", "titulo": "Pruebas de rutina de transformadores",
     "descripcion": "Certificados de pruebas de rutina de los transformadores de medida.",
     "emisor": "LABORATORIO", "multiple": True, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra."},

    {"codigo": "10", "titulo": "Protocolo para el mantenimiento del sistema de medida",
     "descripcion": "Procedimiento de mantenimiento preventivo del sistema de medicion.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra."},

    {"codigo": "11", "titulo": "Diagrama unifilar y planos del sistema de medida",
     "descripcion": "Unifilar y planos electricos del sistema de medicion.",
     "emisor": "UNERGY", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "12", "titulo": "Memorias de calculo del sistema de medida",
     "descripcion": "Memoria de calculo del factor de ajuste del punto de medicion y "
                    "del error asociado al cableado.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO",
     "nota": "Carpeta vacia en el expediente de muestra."},

    {"codigo": "13", "titulo": "Acta de instalacion del sistema de medida",
     "descripcion": "Acta de revision y/o instalacion firmada en sitio. Repite datos "
                    "de la hoja de vida (item 01) y agrega los suyos: lecturas, "
                    "porcentajes de error por fase, sellos instalados y retirados, "
                    "verificacion de telemedida y firmas.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "14", "titulo": "Pagina base de medidores",
     "descripcion": "Reporte de configuracion / pagina base de cada medidor.",
     "emisor": "UNERGY", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "15", "titulo": "Documentacion tecnica del sistema de medida",
     "descripcion": "Manuales y fichas tecnicas de medidores y modems.",
     "emisor": "FABRICANTE", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "16", "titulo": "Parametros, procedimientos y politicas del CGM",
     "descripcion": "Parametros de procedimientos y politicas del Centro de Gestion "
                    "de Medida.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "17", "titulo": "Esquema de telemedida y comunicaciones",
     "descripcion": "Esquema de la arquitectura de telemedida y comunicaciones.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "18", "titulo": "Condiciones de operacion del CGM",
     "descripcion": "Condiciones de operacion del Centro de Gestion de Medida.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "19", "titulo": "Documentacion de la critica de informacion",
     "descripcion": "Procedimiento de critica de la informacion de medida.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "20", "titulo": "Documentacion para la validacion de datos",
     "descripcion": "Procedimiento de validacion de datos de medida.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "21", "titulo": "Documentacion de mecanismos de proteccion",
     "descripcion": "Mecanismos de proteccion de la informacion de medida.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "22", "titulo": "Documentacion de politicas de seguridad fisica",
     "descripcion": "Politicas de seguridad fisica del sistema de medicion.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "23", "titulo": "Documentacion del procedimiento de transmision de datos",
     "descripcion": "Procedimiento de transmision de datos al ASIC.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "Carpeta vacia en el expediente de muestra: falta validar que contiene."},

    {"codigo": "24", "titulo": "Consumo y generacion",
     "descripcion": "Informe de consumo y generacion del proyecto. Proviene de la "
                    "simulacion, no se diligencia a mano en este expediente.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO",
     "nota": "La simulacion todavia no es una fuente conectada a la plataforma; "
             "por ahora el informe se monta como archivo. Ver decision D-12."},

    {"codigo": "25", "titulo": "Matricula profesional",
     "descripcion": "Matricula profesional del ingeniero que firma el expediente.",
     "emisor": "UNERGY", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "26", "titulo": "Registro fotografico",
     "descripcion": "Fotos de cada elemento del sistema de medicion: medidores, "
                    "modems, cada TC y cada TP.",
     "emisor": "UNERGY", "multiple": True, "estado_base": "CONFIRMADO"},

    {"codigo": "27", "titulo": "Plataforma de registro de frontera",
     "descripcion": "Soporte del registro de la frontera en la plataforma del ASIC.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "No existe fisicamente en las carpetas actuales: hay que crearlo y "
             "montarlo aparte. No bloquea el resto del expediente. Ver D-11."},

    {"codigo": "28", "titulo": "Certificados de compra",
     "descripcion": "Ordenes de compra de los equipos del sistema de medicion.",
     "emisor": "UNERGY", "multiple": True, "estado_base": "CONFIRMADO"},
]


# ---------------------------------------------------------------------------
# Proceso CND: numerales 9.1 a 9.10 del Anexo 1 del Acuerdo CNO 1937.
#
# Sobre el "SENE" mencionado al plantear el trabajo: no existe. Ni el codigo ni
# los documentos del expediente lo nombran. Los subitems 9.1 a 9.10 son los
# numerales de ese anexo, y son el proceso CND. No hay un tercer proceso.
# Ver decision D-02.
# ---------------------------------------------------------------------------
ITEMS_CND: list[dict] = [
    {"codigo": "9.1", "titulo": "Registro del proyecto ante el CND",
     "descripcion": "El OR informa al CND las caracteristicas del proyecto: nombre, "
                    "FPO, vigencia de la aprobacion de conexion, promotor, punto de "
                    "conexion, barra del STR donde se refleja, capacidad de "
                    "transporte, ubicacion y tecnologia.",
     "emisor": "OR", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "9.2", "titulo": "Agente generador que representara el proyecto",
     "descripcion": "El agente informa a XM que representara el proyecto y su "
                    "capacidad efectiva neta (Anexo 1 del Acuerdo CNO 1612).",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "9.3", "titulo": "Parametros tecnicos para el planeamiento operativo",
     "descripcion": "Anexo 4 del Acuerdo 1816. Dos hojas: PLANTA (informacion basica, "
                    "datos tecnicos generales, parametros electricos, control y "
                    "respuesta) y UNIDAD EQUIVALENTE (voltajes, frecuencias, "
                    "impedancia, datos del inversor y niveles de cortocircuito).",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "9.4", "titulo": "Cumplimiento de requisitos de protecciones",
     "descripcion": "El OR declara el cumplimiento de los requisitos de protecciones "
                    "del Acuerdo CNO 1862 e incluye la tabla de ajustes de tension, "
                    "frecuencia y anti-isla (ROCOF).",
     "emisor": "OR", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "9.5", "titulo": "Equipos a conectar",
     "descripcion": "Carta de equipos a conectar.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "No esta en el expediente de muestra. El titulo viene del enum del "
             "modulo registros_cnd existente, no de un documento real: validar "
             "contra el Acuerdo CNO 1937 antes de darlo por bueno."},

    {"codigo": "9.6", "titulo": "Envio de codigos de frontera (FRT)",
     "descripcion": "Requisito de envio de los codigos FRT asignados.",
     "emisor": "UNERGY", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "No esta en el expediente de muestra. Titulo tomado del enum existente: "
             "validar contra el Acuerdo CNO 1937."},

    {"codigo": "9.7", "titulo": "Certificado de conexion y capacidad de transporte asignada",
     "descripcion": "El transportador del area certifica que aprueba la conexion del "
                    "proyecto e informa la capacidad de transporte asignada.",
     "emisor": "OR", "multiple": False, "estado_base": "CONFIRMADO"},

    {"codigo": "9.8", "titulo": "Pendiente de identificar",
     "descripcion": "",
     "emisor": "", "multiple": False, "estado_base": "PENDIENTE",
     "nota": "No esta en el expediente de muestra ni en el enum del modulo existente. "
             "Hay que leer el Anexo 1 del Acuerdo CNO 1937 para saber que numeral es. "
             "Se deja la casilla creada para no romper la numeracion."},

    {"codigo": "9.9", "titulo": "Certificacion de cumplimiento de la reglamentacion vigente",
     "descripcion": "El transportador que entrega el punto de conexion certifica que "
                    "la conexion cumplio el procedimiento y la reglamentacion.",
     "emisor": "OR", "multiple": False, "estado_base": "CONFIRMADO",
     "nota": "El enum del modulo registros_cnd rotula 9.9 como 'inicio de operacion y "
             "cierre'. La carta real dice otra cosa: el inicio de operacion es el "
             "9.10. Corregir el enum o dejarlo documentado. Ver D-10."},

    {"codigo": "9.10", "titulo": "Declaracion de entrada en operacion",
     "descripcion": "El agente declara ante el CND la fecha y hora de entrada en "
                    "operacion del proyecto y su capacidad maxima (Acuerdo CNO 1899).",
     "emisor": "UNERGY", "multiple": False, "estado_base": "CONFIRMADO"},
]


ITEMS: list[dict] = (
    [dict(i, proceso=Proceso.SIC) for i in ITEMS_SIC]
    + [dict(i, proceso=Proceso.CND) for i in ITEMS_CND]
)

ITEMS_POR_PROCESO: dict[str, list[dict]] = {
    Proceso.SIC: [i for i in ITEMS if i["proceso"] == Proceso.SIC],
    Proceso.CND: [i for i in ITEMS if i["proceso"] == Proceso.CND],
}

ITEMS_POR_CLAVE: dict[tuple[str, str], dict] = {
    (i["proceso"], i["codigo"]): i for i in ITEMS
}


def item(proceso: str, codigo: str) -> dict | None:
    return ITEMS_POR_CLAVE.get((proceso, codigo))


def existe(proceso: str, codigo: str) -> bool:
    return (proceso, codigo) in ITEMS_POR_CLAVE
