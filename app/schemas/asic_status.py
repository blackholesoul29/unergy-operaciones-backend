"""Estado de cobertura ASIC/GESCON de un contrato PPA.

`AsicStatus` NO es el `estado_solicitud` de una fila de `asic_solicitudes`: es
el veredicto del CONTRATO completo — si a día de hoy hay o no un registro
publicado y vigente ante XM que lo cubra. Un PPA puede tener diez solicitudes
publicadas y aun así estar en PENDIENTE si todas fueron relevadas o vencieron.
"""
import enum
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AsicStatus(str, enum.Enum):
    # Registro publicado, versión vigente de su SIC, con ventana efectiva que cubre hoy.
    PUBLICADA = "PUBLICADA"
    # Hay registros GESCON ligados al PPA, pero ninguno cubre hoy: en proceso,
    # rechazado, ya vencido o relevado por una modificación posterior.
    PENDIENTE = "PENDIENTE"
    # Ni un solo registro GESCON ligado al contrato.
    NINGUNA = "NINGUNA"


class PPAAsicStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ppa_id: int
    ppa_nombre: str | None = None
    numero_codigo_contrato: str | None = None
    # `ppa_contratos` no tiene fecha de inicio de OPERACIÓN: la ventana del
    # contrato comercial (fecha_inicio/fecha_fin) es lo que define si está activo.
    fecha_inicio: date | None = None
    fecha_fin: date | None = None

    asic_status: AsicStatus
    # Registro que sustenta el veredicto: el que cubre hoy (PUBLICADA) o el más
    # reciente de los que no alcanzan a cubrir (PENDIENTE). None en NINGUNA.
    asic_solicitud_id: int | None = None
    codigo_sic_contrato: str | None = None
    # estado_solicitud del registro sustentante. En PENDIENTE distingue el
    # subcaso: "publicado" = hubo cobertura y venció/fue relevada (radicar nueva
    # solicitud); otro estado = trámite que nunca publicó (hacer seguimiento).
    estado_registro: str | None = None
    # Fin efectivo de la ventana del registro sustentante: en PUBLICADA, cuándo
    # vence la cobertura actual; en PENDIENTE-publicado, cuándo venció/fue relevada.
    fin_cobertura: date | None = None
    # Días desde que se radicó ese último registro. Solo en PENDIENTE — es el
    # contador contra el que corre el umbral, tanto si el registro sigue en
    # trámite como si publicó y su cobertura ya venció.
    dias_pendiente: int | None = None
    # updated_at más reciente entre los registros GESCON del contrato.
    fecha_ultima_actualizacion: datetime | None = None

    es_critico: bool = False
