"""Fuente de verdad del dominio de "Registros CND/ASIC": etapas, estados, hitos,
responsables, la ponderacion de avance y las reglas de vigencia.

Portado 1:1 del prototipo (src/lib/domain/enums.ts). Los valores viajan como String
a la base de datos; aqui viven las constantes, la metadata y la ponderacion.

Referencias del skill seguimiento-conexion-xm:
 - ponderacion de avance (hitos 1a-8c, suma 100%)
 - etapas, estados y transiciones (ver state_machine.py)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Etapas del proceso
# ---------------------------------------------------------------------------
class Etapa:
    # Alcance actual (hasta aprobacion 9.4 = 100%)
    ETAPA_1_CREG174_AMBITO = "ETAPA_1_CREG174_AMBITO"
    ETAPA_2_CARTAS_9_1_9_7 = "ETAPA_2_CARTAS_9_1_9_7"
    ETAPA_3_MDC = "ETAPA_3_MDC"
    ETAPA_4_MONTAJE_9_2 = "ETAPA_4_MONTAJE_9_2"
    ETAPA_5_REQ_9_3 = "ETAPA_5_REQ_9_3"
    ETAPA_6_FRONTERA = "ETAPA_6_FRONTERA"
    ETAPA_7_REGISTRO_ASIC = "ETAPA_7_REGISTRO_ASIC"
    ETAPA_8_REQ_9_4 = "ETAPA_8_REQ_9_4"
    # Futuras (enum previsto, sin logica ni UI)
    CONSTRUCCION = "CONSTRUCCION"
    INTERVENTORIA_PROTECCIONES = "INTERVENTORIA_PROTECCIONES"
    ENERGIZACION = "ENERGIZACION"
    CARTA_9_5 = "CARTA_9_5"
    REQUISITO_9_6 = "REQUISITO_9_6"
    PRUEBAS_GENERACION = "PRUEBAS_GENERACION"
    CARTA_9_9 = "CARTA_9_9"


ETAPAS_ACTUALES: list[str] = [
    Etapa.ETAPA_1_CREG174_AMBITO,
    Etapa.ETAPA_2_CARTAS_9_1_9_7,
    Etapa.ETAPA_3_MDC,
    Etapa.ETAPA_4_MONTAJE_9_2,
    Etapa.ETAPA_5_REQ_9_3,
    Etapa.ETAPA_6_FRONTERA,
    Etapa.ETAPA_7_REGISTRO_ASIC,
    Etapa.ETAPA_8_REQ_9_4,
]

ETAPAS_FUTURAS: list[str] = [
    Etapa.CONSTRUCCION,
    Etapa.INTERVENTORIA_PROTECCIONES,
    Etapa.ENERGIZACION,
    Etapa.CARTA_9_5,
    Etapa.REQUISITO_9_6,
    Etapa.PRUEBAS_GENERACION,
    Etapa.CARTA_9_9,
]

ETIQUETAS_ETAPA: dict[str, str] = {
    Etapa.ETAPA_1_CREG174_AMBITO: "1. CREG 174 y ambito de conexion",
    Etapa.ETAPA_2_CARTAS_9_1_9_7: "2. Cartas 9.1 y 9.7 (OR)",
    Etapa.ETAPA_3_MDC: "3. Creacion en el aplicativo MDC (XM)",
    Etapa.ETAPA_4_MONTAJE_9_2: "4. Montaje 9.1/9.7 y carta 9.2",
    Etapa.ETAPA_5_REQ_9_3: "5. Requisito 9.3 (parametros tecnicos)",
    Etapa.ETAPA_6_FRONTERA: "6. Documentacion y equipos de frontera",
    Etapa.ETAPA_7_REGISTRO_ASIC: "7. Registro de frontera (ASIC) y codigos FRT",
    Etapa.ETAPA_8_REQ_9_4: "8. Requisito 9.4 (protecciones)",
    Etapa.CONSTRUCCION: "Construccion",
    Etapa.INTERVENTORIA_PROTECCIONES: "Interventoria y protecciones",
    Etapa.ENERGIZACION: "Energizacion",
    Etapa.CARTA_9_5: "Carta 9.5 (equipos a conectar)",
    Etapa.REQUISITO_9_6: "Requisito 9.6 (envio codigos FRT)",
    Etapa.PRUEBAS_GENERACION: "Pruebas de generacion",
    # El rotulo decia "inicio de operacion y cierre". Las cartas reales del expediente
    # dicen otra cosa: la 9.9 es la certificacion de cumplimiento que emite el
    # transportador, y el inicio de operacion es la 9.10 (Acuerdo CNO 1899). Se corrige
    # solo la etiqueta: el valor persistido sigue siendo CARTA_9_9. El modulo no tiene
    # todavia una etapa propia para el 9.10 (ver D-19).
    Etapa.CARTA_9_9: "Carta 9.9 (certificacion de cumplimiento de la reglamentacion)",
}


# ---------------------------------------------------------------------------
# Estados (canonicos + especiales + futuros)
# ---------------------------------------------------------------------------
class Estado:
    NO_INICIADO = "NO_INICIADO"
    # Etapa 1
    SOLICITUD_RADICADA = "SOLICITUD_RADICADA"
    CREG174_APROBADA = "CREG174_APROBADA"
    AMBITO_EMITIDO = "AMBITO_EMITIDO"
    PRORROGA_SOLICITADA = "PRORROGA_SOLICITADA"
    PRORROGADO = "PRORROGADO"
    # Etapa 2
    CARTAS_EN_PREPARACION = "CARTAS_EN_PREPARACION"
    SOLICITUD_ENVIADA_OR = "SOLICITUD_ENVIADA_OR"
    EN_FIRMA_OR = "EN_FIRMA_OR"
    OBSERVACIONES_OR = "OBSERVACIONES_OR"
    CARTAS_FIRMADAS = "CARTAS_FIRMADAS"
    # Etapa 3
    SOLICITUD_ENVIADA_XM = "SOLICITUD_ENVIADA_XM"
    EN_CREACION_XM = "EN_CREACION_XM"
    APLICATIVO_CREADO = "APLICATIVO_CREADO"
    # Etapa 4
    CARTAS_MONTADAS_MDC = "CARTAS_MONTADAS_MDC"
    CARTA_9_2_ENVIADA = "CARTA_9_2_ENVIADA"
    CARTA_9_2_ACEPTADA = "CARTA_9_2_ACEPTADA"
    # Etapa 5
    RECOPILANDO_INSUMOS = "RECOPILANDO_INSUMOS"
    EN_DILIGENCIAMIENTO = "EN_DILIGENCIAMIENTO"
    MONTADO_MDC = "MONTADO_MDC"
    ACEPTADO_XM = "ACEPTADO_XM"
    # Etapa 6
    EQUIPOS_SOLICITADOS = "EQUIPOS_SOLICITADOS"
    EQUIPOS_EN_LABORATORIO_QUOIA = "EQUIPOS_EN_LABORATORIO_QUOIA"
    EQUIPOS_PARAMETRIZADOS = "EQUIPOS_PARAMETRIZADOS"
    DOCUMENTACION_EN_RECOPILACION = "DOCUMENTACION_EN_RECOPILACION"
    DOCUMENTACION_COMPLETA = "DOCUMENTACION_COMPLETA"
    # Etapa 7
    EN_VERIFICACION_TERCERO = "EN_VERIFICACION_TERCERO"
    INSCRITA_ASIC = "INSCRITA_ASIC"
    CGM_ASIGNADO = "CGM_ASIGNADO"
    CODIGO_FRT_ASIGNADO = "CODIGO_FRT_ASIGNADO"
    FRONTERA_EN_OPERACION = "FRONTERA_EN_OPERACION"
    # Etapa 8
    ESPERANDO_VISITA_PROTECCIONES = "ESPERANDO_VISITA_PROTECCIONES"
    VALORES_RECIBIDOS = "VALORES_RECIBIDOS"
    CARTA_SOLICITADA_OR = "CARTA_SOLICITADA_OR"
    FIRMADA_OR = "FIRMADA_OR"
    MONTADA_MDC = "MONTADA_MDC"
    APROBADA_XM = "APROBADA_XM"
    # Observaciones de XM (reutilizado en etapas 4, 5, 8)
    OBSERVACIONES_XM = "OBSERVACIONES_XM"
    # Especiales transversales
    VENCIDO = "VENCIDO"
    BLOQUEADO = "BLOQUEADO"
    # Futuros
    EN_OBRA = "EN_OBRA"
    TERMINADA = "TERMINADA"
    EN_REVISION = "EN_REVISION"
    NO_CONFORMIDADES = "NO_CONFORMIDADES"
    CERRADA = "CERRADA"
    SOLICITADA = "SOLICITADA"
    APROBADA = "APROBADA"
    ENVIADO = "ENVIADO"
    CONFIRMADO = "CONFIRMADO"
    EN_PRUEBAS = "EN_PRUEBAS"
    CERRADO = "CERRADO"


# ---------------------------------------------------------------------------
# Hitos 1a-8c (ponderacion de avance). Suma de pesos por defecto = 100%.
# ---------------------------------------------------------------------------
class Hito:
    H_1A = "1a"
    H_1B = "1b"
    H_2A = "2a"
    H_2B = "2b"
    H_3A = "3a"
    H_3B = "3b"
    H_4 = "4"
    H_5 = "5"
    H_6A = "6a"
    H_6B = "6b"
    H_7 = "7"
    H_8A = "8a"
    H_8B = "8b"
    H_8C = "8c"


# Cada hito guarda su clave (== codigo "1a".."8c"), etapa, peso por defecto y descripcion.
HITOS: list[dict] = [
    {"key": Hito.H_1A, "etapa": Etapa.ETAPA_1_CREG174_AMBITO, "peso_default": 8, "descripcion": "CREG 174 (factibilidad) aprobada"},
    {"key": Hito.H_1B, "etapa": Etapa.ETAPA_1_CREG174_AMBITO, "peso_default": 7, "descripcion": "Ambito de conexion emitido (punto exacto)"},
    {"key": Hito.H_2A, "etapa": Etapa.ETAPA_2_CARTAS_9_1_9_7, "peso_default": 5, "descripcion": "Solicitud de cartas 9.1 y 9.7 enviada al OR"},
    {"key": Hito.H_2B, "etapa": Etapa.ETAPA_2_CARTAS_9_1_9_7, "peso_default": 10, "descripcion": "Cartas 9.1 y 9.7 firmadas por el OR"},
    {"key": Hito.H_3A, "etapa": Etapa.ETAPA_3_MDC, "peso_default": 3, "descripcion": "Solicitud a XM de creacion en el aplicativo MDC"},
    {"key": Hito.H_3B, "etapa": Etapa.ETAPA_3_MDC, "peso_default": 7, "descripcion": "Proyecto creado en el aplicativo MDC"},
    {"key": Hito.H_4, "etapa": Etapa.ETAPA_4_MONTAJE_9_2, "peso_default": 5, "descripcion": "Cartas 9.1/9.7 montadas + carta 9.2 diligenciada y aceptada"},
    {"key": Hito.H_5, "etapa": Etapa.ETAPA_5_REQ_9_3, "peso_default": 10, "descripcion": "Requisito 9.3 diligenciado, montado y aceptado por XM"},
    {"key": Hito.H_6A, "etapa": Etapa.ETAPA_6_FRONTERA, "peso_default": 5, "descripcion": "Documentacion de frontera solicitada (Solenium)"},
    {"key": Hito.H_6B, "etapa": Etapa.ETAPA_6_FRONTERA, "peso_default": 10, "descripcion": "Documentacion de frontera completa (equipos parametrizados en Quoia)"},
    {"key": Hito.H_7, "etapa": Etapa.ETAPA_7_REGISTRO_ASIC, "peso_default": 15, "descripcion": "Frontera registrada ante el ASIC + codigos FRT recibidos"},
    {"key": Hito.H_8A, "etapa": Etapa.ETAPA_8_REQ_9_4, "peso_default": 3, "descripcion": "Carta 9.4 solicitada (tras visita de protecciones)"},
    {"key": Hito.H_8B, "etapa": Etapa.ETAPA_8_REQ_9_4, "peso_default": 5, "descripcion": "Carta 9.4 firmada por el OR"},
    {"key": Hito.H_8C, "etapa": Etapa.ETAPA_8_REQ_9_4, "peso_default": 7, "descripcion": "Carta 9.4 montada en el MDC y aprobada por XM"},
]

HITOS_POR_KEY: dict[str, dict] = {h["key"]: h for h in HITOS}


# ---------------------------------------------------------------------------
# Responsables
# ---------------------------------------------------------------------------
class Responsable:
    PROMOTOR = "PROMOTOR"
    OR = "OR"
    XM = "XM"
    ASIC = "ASIC"
    SOLENIUM = "SOLENIUM"
    QUOIA = "QUOIA"


# ---------------------------------------------------------------------------
# Reglas de vigencia (CREG 174 / ambito)
# ---------------------------------------------------------------------------
def meses_vigencia_conexion(clasificacion_o_tipo: str | None, tecnologia: str | None = None) -> int:
    """Meses de vigencia de la aprobacion de conexion segun clasificacion y tecnologia.

    GD/AGPE/DER/autoconsumo: 6 meses; hidraulica: 24; otras AGGE: 12. (comparacion
    case-insensitive contra clasificacion_regulatoria o tipo_proyecto del Proyecto.)
    """
    tec = (tecnologia or "").strip().lower()
    if tec == "hidraulica":
        return 24
    v = (clasificacion_o_tipo or "").strip().lower()
    if v in ("gd", "agpe", "der", "autoconsumo", "agp"):
        return 6
    if v == "agge":
        return 12
    return 6


# ---------------------------------------------------------------------------
# Catalogos auxiliares (tipos de alerta, documento, equipo, estados)
# ---------------------------------------------------------------------------
class TipoAlerta:
    VENCIMIENTO_VIGENCIA = "VENCIMIENTO_VIGENCIA"
    EQUIPOS_FRONTERA_90D = "EQUIPOS_FRONTERA_90D"
    MEDIDOR_OR_15DH = "MEDIDOR_OR_15DH"
    ETAPA_ESTANCADA = "ETAPA_ESTANCADA"
    CALIBRACION_POR_VENCER = "CALIBRACION_POR_VENCER"


class EstadoAlerta:
    PENDIENTE = "PENDIENTE"
    NOTIFICADA = "NOTIFICADA"
    RESUELTA = "RESUELTA"


class TipoVisitaProtecciones:
    VIRTUAL = "VIRTUAL"
    PRESENCIAL = "PRESENCIAL"


class TipoDocumento:
    CREG_174 = "CREG_174"
    AMBITO = "AMBITO"
    CARTA_9_1 = "CARTA_9_1"
    CARTA_9_2 = "CARTA_9_2"
    CARTA_9_4 = "CARTA_9_4"
    CARTA_9_5 = "CARTA_9_5"
    CARTA_9_7 = "CARTA_9_7"
    CARTA_9_9 = "CARTA_9_9"
    REQ_9_3_XLSX = "REQ_9_3_XLSX"
    JUSTIFICACION_9_3 = "JUSTIFICACION_9_3"
    CERT_CONFORMIDAD = "CERT_CONFORMIDAD"
    CERT_CALIBRACION = "CERT_CALIBRACION"
    UNIFILAR = "UNIFILAR"
    MEMORIA_CALCULO = "MEMORIA_CALCULO"
    DATASHEET = "DATASHEET"
    FOTOS_EQUIPOS = "FOTOS_EQUIPOS"
    FACTURA = "FACTURA"
    CERT_VERIFICACION_CAC = "CERT_VERIFICACION_CAC"
    CORREO = "CORREO"
    OTRO = "OTRO"


class EstadoDocumento:
    BORRADOR = "BORRADOR"
    ENVIADO = "ENVIADO"
    FIRMADO = "FIRMADO"
    OBSERVADO = "OBSERVADO"
    APROBADO = "APROBADO"
    VENCIDO = "VENCIDO"


class TipoEquipoFrontera:
    MEDIDOR_PRINCIPAL = "MEDIDOR_PRINCIPAL"
    MEDIDOR_RESPALDO = "MEDIDOR_RESPALDO"
    TC = "TC"
    TP = "TP"
    MODEM = "MODEM"
    CELDA = "CELDA"
    BLOQUE_PRUEBAS = "BLOQUE_PRUEBAS"
    CABLE_CONTROL = "CABLE_CONTROL"
