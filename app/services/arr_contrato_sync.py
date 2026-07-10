"""Sincronización bidireccional entre arr_proyectos (fuente del panel Costos→Arriendos)
y contratos_servicio (servicio_aplica='arriendo', mostrado en Servicios→Operación).

Vínculo: arr_proyectos.proyecto_id == contratos_servicio.proyecto_id.
Escrituras directas a BD dentro del mismo request (sin llamadas cruzadas entre
endpoints) → no hay riesgo de bucle de sincronización.

Campos compartidos:
    arr_proyectos.valor_base            <-> contratos_servicio.tarifa_base
    arr_proyectos.fecha_firma_contrato  <-> contratos_servicio.fecha_firma_contrato
    arr_proyectos.activo                <-> contratos_servicio.estado (activo->vigente)
    arr_proyectos.canon_archivo         : solo arr (sin equivalente)
"""
from __future__ import annotations
from sqlalchemy.orm import Session


def _estado_from_activo(activo: bool | None) -> str:
    return "vigente" if activo else "terminado"


def sync_arr_to_contrato(arr, db: Session) -> None:
    """Upsert del contrato de arriendo del proyecto vinculado con los datos del arr_proyecto."""
    from app.models.contratos import ContratoServicio

    if getattr(arr, "proyecto_id", None) is None:
        return

    contrato = (
        db.query(ContratoServicio)
        .filter(
            ContratoServicio.proyecto_id == arr.proyecto_id,
            ContratoServicio.servicio_aplica == "arriendo",
        )
        .first()
    )
    if contrato is None:
        contrato = ContratoServicio(proyecto_id=arr.proyecto_id, servicio_aplica="arriendo")
        db.add(contrato)

    contrato.tarifa_base = arr.valor_base
    contrato.fecha_firma_contrato = arr.fecha_firma_contrato
    contrato.estado = _estado_from_activo(arr.activo)
    db.commit()


def sync_contrato_to_arr(contrato, db: Session) -> None:
    """Escribe de vuelta al arr_proyecto vinculado los campos compartidos del contrato."""
    from app.models.arriendos import ArrProyecto

    if contrato.servicio_aplica != "arriendo" or contrato.proyecto_id is None:
        return

    arr = (
        db.query(ArrProyecto)
        .filter(ArrProyecto.proyecto_id == contrato.proyecto_id)
        .first()
    )
    if arr is None:
        return

    if contrato.tarifa_base is not None:
        arr.valor_base = contrato.tarifa_base
    if contrato.fecha_firma_contrato is not None:
        arr.fecha_firma_contrato = contrato.fecha_firma_contrato
    db.commit()
