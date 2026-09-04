"""Maquina de estados por etapa. Portado 1:1 de src/lib/domain/stateMachine.ts.

Define, por cada etapa: estado inicial, transiciones permitidas (de -> [a...]), que
hito(s) se completan al ENTRAR en un estado, y el responsable por defecto de cada estado.
Todo es data + funciones puras (sin dependencia de la sesion DB).
"""

from __future__ import annotations

from apps.registros_cnd.services.dominio import Estado as E, Etapa, Hito, Responsable as R


# etapa -> {inicial, transiciones, hitos_al_entrar, responsable_por_estado,
#           soporta_bloqueo?, soporta_vencimiento?}
ETAPA_DEFS: dict[str, dict] = {
    Etapa.ETAPA_1_CREG174_AMBITO: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.SOLICITUD_RADICADA],
            E.SOLICITUD_RADICADA: [E.CREG174_APROBADA, E.VENCIDO],
            E.CREG174_APROBADA: [E.AMBITO_EMITIDO, E.SOLICITUD_RADICADA, E.PRORROGA_SOLICITADA, E.VENCIDO],
            E.AMBITO_EMITIDO: [E.PRORROGA_SOLICITADA, E.SOLICITUD_RADICADA, E.VENCIDO],
            E.PRORROGA_SOLICITADA: [E.PRORROGADO, E.VENCIDO],
            E.PRORROGADO: [E.AMBITO_EMITIDO, E.PRORROGA_SOLICITADA, E.VENCIDO],
            E.VENCIDO: [E.SOLICITUD_RADICADA, E.PRORROGA_SOLICITADA],
        },
        "hitos_al_entrar": {
            E.CREG174_APROBADA: [Hito.H_1A],
            E.AMBITO_EMITIDO: [Hito.H_1B],
        },
        "responsable_por_estado": {
            E.SOLICITUD_RADICADA: R.PROMOTOR,
            E.CREG174_APROBADA: R.OR,
            E.AMBITO_EMITIDO: R.OR,
        },
        "soporta_vencimiento": True,
    },
    Etapa.ETAPA_2_CARTAS_9_1_9_7: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.CARTAS_EN_PREPARACION],
            E.CARTAS_EN_PREPARACION: [E.SOLICITUD_ENVIADA_OR],
            E.SOLICITUD_ENVIADA_OR: [E.EN_FIRMA_OR, E.OBSERVACIONES_OR],
            E.EN_FIRMA_OR: [E.CARTAS_FIRMADAS, E.OBSERVACIONES_OR],
            E.OBSERVACIONES_OR: [E.CARTAS_EN_PREPARACION],
            E.CARTAS_FIRMADAS: [],
        },
        "hitos_al_entrar": {
            E.SOLICITUD_ENVIADA_OR: [Hito.H_2A],
            E.CARTAS_FIRMADAS: [Hito.H_2B],
        },
        "responsable_por_estado": {
            E.CARTAS_EN_PREPARACION: R.PROMOTOR,
            E.SOLICITUD_ENVIADA_OR: R.OR,
            E.EN_FIRMA_OR: R.OR,
            E.CARTAS_FIRMADAS: R.OR,
        },
    },
    Etapa.ETAPA_3_MDC: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.SOLICITUD_ENVIADA_XM],
            E.SOLICITUD_ENVIADA_XM: [E.EN_CREACION_XM],
            E.EN_CREACION_XM: [E.APLICATIVO_CREADO],
            E.APLICATIVO_CREADO: [],
        },
        "hitos_al_entrar": {
            E.SOLICITUD_ENVIADA_XM: [Hito.H_3A],
            E.APLICATIVO_CREADO: [Hito.H_3B],
        },
        "responsable_por_estado": {
            E.SOLICITUD_ENVIADA_XM: R.XM,
            E.EN_CREACION_XM: R.XM,
            E.APLICATIVO_CREADO: R.XM,
        },
    },
    Etapa.ETAPA_4_MONTAJE_9_2: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.CARTAS_MONTADAS_MDC],
            E.CARTAS_MONTADAS_MDC: [E.CARTA_9_2_ENVIADA],
            E.CARTA_9_2_ENVIADA: [E.CARTA_9_2_ACEPTADA, E.OBSERVACIONES_XM],
            E.OBSERVACIONES_XM: [E.CARTAS_MONTADAS_MDC, E.CARTA_9_2_ENVIADA],
            E.CARTA_9_2_ACEPTADA: [],
        },
        "hitos_al_entrar": {
            E.CARTA_9_2_ACEPTADA: [Hito.H_4],
        },
        "responsable_por_estado": {
            E.CARTAS_MONTADAS_MDC: R.PROMOTOR,
            E.CARTA_9_2_ENVIADA: R.PROMOTOR,
            E.OBSERVACIONES_XM: R.XM,
            E.CARTA_9_2_ACEPTADA: R.XM,
        },
    },
    Etapa.ETAPA_5_REQ_9_3: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.RECOPILANDO_INSUMOS],
            E.RECOPILANDO_INSUMOS: [E.EN_DILIGENCIAMIENTO],
            E.EN_DILIGENCIAMIENTO: [E.MONTADO_MDC],
            E.MONTADO_MDC: [E.ACEPTADO_XM, E.OBSERVACIONES_XM],
            E.OBSERVACIONES_XM: [E.EN_DILIGENCIAMIENTO],
            E.ACEPTADO_XM: [],
        },
        "hitos_al_entrar": {
            E.ACEPTADO_XM: [Hito.H_5],
        },
        "responsable_por_estado": {
            E.RECOPILANDO_INSUMOS: R.PROMOTOR,
            E.EN_DILIGENCIAMIENTO: R.PROMOTOR,
            E.MONTADO_MDC: R.PROMOTOR,
            E.OBSERVACIONES_XM: R.XM,
            E.ACEPTADO_XM: R.XM,
        },
    },
    Etapa.ETAPA_6_FRONTERA: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.EQUIPOS_SOLICITADOS],
            E.EQUIPOS_SOLICITADOS: [E.EQUIPOS_EN_LABORATORIO_QUOIA, E.BLOQUEADO],
            E.EQUIPOS_EN_LABORATORIO_QUOIA: [E.EQUIPOS_PARAMETRIZADOS, E.BLOQUEADO],
            E.EQUIPOS_PARAMETRIZADOS: [E.DOCUMENTACION_EN_RECOPILACION, E.BLOQUEADO],
            E.DOCUMENTACION_EN_RECOPILACION: [E.DOCUMENTACION_COMPLETA, E.BLOQUEADO],
            E.DOCUMENTACION_COMPLETA: [],
            E.BLOQUEADO: [
                E.EQUIPOS_SOLICITADOS,
                E.EQUIPOS_EN_LABORATORIO_QUOIA,
                E.EQUIPOS_PARAMETRIZADOS,
                E.DOCUMENTACION_EN_RECOPILACION,
            ],
        },
        "hitos_al_entrar": {
            E.EQUIPOS_SOLICITADOS: [Hito.H_6A],
            E.DOCUMENTACION_COMPLETA: [Hito.H_6B],
        },
        "responsable_por_estado": {
            E.EQUIPOS_SOLICITADOS: R.SOLENIUM,
            E.EQUIPOS_EN_LABORATORIO_QUOIA: R.QUOIA,
            E.EQUIPOS_PARAMETRIZADOS: R.QUOIA,
            E.DOCUMENTACION_EN_RECOPILACION: R.PROMOTOR,
            E.DOCUMENTACION_COMPLETA: R.PROMOTOR,
        },
        "soporta_bloqueo": True,
    },
    Etapa.ETAPA_7_REGISTRO_ASIC: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.EN_VERIFICACION_TERCERO],
            E.EN_VERIFICACION_TERCERO: [E.INSCRITA_ASIC],
            E.INSCRITA_ASIC: [E.CGM_ASIGNADO],
            E.CGM_ASIGNADO: [E.CODIGO_FRT_ASIGNADO],
            E.CODIGO_FRT_ASIGNADO: [E.FRONTERA_EN_OPERACION],
            E.FRONTERA_EN_OPERACION: [],
        },
        "hitos_al_entrar": {
            E.CODIGO_FRT_ASIGNADO: [Hito.H_7],
        },
        "responsable_por_estado": {
            E.EN_VERIFICACION_TERCERO: R.PROMOTOR,
            E.INSCRITA_ASIC: R.ASIC,
            E.CGM_ASIGNADO: R.ASIC,
            E.CODIGO_FRT_ASIGNADO: R.ASIC,
        },
    },
    Etapa.ETAPA_8_REQ_9_4: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.ESPERANDO_VISITA_PROTECCIONES],
            E.ESPERANDO_VISITA_PROTECCIONES: [E.VALORES_RECIBIDOS],
            E.VALORES_RECIBIDOS: [E.CARTA_SOLICITADA_OR],
            E.CARTA_SOLICITADA_OR: [E.FIRMADA_OR],
            E.FIRMADA_OR: [E.MONTADA_MDC],
            E.MONTADA_MDC: [E.APROBADA_XM, E.OBSERVACIONES_XM],
            E.OBSERVACIONES_XM: [E.MONTADA_MDC],
            E.APROBADA_XM: [],
        },
        "hitos_al_entrar": {
            E.CARTA_SOLICITADA_OR: [Hito.H_8A],
            E.FIRMADA_OR: [Hito.H_8B],
            E.APROBADA_XM: [Hito.H_8C],
        },
        "responsable_por_estado": {
            E.ESPERANDO_VISITA_PROTECCIONES: R.SOLENIUM,
            E.VALORES_RECIBIDOS: R.SOLENIUM,
            E.CARTA_SOLICITADA_OR: R.OR,
            E.FIRMADA_OR: R.OR,
            E.MONTADA_MDC: R.PROMOTOR,
            E.OBSERVACIONES_XM: R.XM,
            E.APROBADA_XM: R.XM,
        },
    },
    # --- Etapas futuras (enum previsto, sin hitos ni UI) ---
    Etapa.CONSTRUCCION: {
        "inicial": E.NO_INICIADO,
        "transiciones": {E.NO_INICIADO: [E.EN_OBRA], E.EN_OBRA: [E.TERMINADA], E.TERMINADA: []},
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.INTERVENTORIA_PROTECCIONES: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.EN_REVISION],
            E.EN_REVISION: [E.NO_CONFORMIDADES, E.CERRADA],
            E.NO_CONFORMIDADES: [E.EN_REVISION],
            E.CERRADA: [],
        },
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.ENERGIZACION: {
        "inicial": E.NO_INICIADO,
        "transiciones": {E.NO_INICIADO: [E.SOLICITADA], E.SOLICITADA: [E.APROBADA], E.APROBADA: []},
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.CARTA_9_5: {
        "inicial": E.NO_INICIADO,
        "transiciones": {E.NO_INICIADO: [E.SOLICITADA], E.SOLICITADA: [E.FIRMADA_OR], E.FIRMADA_OR: []},
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.REQUISITO_9_6: {
        "inicial": E.NO_INICIADO,
        "transiciones": {E.NO_INICIADO: [E.ENVIADO], E.ENVIADO: [E.CONFIRMADO], E.CONFIRMADO: []},
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.PRUEBAS_GENERACION: {
        "inicial": E.NO_INICIADO,
        "transiciones": {E.NO_INICIADO: [E.EN_PRUEBAS], E.EN_PRUEBAS: [E.CERRADO], E.CERRADO: []},
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
    Etapa.CARTA_9_9: {
        "inicial": E.NO_INICIADO,
        "transiciones": {
            E.NO_INICIADO: [E.SOLICITADA],
            E.SOLICITADA: [E.FIRMADA_OR],
            E.FIRMADA_OR: [E.CERRADO],
            E.CERRADO: [],
        },
        "hitos_al_entrar": {},
        "responsable_por_estado": {},
    },
}


class TransicionInvalidaError(Exception):
    def __init__(self, etapa: str, de: str, a: str):
        self.etapa = etapa
        self.de = de
        self.a = a
        permitidas = ", ".join(transiciones_permitidas(etapa, de)) or "ninguna"
        super().__init__(
            f"Transicion invalida en {etapa}: {de} -> {a}. Permitidas desde {de}: [{permitidas}]"
        )


def get_etapa_def(etapa: str) -> dict:
    d = ETAPA_DEFS.get(etapa)
    if d is None:
        raise ValueError(f"Etapa desconocida: {etapa}")
    return d


def transiciones_permitidas(etapa: str, estado: str) -> list[str]:
    return get_etapa_def(etapa)["transiciones"].get(estado, [])


def es_transicion_valida(etapa: str, de: str, a: str) -> bool:
    return a in transiciones_permitidas(etapa, de)


def hitos_completados_al_entrar(etapa: str, estado: str) -> list[str]:
    return get_etapa_def(etapa)["hitos_al_entrar"].get(estado, [])


def responsable_de_estado(etapa: str, estado: str) -> str | None:
    return get_etapa_def(etapa).get("responsable_por_estado", {}).get(estado)


def es_estado_final(etapa: str, estado: str) -> bool:
    return len(transiciones_permitidas(etapa, estado)) == 0
