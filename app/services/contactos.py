"""Resolución única de "a quién le llega qué correo" para Fallas, Reporte CGM,
Informes mensuales y Alarmas MGS. Reemplaza la lectura directa de columnas de
`Cliente` y el matching frágil por nombre de `proyecto_contactos`.

Diseño: los correos reales viven SIEMPRE en `Contacto.cliente_id`. Un Proyecto
nunca guarda un correo suelto -- para un `tipo` (área) dado, puede apuntar
(`ProyectoAreaContacto`) a UN Cliente específico, y en ese caso se usa
exclusivamente ese. Sin puntero para ese tipo, el default es la UNIÓN de los
contactos de todos los clientes ligados al proyecto vía `ProyectoInversionista`
vigente (fecha_fin nula o futura), más el titular (`Proyecto.cliente_id`) si
existe. No hay dependencia dura del titular: un proyecto sin cliente_id pero
con varios inversionistas (participación repartida en %, sin uno "principal")
igual resuelve a quién notificar.
"""
from datetime import date
from sqlalchemy.orm import Session
from app.models.contactos import Contacto, ProyectoAreaContacto
from app.models.proyectos import Proyecto, ProyectoInversionista


def get_contactos(db: Session, tipo: str, *, proyecto_id: int | None = None, cliente_id: int | None = None) -> list[str]:
    """Correos de tipo `tipo` para un proyecto o directamente para un cliente.
    Pasar exactamente uno de `proyecto_id`/`cliente_id`.

    Para un proyecto: si tiene un puntero de área para ese tipo, usa solo el
    cliente al que apunta. Si no, usa la unión de contactos de su titular (si
    tiene) y de todos sus inversionistas vigentes -- sin duplicados."""
    if cliente_id is not None:
        rows = (
            db.query(Contacto.email)
            .filter(Contacto.cliente_id == cliente_id, Contacto.tipo == tipo, Contacto.recibe_notificaciones.is_(True))
            .all()
        )
        return [r[0] for r in rows]

    if proyecto_id is None:
        return []

    override = (
        db.query(ProyectoAreaContacto.cliente_id)
        .filter(ProyectoAreaContacto.proyecto_id == proyecto_id, ProyectoAreaContacto.tipo == tipo)
        .first()
    )
    if override:
        return get_contactos(db, tipo, cliente_id=override[0])

    cliente_ids: list[int] = []
    proyecto = db.query(Proyecto.cliente_id).filter(Proyecto.id == proyecto_id).first()
    if proyecto and proyecto[0]:
        cliente_ids.append(proyecto[0])

    hoy = date.today()
    inversionistas = (
        db.query(ProyectoInversionista.cliente_id)
        .filter(
            ProyectoInversionista.proyecto_id == proyecto_id,
            (ProyectoInversionista.fecha_fin.is_(None)) | (ProyectoInversionista.fecha_fin >= hoy),
        )
        .all()
    )
    for (cid,) in inversionistas:
        if cid:
            cliente_ids.append(cid)

    correos: list[str] = []
    vistos_cliente: set[int] = set()
    for cid in cliente_ids:
        if cid in vistos_cliente:
            continue
        vistos_cliente.add(cid)
        correos.extend(get_contactos(db, tipo, cliente_id=cid))

    vistos_email: set[str] = set()
    unicos: list[str] = []
    for e in correos:
        if e and e not in vistos_email:
            vistos_email.add(e)
            unicos.append(e)
    return unicos