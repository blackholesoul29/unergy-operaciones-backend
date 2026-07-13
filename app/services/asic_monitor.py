"""Monitoreo de cobertura ASIC/GESCON de los contratos PPA activos.

Un PPA con la ventana comercial vigente hoy debería tener al menos un registro
GESCON PUBLICADO ante XM cubriendo el día de hoy. Si no lo tiene, se está
entregando energía bajo un contrato que el ASIC no reconoce: la liquidación se
va a bolsa y el contrato no cubre nada. Eso es lo que este módulo detecta.

Por qué no basta con mirar `estado_solicitud == publicado`
──────────────────────────────────────────────────────────
`asic_solicitudes` conserva cada solicitud histórica como fila permanente y las
filas relevadas mantienen su `fecha_fin` CRUDA (ver docstring de
`app/utils/gescon_vigencia`). Un PPA cuyo único registro publicado fue relevado
por una modificación posterior seguiría pareciendo "cubierto" si comparáramos
la fecha_fin cruda. Por eso la cobertura se decide sobre la vigencia EFECTIVA
que resuelve `resolver_vigencias` — el mismo núcleo que usan Cumplimiento,
GET /asic y /alertas/contratos-ppa.

Ligadura registro→PPA: por FK `contrato_ppa_id` y, si falta, casando
`contrato_interno` con `numero_codigo_contrato` (misma regla que
`_resolver_ppa_para` en asic.py). Sin ese fallback, los contratos cargados
antes de que existiera la FK aparecerían como NINGUNA — falsos críticos.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asic import AsicSolicitud, EstadoSolicitudAsicEnum, TipoSolicitudAsicEnum
from app.models.contratos import PPAContrato
from app.schemas.asic_status import AsicStatus, PPAAsicStatusResponse
from app.utils.gescon_vigencia import resolver_vigencias


@dataclass(frozen=True)
class RegistroAsic:
    """Registro GESCON ya resuelto: lo mínimo para decidir cobertura.

    Desacopla la clasificación del ORM y de la resolución de vigencia, que es
    lo que permite testear la regla sin base de datos.
    """

    id: int
    estado: str                      # estado_solicitud
    tipo: str                        # tipo_solicitud
    fecha_inicio: date | None
    fecha_fin_efectiva: date | None  # de resolver_vigencias; None = ventana abierta
    vigente: bool                    # es la versión vigente de su SIC
    fecha_radicacion: date | None    # fecha_solicitud (fallback: created_at)
    codigo_sic_contrato: str | None = None
    actualizado_en: datetime | None = None

    def cubre(self, hoy: date) -> bool:
        """¿Este registro cubre el día `hoy` ante el ASIC?

        Publicado + versión vigente de su SIC + no es terminación/desistimiento
        + la ventana efectiva contiene hoy. `fecha_fin_efectiva` None = ventana
        abierta (sigue cubriendo); `fecha_inicio` None = vigente desde siempre.
        """
        if self.estado != EstadoSolicitudAsicEnum.publicado.value:
            return False
        if self.tipo in (TipoSolicitudAsicEnum.terminacion.value, TipoSolicitudAsicEnum.desistimiento.value):
            return False
        if not self.vigente:
            return False
        if self.fecha_inicio is not None and self.fecha_inicio > hoy:
            return False
        if self.fecha_fin_efectiva is not None and self.fecha_fin_efectiva < hoy:
            return False
        return True


@dataclass(frozen=True)
class CoberturaAsic:
    status: AsicStatus
    asic_solicitud_id: int | None
    codigo_sic_contrato: str | None
    dias_pendiente: int | None
    es_critico: bool


def ppa_activo(contrato: PPAContrato, hoy: date) -> bool:
    """`ppa_contratos` no tiene columna `estado`: activo = no borrado y con la
    ventana comercial conteniendo hoy. Fechas nulas no acotan (contrato abierto)."""
    if contrato.deleted_at is not None:
        return False
    if contrato.fecha_inicio is not None and contrato.fecha_inicio > hoy:
        return False
    if contrato.fecha_fin is not None and contrato.fecha_fin < hoy:
        return False
    return True


def clasificar_cobertura(
    registros: list[RegistroAsic],
    hoy: date,
    umbral_dias: int,
) -> CoberturaAsic:
    """Veredicto de cobertura ASIC de UN contrato PPA activo. Función pura.

    - PUBLICADA → hay registro que cubre hoy. Nunca es crítico.
    - PENDIENTE → hay registros, ninguno cubre hoy. Crítico solo si el más
      reciente lleva MÁS de `umbral_dias` radicado (el día exacto del umbral no
      alerta, igual que `calcular_alerta` del CRM comercial).
    - NINGUNA → ni un registro. Crítico de inmediato: un PPA activo sin nada
      radicado ante XM no tiene un trámite en curso al que darle plazo.
    """
    if not registros:
        return CoberturaAsic(AsicStatus.NINGUNA, None, None, None, es_critico=True)

    cubren = [r for r in registros if r.cubre(hoy)]
    if cubren:
        # El vigente más reciente: es el que sustenta la cobertura de hoy.
        actual = max(cubren, key=lambda r: (r.fecha_inicio or date.min, r.id))
        return CoberturaAsic(
            AsicStatus.PUBLICADA, actual.id, actual.codigo_sic_contrato, None, es_critico=False
        )

    ultimo = max(registros, key=lambda r: (r.fecha_radicacion or date.min, r.id))
    dias = (hoy - ultimo.fecha_radicacion).days if ultimo.fecha_radicacion else None
    if dias is not None and dias < 0:
        dias = 0  # radicación futura: aún no empieza a correr el reloj
    # Sin fecha de radicación no hay reloj que contar: se alerta igual, porque un
    # PPA activo sin cobertura es el riesgo, y la fecha ausente no lo atenúa.
    es_critico = dias is None or dias > umbral_dias
    return CoberturaAsic(
        AsicStatus.PENDIENTE, ultimo.id, ultimo.codigo_sic_contrato, dias, es_critico=es_critico
    )


def _a_registro(s: AsicSolicitud, vigencia) -> RegistroAsic:
    """Fila ORM + su Vigencia → RegistroAsic. Las filas que no participan del
    walk (no publicadas, desistimientos) no tienen Vigencia: conservan su
    fecha_fin cruda y vigente=False, así que nunca cuentan como cobertura."""
    radicacion = s.fecha_solicitud
    if radicacion is None and s.created_at is not None:
        radicacion = s.created_at.date()
    return RegistroAsic(
        id=s.id,
        estado=getattr(s.estado_solicitud, "value", s.estado_solicitud),
        tipo=getattr(s.tipo_solicitud, "value", s.tipo_solicitud),
        fecha_inicio=s.fecha_inicio,
        fecha_fin_efectiva=vigencia.fecha_fin_efectiva if vigencia else s.fecha_fin,
        vigente=bool(vigencia.vigente) if vigencia else False,
        fecha_radicacion=radicacion,
        codigo_sic_contrato=s.codigo_sic_contrato,
        actualizado_en=s.updated_at,
    )


def _registros_por_ppa(db: Session, contratos: list[PPAContrato], hoy: date) -> dict[int, list[RegistroAsic]]:
    """Agrupa TODOS los registros GESCON (cualquier estado) por contrato PPA.

    La vigencia se resuelve sobre el universo completo de publicados, no sobre
    los registros del contrato: el relevo que recorta una fila puede venir de
    otro contrato (mismo criterio que `_aplicar_vigencia` en asic.py). `hasta=hoy`
    evita que un relevo con efecto FUTURO desplace a la versión vigente de hoy.
    """
    universo = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud != TipoSolicitudAsicEnum.desistimiento,
        )
        .order_by(
            AsicSolicitud.fecha_inicio.asc().nullsfirst(),
            AsicSolicitud.fecha_solicitud.asc().nullsfirst(),
            AsicSolicitud.created_at.asc(),
        )
        .all()
    )
    vigencias = resolver_vigencias(universo, hasta=hoy)

    por_codigo = {
        c.numero_codigo_contrato: c.id
        for c in contratos
        if c.numero_codigo_contrato
    }
    ids_vivos = {c.id for c in contratos}

    out: dict[int, list[RegistroAsic]] = defaultdict(list)
    for s in db.query(AsicSolicitud).all():
        ppa_id = s.contrato_ppa_id if s.contrato_ppa_id in ids_vivos else None
        if ppa_id is None and s.contrato_interno:
            ppa_id = por_codigo.get(s.contrato_interno.strip())
        if ppa_id is None:
            continue
        out[ppa_id].append(_a_registro(s, vigencias.get(s.id)))
    return out


def get_ppa_asic_status(
    db: Session,
    status_filter: AsicStatus | None = None,
    is_critical_only: bool = False,
    umbral_dias: int | None = None,
    hoy: date | None = None,
) -> list[PPAAsicStatusResponse]:
    """Estado de cobertura ASIC de cada PPA ACTIVO hoy.

    Los contratos vencidos o aún no iniciados quedan fuera: un PPA que terminó
    en 2024 sin registro GESCON no es un riesgo, es historia.
    """
    hoy = hoy or date.today()
    umbral = settings.ASIC_ALERTA_DIAS if umbral_dias is None else umbral_dias

    contratos = [
        c
        for c in db.query(PPAContrato).filter(PPAContrato.deleted_at.is_(None)).all()
        if ppa_activo(c, hoy)
    ]
    registros_por_ppa = _registros_por_ppa(db, contratos, hoy)

    salida: list[PPAAsicStatusResponse] = []
    for c in contratos:
        registros = registros_por_ppa.get(c.id, [])
        cobertura = clasificar_cobertura(registros, hoy, umbral)

        if status_filter is not None and cobertura.status != status_filter:
            continue
        if is_critical_only and not cobertura.es_critico:
            continue

        actualizaciones = [r.actualizado_en for r in registros if r.actualizado_en]
        salida.append(
            PPAAsicStatusResponse(
                ppa_id=c.id,
                ppa_nombre=c.nombre_interno,
                numero_codigo_contrato=c.numero_codigo_contrato,
                fecha_inicio=c.fecha_inicio,
                fecha_fin=c.fecha_fin,
                asic_status=cobertura.status,
                asic_solicitud_id=cobertura.asic_solicitud_id,
                codigo_sic_contrato=cobertura.codigo_sic_contrato,
                dias_pendiente=cobertura.dias_pendiente,
                fecha_ultima_actualizacion=max(actualizaciones) if actualizaciones else None,
                es_critico=cobertura.es_critico,
            )
        )

    # Los críticos primero; dentro de cada grupo, el más expuesto (más días) arriba.
    salida.sort(key=lambda r: (not r.es_critico, -(r.dias_pendiente or 0), r.ppa_id))
    return salida
