"""Generadores de alertas. Portado de src/lib/domain/alertas.ts.

 - VENCIMIENTO_VIGENCIA: a -60, -30 y -15 dias del vencimiento de CREG 174 / ambito.
 - EQUIPOS_FRONTERA_90D: si (fecha_conexion_estimada - hoy) < 90 dias y no se han
   solicitado los equipos a Solenium.
 - MEDIDOR_OR_15DH: si el proyecto exporta y el comercializador es el OR, el medidor
   debe llegar al OR 15 dias habiles antes de la visita tecnica.
 - ETAPA_ESTANCADA: SOLICITUD_ENVIADA_OR / SOLICITUD_ENVIADA_XM > 10 dias habiles;
   ESPERANDO_VISITA_PROTECCIONES sin agenda.
 - CALIBRACION_POR_VENCER: calibracion de equipos de frontera proxima a vencer.

Funciones puras: reciben un snapshot del registro y la fecha de referencia `hoy`.
El `dedupe_key` de cada alerta evita duplicados al re-ejecutar el motor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.services.registros_cnd.dominio import Estado, TipoAlerta


@dataclass
class AlertaGenerada:
    tipo: str
    fecha_disparo: date
    mensaje: str
    dedupe_key: str


@dataclass
class EtapaSnapshot:
    etapa: str
    estado_actual: str
    fecha_estado: date


@dataclass
class EquipoSnapshot:
    tipo: str
    serial: str | None = None
    fecha_vencimiento_calibracion: date | None = None
    fecha_envio_or: date | None = None


@dataclass
class ProyectoSnapshot:
    id: int
    nombre_comercial: str
    fecha_conexion_estimada: date | None = None
    vigencia_conexion: date | None = None  # vencimiento CREG 174 / ambito
    equipos_solicitados: bool = False
    exporta: bool = False
    comercializador_es_or: bool = False
    fecha_visita_protecciones: date | None = None
    etapas: list[EtapaSnapshot] = field(default_factory=list)
    equipos: list[EquipoSnapshot] = field(default_factory=list)


def dias_calendario(a: date, b: date) -> int:
    """Dias calendario desde `a` hasta `b` (positivo si b es posterior)."""
    return (b - a).days


def _es_fin_de_semana(d: date) -> bool:
    return d.weekday() >= 5  # 5 sab, 6 dom


def dias_habiles_entre(desde: date, hasta: date) -> int:
    """Dias habiles (lun-vie) en el intervalo (desde, hasta]. Sin festivos (fuera de alcance)."""
    if hasta <= desde:
        return 0
    from datetime import timedelta
    cuenta = 0
    cur = desde
    while cur < hasta:
        cur = cur + timedelta(days=1)
        if not _es_fin_de_semana(cur):
            cuenta += 1
    return cuenta


UMBRALES_VIGENCIA = (60, 30, 15)


def alertas_vigencia(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    if not p.vigencia_conexion:
        return []
    restantes = dias_calendario(hoy, p.vigencia_conexion)
    out: list[AlertaGenerada] = []
    if restantes < 0:
        out.append(AlertaGenerada(
            tipo=TipoAlerta.VENCIMIENTO_VIGENCIA,
            fecha_disparo=hoy,
            mensaje=f'La vigencia de conexion de "{p.nombre_comercial}" esta VENCIDA hace {abs(restantes)} dias. Requiere prorroga o nueva solicitud.',
            dedupe_key=f"{p.id}:VENCIMIENTO_VIGENCIA:VENCIDO",
        ))
        return out
    for umbral in UMBRALES_VIGENCIA:
        if restantes <= umbral:
            out.append(AlertaGenerada(
                tipo=TipoAlerta.VENCIMIENTO_VIGENCIA,
                fecha_disparo=hoy,
                mensaje=f'Vigencia de conexion de "{p.nombre_comercial}" vence en {restantes} dias (umbral {umbral}d). Gestionar prorroga (avisar 1 mes antes).',
                dedupe_key=f"{p.id}:VENCIMIENTO_VIGENCIA:{umbral}",
            ))
    return out


def alertas_equipos_frontera(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    if not p.fecha_conexion_estimada or p.equipos_solicitados:
        return []
    restantes = dias_calendario(hoy, p.fecha_conexion_estimada)
    if restantes >= 90:
        return []
    return [AlertaGenerada(
        tipo=TipoAlerta.EQUIPOS_FRONTERA_90D,
        fecha_disparo=hoy,
        mensaje=f'Faltan {restantes} dias para la conexion estimada de "{p.nombre_comercial}" y no se han solicitado los equipos de frontera a Solenium (regla: >= 3 meses antes).',
        dedupe_key=f"{p.id}:EQUIPOS_FRONTERA_90D",
    )]


def alertas_medidor_or(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    if not p.exporta or not p.comercializador_es_or or not p.fecha_visita_protecciones:
        return []
    medidor = next(
        (e for e in p.equipos if e.tipo in ("MEDIDOR_PRINCIPAL", "MEDIDOR_RESPALDO")), None
    )
    if medidor and medidor.fecha_envio_or:
        return []
    habiles = dias_habiles_entre(hoy, p.fecha_visita_protecciones)
    if habiles > 15:
        return []
    return [AlertaGenerada(
        tipo=TipoAlerta.MEDIDOR_OR_15DH,
        fecha_disparo=hoy,
        mensaje=f'Faltan {habiles} dias habiles para la visita de protecciones de "{p.nombre_comercial}" y el medidor + equipo de comunicacion no se ha enviado al OR (regla: 15 dias habiles antes).',
        dedupe_key=f"{p.id}:MEDIDOR_OR_15DH",
    )]


ESTADOS_ESTANCAMIENTO_10DH = {Estado.SOLICITUD_ENVIADA_OR, Estado.SOLICITUD_ENVIADA_XM}


def alertas_etapa_estancada(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    out: list[AlertaGenerada] = []
    for et in p.etapas:
        habiles = dias_habiles_entre(et.fecha_estado, hoy)
        if et.estado_actual in ESTADOS_ESTANCAMIENTO_10DH and habiles > 10:
            out.append(AlertaGenerada(
                tipo=TipoAlerta.ETAPA_ESTANCADA,
                fecha_disparo=hoy,
                mensaje=f'"{p.nombre_comercial}" lleva {habiles} dias habiles en {et.estado_actual} ({et.etapa}) sin avanzar. Reenviar/escalar.',
                dedupe_key=f"{p.id}:ETAPA_ESTANCADA:{et.etapa}",
            ))
        if (
            et.estado_actual == Estado.ESPERANDO_VISITA_PROTECCIONES
            and not p.fecha_visita_protecciones
            and habiles > 10
        ):
            out.append(AlertaGenerada(
                tipo=TipoAlerta.ETAPA_ESTANCADA,
                fecha_disparo=hoy,
                mensaje=f'"{p.nombre_comercial}" lleva {habiles} dias habiles esperando la visita de protecciones sin agenda. Coordinar con Solenium/OR.',
                dedupe_key=f"{p.id}:ETAPA_ESTANCADA:{et.etapa}",
            ))
    return out


UMBRAL_CALIBRACION_DIAS = 30


def alertas_calibracion(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    out: list[AlertaGenerada] = []
    for eq in p.equipos:
        if not eq.fecha_vencimiento_calibracion:
            continue
        restantes = dias_calendario(hoy, eq.fecha_vencimiento_calibracion)
        if restantes > UMBRAL_CALIBRACION_DIAS:
            continue
        disc = f"{eq.tipo}:{eq.serial or 's/n'}"
        estado = f"VENCIDA hace {abs(restantes)} dias" if restantes < 0 else f"vence en {restantes} dias"
        out.append(AlertaGenerada(
            tipo=TipoAlerta.CALIBRACION_POR_VENCER,
            fecha_disparo=hoy,
            mensaje=f'Calibracion del equipo {disc} de "{p.nombre_comercial}" {estado} (medidores <= 12m, TC/TP <= 6m).',
            dedupe_key=f"{p.id}:CALIBRACION_POR_VENCER:{disc}",
        ))
    return out


def generar_alertas(p: ProyectoSnapshot, hoy: date) -> list[AlertaGenerada]:
    """Ejecuta todos los generadores para un registro."""
    return [
        *alertas_vigencia(p, hoy),
        *alertas_equipos_frontera(p, hoy),
        *alertas_medidor_or(p, hoy),
        *alertas_etapa_estancada(p, hoy),
        *alertas_calibracion(p, hoy),
    ]
