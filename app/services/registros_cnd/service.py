"""Orquestacion con la base de datos para "Registros CND/ASIC".

Aqui vive la logica que toca la sesion DB: crear un registro con su estructura
(etapas + hitos), construir el resumen "en que va el proyecto X", registrar una
transicion validada por la maquina de estados, y recomputar alertas (upsert por
dedupe_key). La logica pura vive en dominio/avance/state_machine/validaciones_93/alertas.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session, joinedload

from app.models.registros_cnd import (
    RegistroConexion, RegistroEtapa, RegistroHito, RegistroTransicion,
    RegistroAlerta,
)
from app.models.proyectos import Proyecto
from app.services.registros_cnd.dominio import (
    ETAPAS_ACTUALES, ETAPAS_FUTURAS, ETIQUETAS_ETAPA, HITOS, HITOS_POR_KEY,
    Estado, Etapa,
)
from app.services.registros_cnd import state_machine as sm
from app.services.registros_cnd.avance import (
    HitoAvance, avance_por_etapa, calcular_avance_pct, siguiente_hito_pendiente, suma_pesos,
)
from app.services.registros_cnd import alertas as alertas_mod


# ---------------------------------------------------------------------------
# Creacion
# ---------------------------------------------------------------------------
def crear_registro(db: Session, proyecto_id: int, **campos) -> RegistroConexion:
    """Crea un registro sobre un Proyecto e inicializa TODAS sus etapas (actuales +
    futuras) en su estado inicial, y todos los hitos 1a-8c con su peso por defecto.

    Lanza ValueError si el proyecto no existe o ya tiene registro.
    """
    proyecto = db.get(Proyecto, proyecto_id)
    if proyecto is None:
        raise ValueError(f"El proyecto {proyecto_id} no existe")
    existente = db.query(RegistroConexion).filter_by(proyecto_id=proyecto_id).first()
    if existente is not None:
        raise ValueError(f"El proyecto {proyecto_id} ya tiene un registro de conexion (id={existente.id})")

    registro = RegistroConexion(proyecto_id=proyecto_id, **campos)
    db.add(registro)
    db.flush()  # asigna registro.id

    for etapa in [*ETAPAS_ACTUALES, *ETAPAS_FUTURAS]:
        db.add(RegistroEtapa(
            registro_id=registro.id,
            etapa=etapa,
            estado_actual=sm.get_etapa_def(etapa)["inicial"],
        ))
    for h in HITOS:
        db.add(RegistroHito(
            registro_id=registro.id,
            hito=h["key"],
            peso_pct=float(h["peso_default"]),
            completado=False,
        ))
    db.commit()
    db.refresh(registro)
    return registro


def get_or_create_registro(db: Session, proyecto_id: int) -> RegistroConexion:
    """Devuelve el registro del proyecto, creandolo (con etapas + hitos) si no existe.

    Materializa el seguimiento la primera vez que se abre un proyecto. Lanza ValueError
    si el proyecto no existe.
    """
    reg = db.query(RegistroConexion).filter_by(proyecto_id=proyecto_id).first()
    if reg is not None:
        return reg
    return crear_registro(db, proyecto_id)


# ---------------------------------------------------------------------------
# Resumen "en que va el proyecto X"
# ---------------------------------------------------------------------------
def _to_hito_avance(hitos_orm: list[RegistroHito]) -> list[HitoAvance]:
    return [HitoAvance(hito=h.hito, peso_pct=h.peso_pct, completado=h.completado) for h in hitos_orm]


def _enum_val(v) -> str | None:
    if v is None:
        return None
    return getattr(v, "value", v)


def construir_resumen(db: Session, registro: RegistroConexion) -> dict:
    """Construye el resumen completo del registro (avance, estado por etapa,
    siguiente paso con responsable, bloqueos, alertas pendientes)."""
    proyecto: Proyecto = registro.proyecto
    hitos_av = _to_hito_avance(registro.hitos)
    por_etapa_av = {a.etapa: a for a in avance_por_etapa(hitos_av)}
    etapa_rows = {e.etapa: e for e in registro.etapas}

    por_etapa = []
    for etapa in ETAPAS_ACTUALES:
        row = etapa_rows.get(etapa)
        av = por_etapa_av[etapa]
        por_etapa.append({
            "etapa": etapa,
            "etiqueta": ETIQUETAS_ETAPA[etapa],
            "estado_actual": row.estado_actual if row else sm.get_etapa_def(etapa)["inicial"],
            "bloqueada": row.bloqueada if row else False,
            "causa_bloqueo": row.causa_bloqueo if row else None,
            "responsable_actual": row.responsable_actual if row else None,
            "ganado_pct": av.ganado_pct,
            "total_pct": av.total_pct,
            "completos": av.completos,
            "total_hitos": av.total_hitos,
        })

    # Siguiente paso: primer hito pendiente en el orden canonico.
    sig_hito = siguiente_hito_pendiente(hitos_av)
    siguiente_paso = None
    if sig_hito:
        meta = HITOS_POR_KEY[sig_hito]
        row = etapa_rows.get(meta["etapa"])
        estado_actual = row.estado_actual if row else sm.get_etapa_def(meta["etapa"])["inicial"]
        proximos = sm.transiciones_permitidas(meta["etapa"], estado_actual)
        responsable = (row.responsable_actual if row and row.responsable_actual else None) or (
            sm.responsable_de_estado(meta["etapa"], proximos[0]) if proximos else None
        )
        siguiente_paso = {
            "hito": sig_hito,
            "codigo": sig_hito,
            "descripcion": meta["descripcion"],
            "etapa": meta["etapa"],
            "etiqueta_etapa": ETIQUETAS_ETAPA[meta["etapa"]],
            "responsable": responsable,
        }

    bloqueos = [
        {
            "etapa": e["etapa"],
            "etiqueta": e["etiqueta"],
            "motivo": "Vigencia vencida" if e["estado_actual"] == Estado.VENCIDO
            else (e["causa_bloqueo"] or "Bloqueada (sin causa registrada)"),
        }
        for e in por_etapa
        if e["bloqueada"] or e["estado_actual"] == Estado.VENCIDO
    ]

    hitos_out = sorted(
        (
            {
                "hito": h.hito,
                "codigo": HITOS_POR_KEY.get(h.hito, {}).get("key", h.hito),
                "descripcion": HITOS_POR_KEY.get(h.hito, {}).get("descripcion", ""),
                "etapa": HITOS_POR_KEY.get(h.hito, {}).get("etapa", Etapa.ETAPA_1_CREG174_AMBITO),
                "peso_pct": h.peso_pct,
                "completado": h.completado,
                "fecha_completado": h.fecha_completado,
            }
            for h in registro.hitos
        ),
        key=lambda x: _orden_hito(x["codigo"]),
    )

    operador = getattr(proyecto, "operador", None)
    or_nombre = None
    if operador is not None:
        or_nombre = operador.nombre_comercial or operador.nombre_legal

    return {
        "id": registro.id,
        "proyecto_id": registro.proyecto_id,
        "nombre_comercial": proyecto.nombre_comercial,
        "codigo_cnd": getattr(proyecto, "codigo_cnd", None),
        "clasificacion_regulatoria": _enum_val(getattr(proyecto, "clasificacion_regulatoria", None)),
        "tecnologia": _enum_val(getattr(proyecto, "tipo_tecnologia", None)),
        "operador_red": or_nombre,
        "fecha_entrada_operacion": getattr(proyecto, "fecha_entrada_operacion", None),
        "numero_expediente": registro.numero_expediente,
        "id_requerimiento_or": registro.id_requerimiento_or,
        "numero_solicitud_appweb": registro.numero_solicitud_appweb,
        "fecha_conexion_estimada": registro.fecha_conexion_estimada,
        "vigencia_aprobacion_conexion": registro.vigencia_aprobacion_conexion,
        "fecha_visita_protecciones": registro.fecha_visita_protecciones,
        "tipo_visita_protecciones": registro.tipo_visita_protecciones,
        "exporta": registro.exporta,
        "comercializador_es_or": registro.comercializador_es_or,
        "punto_conexion_texto": registro.punto_conexion_texto,
        "notas": registro.notas,
        "avance_pct": calcular_avance_pct(hitos_av),
        "total_pct": suma_pesos(hitos_av),
        "por_etapa": por_etapa,
        "hitos": hitos_out,
        "siguiente_paso": siguiente_paso,
        "bloqueos": bloqueos,
        "alertas_pendientes": [
            {"tipo": a.tipo, "mensaje": a.mensaje, "fecha_disparo": a.fecha_disparo}
            for a in registro.alertas
            if a.estado == "PENDIENTE"
        ],
    }


def _orden_hito(codigo: str):
    """Orden numerico-alfabetico de "1a".."8c"."""
    num = "".join(c for c in codigo if c.isdigit())
    letra = "".join(c for c in codigo if c.isalpha())
    return (int(num) if num else 0, letra)


def resumen_ligero(db: Session, registro: RegistroConexion) -> dict:
    """Resumen reducido para la lista (evita serializar todos los hitos)."""
    r = construir_resumen(db, registro)
    return {
        "id": r["id"],
        "proyecto_id": r["proyecto_id"],
        "nombre_comercial": r["nombre_comercial"],
        "codigo_cnd": r["codigo_cnd"],
        "clasificacion_regulatoria": r["clasificacion_regulatoria"],
        "tecnologia": r["tecnologia"],
        "operador_red": r["operador_red"],
        "avance_pct": r["avance_pct"],
        "siguiente_paso": r["siguiente_paso"],
        "alertas_pendientes": len(r["alertas_pendientes"]),
        "bloqueos": len(r["bloqueos"]),
        "tiene_registro": True,
    }


def _fila_bare(proyecto: Proyecto) -> dict:
    """Fila de lista para un Proyecto que aun NO tiene registro de conexion:
    avance 0, todos los hitos pendientes, siguiente paso = 1a."""
    operador = getattr(proyecto, "operador", None)
    or_nombre = (operador.nombre_comercial or operador.nombre_legal) if operador else None
    h0 = HITOS[0]  # "1a"
    return {
        "id": None,  # aun no hay registro
        "proyecto_id": proyecto.id,
        "nombre_comercial": proyecto.nombre_comercial,
        "codigo_cnd": getattr(proyecto, "codigo_cnd", None),
        "clasificacion_regulatoria": _enum_val(getattr(proyecto, "clasificacion_regulatoria", None)),
        "tecnologia": _enum_val(getattr(proyecto, "tipo_tecnologia", None)),
        "operador_red": or_nombre,
        "avance_pct": 0.0,
        "siguiente_paso": {
            "hito": h0["key"],
            "codigo": h0["key"],
            "descripcion": h0["descripcion"],
            "etapa": h0["etapa"],
            "etiqueta_etapa": ETIQUETAS_ETAPA[h0["etapa"]],
            "responsable": "PROMOTOR",
        },
        "alertas_pendientes": 0,
        "bloqueos": 0,
        "tiene_registro": False,
    }


def listar_todos(db: Session) -> list[dict]:
    """Una fila por CADA proyecto de la plataforma (no solo los que ya tienen registro).
    Los que ya tienen registro muestran su avance real; el resto, 0% / pendiente."""
    registros = {r.proyecto_id: r for r in db.query(RegistroConexion).all()}
    query = db.query(Proyecto).options(joinedload(Proyecto.operador))
    if hasattr(Proyecto, "deleted_at"):
        query = query.filter(Proyecto.deleted_at.is_(None))
    proyectos = query.order_by(Proyecto.nombre_comercial.asc()).all()
    filas = []
    for p in proyectos:
        reg = registros.get(p.id)
        filas.append(resumen_ligero(db, reg) if reg is not None else _fila_bare(p))
    return filas


# ---------------------------------------------------------------------------
# Transiciones
# ---------------------------------------------------------------------------
def registrar_transicion(
    db: Session,
    registro: RegistroConexion,
    etapa: str,
    a_estado: str,
    nota: str | None = None,
    actor: str | None = None,
) -> RegistroEtapa:
    """Valida y persiste una transicion de estado; completa los hitos asociados.

    Lanza state_machine.TransicionInvalidaError si la transicion no es valida.
    """
    row = next((e for e in registro.etapas if e.etapa == etapa), None)
    if row is None:
        raise ValueError(f"El registro no tiene la etapa {etapa}")

    de_estado = row.estado_actual
    if not sm.es_transicion_valida(etapa, de_estado, a_estado):
        raise sm.TransicionInvalidaError(etapa, de_estado, a_estado)

    # Historial
    db.add(RegistroTransicion(
        etapa_id=row.id, de_estado=de_estado, a_estado=a_estado, actor=actor, nota=nota,
    ))

    # Actualizar la etapa
    row.estado_actual = a_estado
    row.fecha_estado = datetime.utcnow()
    row.responsable_actual = sm.responsable_de_estado(etapa, a_estado)
    row.bloqueada = a_estado == Estado.BLOQUEADO
    if a_estado != Estado.BLOQUEADO:
        row.causa_bloqueo = None

    # Completar hitos al entrar en el estado
    hitos_a_completar = set(sm.hitos_completados_al_entrar(etapa, a_estado))
    if hitos_a_completar:
        ahora = datetime.utcnow()
        for h in registro.hitos:
            if h.hito in hitos_a_completar and not h.completado:
                h.completado = True
                h.fecha_completado = ahora

    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
def _snapshot(registro: RegistroConexion) -> alertas_mod.ProyectoSnapshot:
    def _d(v):
        if v is None:
            return None
        return v.date() if isinstance(v, datetime) else v

    equipos_solicitados = any(
        e.fecha_solicitud_solenium is not None for e in registro.equipos
    )
    return alertas_mod.ProyectoSnapshot(
        id=registro.id,
        nombre_comercial=registro.proyecto.nombre_comercial,
        fecha_conexion_estimada=_d(registro.fecha_conexion_estimada),
        vigencia_conexion=_d(registro.vigencia_aprobacion_conexion),
        equipos_solicitados=equipos_solicitados,
        exporta=registro.exporta,
        comercializador_es_or=registro.comercializador_es_or,
        fecha_visita_protecciones=_d(registro.fecha_visita_protecciones),
        etapas=[
            alertas_mod.EtapaSnapshot(etapa=e.etapa, estado_actual=e.estado_actual, fecha_estado=_d(e.fecha_estado))
            for e in registro.etapas
        ],
        equipos=[
            alertas_mod.EquipoSnapshot(
                tipo=eq.tipo, serial=eq.serial,
                fecha_vencimiento_calibracion=_d(eq.fecha_vencimiento_calibracion),
                fecha_envio_or=_d(eq.fecha_envio_or),
            )
            for eq in registro.equipos
        ],
    )


def recomputar_alertas(db: Session, registro: RegistroConexion, hoy: date | None = None) -> list[RegistroAlerta]:
    """Recalcula las alertas del registro y las persiste (upsert por dedupe_key)."""
    hoy = hoy or date.today()
    generadas = alertas_mod.generar_alertas(_snapshot(registro), hoy)
    existentes = {a.dedupe_key: a for a in registro.alertas}
    creadas: list[RegistroAlerta] = []
    for g in generadas:
        if g.dedupe_key in existentes:
            continue  # ya existe (evita duplicados)
        alerta = RegistroAlerta(
            registro_id=registro.id,
            tipo=g.tipo,
            fecha_disparo=datetime.combine(g.fecha_disparo, datetime.min.time()),
            estado="PENDIENTE",
            mensaje=g.mensaje,
            dedupe_key=g.dedupe_key,
        )
        db.add(alerta)
        creadas.append(alerta)
    if creadas:
        db.commit()
    return creadas
