"""Agregados por cliente para la vista comercial de /clientes y el panel 360.

"Planta con nosotros" = proyecto donde el cliente cumple cualquiera de:
- es inversionista (proyecto_inversionistas),
- es contratante de un contrato de servicio sobre el proyecto (contratos_servicio),
- es comprador o vendedor de un PPA que cubre el proyecto (ppa_contrato_proyectos).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

UMBRAL_POR_VENCER_DIAS = 90
_ORDEN_SEMAFORO = {"vigente": 0, "por_vencer": 1, "vencido": 2}


def semaforo_contrato(fecha_fin: date | None, hoy: date,
                      umbral_dias: int = UMBRAL_POR_VENCER_DIAS) -> str:
    """Sin fecha fin = contrato indefinido = vigente."""
    if fecha_fin is None:
        return "vigente"
    if fecha_fin < hoy:
        return "vencido"
    if (fecha_fin - hoy).days <= umbral_dias:
        return "por_vencer"
    return "vigente"


def peor_semaforo(semaforos: list[str]) -> str | None:
    if not semaforos:
        return None
    return max(semaforos, key=lambda s: _ORDEN_SEMAFORO.get(s, 0))


def renovacion_combinada(valores: list[bool | None]) -> bool | None:
    """True si algún contrato renueva; False si hay dato y ninguno renueva;
    None si no hay ningún dato (la UI muestra '—')."""
    con_dato = [v for v in valores if v is not None]
    if not con_dato:
        return None
    return any(con_dato)


def proyectos_por_cliente(db: Session, cliente_ids: set[int]) -> dict[int, set[int]]:
    from app.models.contratos import ContratoServicio, PPAContrato, ppa_contrato_proyectos_table
    from app.models.proyectos import ProyectoInversionista

    res: dict[int, set[int]] = defaultdict(set)
    if not cliente_ids:
        return res

    filas_inv = (
        db.query(ProyectoInversionista.cliente_id, ProyectoInversionista.proyecto_id)
        .filter(ProyectoInversionista.cliente_id.in_(cliente_ids))
        .all()
    )
    for cid, pid in filas_inv:
        res[cid].add(pid)

    filas_serv = (
        db.query(ContratoServicio.contratante_id, ContratoServicio.proyecto_id)
        .filter(ContratoServicio.contratante_id.in_(cliente_ids),
                ContratoServicio.proyecto_id.isnot(None))
        .all()
    )
    for cid, pid in filas_serv:
        res[cid].add(pid)

    filas_ppa = (
        db.query(PPAContrato.comprador_id, PPAContrato.vendedor_id,
                 ppa_contrato_proyectos_table.c.proyecto_id)
        .join(ppa_contrato_proyectos_table,
              ppa_contrato_proyectos_table.c.contrato_id == PPAContrato.id)
        .filter(PPAContrato.deleted_at.is_(None),
                or_(PPAContrato.comprador_id.in_(cliente_ids),
                    PPAContrato.vendedor_id.in_(cliente_ids)))
        .all()
    )
    for comprador_id, vendedor_id, pid in filas_ppa:
        if comprador_id in cliente_ids:
            res[comprador_id].add(pid)
        if vendedor_id in cliente_ids:
            res[vendedor_id].add(pid)
    return res


def servicios_por_cliente(db: Session, cliente_ids: set[int]) -> dict[int, set[str]]:
    from app.models.clientes import ClienteServicio
    from app.models.contratos import ContratoServicio, PPAContrato

    res: dict[int, set[str]] = defaultdict(set)
    if not cliente_ids:
        return res

    for cid, tipo in (db.query(ClienteServicio.cliente_id, ClienteServicio.tipo)
                      .filter(ClienteServicio.cliente_id.in_(cliente_ids)).all()):
        res[cid].add(tipo.value if hasattr(tipo, "value") else tipo)

    for cid, tipo in (db.query(ContratoServicio.contratante_id, ContratoServicio.servicio_aplica)
                      .filter(ContratoServicio.contratante_id.in_(cliente_ids)).all()):
        res[cid].add(tipo.value if hasattr(tipo, "value") else tipo)

    filas_ppa = (
        db.query(PPAContrato.comprador_id, PPAContrato.vendedor_id)
        .filter(PPAContrato.deleted_at.is_(None),
                or_(PPAContrato.comprador_id.in_(cliente_ids),
                    PPAContrato.vendedor_id.in_(cliente_ids)))
        .all()
    )
    for comprador_id, vendedor_id in filas_ppa:
        if comprador_id in cliente_ids:
            res[comprador_id].add("ppa")
        if vendedor_id in cliente_ids:
            res[vendedor_id].add("ppa")
    return res


def contacto_comercial_por_cliente(db: Session, cliente_ids: set[int]) -> dict[int, dict]:
    """Primer contacto de tipo 'comercial' por cliente (nombre/teléfono/correo)
    más cuántos contactos comerciales adicionales hay. La tabla overview muestra
    el principal; el detalle muestra todos."""
    from app.models.contactos import Contacto

    res: dict[int, dict] = {}
    if not cliente_ids:
        return res
    filas = (
        db.query(Contacto)
        .filter(Contacto.cliente_id.in_(cliente_ids), Contacto.tipo == "comercial")
        .order_by(Contacto.cliente_id, Contacto.id)
        .all()
    )
    por_cliente: dict[int, list] = defaultdict(list)
    for c in filas:
        por_cliente[c.cliente_id].append(c)
    for cid, contactos in por_cliente.items():
        principal = contactos[0]
        res[cid] = {
            "nombre": principal.nombre,
            "telefono": principal.telefono,
            "correo": principal.email,
            "adicionales": len(contactos) - 1,
        }
    return res


def alerta_contratos_por_cliente(db: Session, cliente_ids: set[int],
                                 hoy: date) -> dict[int, dict]:
    """Peor semáforo entre los contratos no terminados del cliente y la
    fecha de fin futura más cercana."""
    from app.models.contratos import ContratoServicio, PPAContrato

    semaforos: dict[int, list[str]] = defaultdict(list)
    vencimientos: dict[int, list[date]] = defaultdict(list)
    if not cliente_ids:
        return {}

    filas_serv = (
        db.query(ContratoServicio.contratante_id, ContratoServicio.prestador_id,
                 ContratoServicio.fecha_fin, ContratoServicio.estado)
        .filter(or_(ContratoServicio.contratante_id.in_(cliente_ids),
                    ContratoServicio.prestador_id.in_(cliente_ids)))
        .all()
    )
    for contratante_id, prestador_id, fecha_fin, estado in filas_serv:
        estado_val = estado.value if hasattr(estado, "value") else estado
        if estado_val == "terminado":
            continue
        sem = semaforo_contrato(fecha_fin, hoy)
        for cid in (contratante_id, prestador_id):
            if cid in cliente_ids:
                semaforos[cid].append(sem)
                if fecha_fin and fecha_fin >= hoy:
                    vencimientos[cid].append(fecha_fin)

    filas_ppa = (
        db.query(PPAContrato.comprador_id, PPAContrato.vendedor_id, PPAContrato.fecha_fin)
        .filter(PPAContrato.deleted_at.is_(None),
                or_(PPAContrato.comprador_id.in_(cliente_ids),
                    PPAContrato.vendedor_id.in_(cliente_ids)))
        .all()
    )
    for comprador_id, vendedor_id, fecha_fin in filas_ppa:
        sem = semaforo_contrato(fecha_fin, hoy)
        for cid in (comprador_id, vendedor_id):
            if cid in cliente_ids:
                semaforos[cid].append(sem)
                if fecha_fin and fecha_fin >= hoy:
                    vencimientos[cid].append(fecha_fin)

    return {
        cid: {
            "alerta": peor_semaforo(sems) if peor_semaforo(sems) != "vigente" else None,
            "proximo_vencimiento": min(vencimientos[cid]) if vencimientos.get(cid) else None,
        }
        for cid, sems in semaforos.items()
    }
