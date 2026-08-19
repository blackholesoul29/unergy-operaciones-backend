"""CRM comercial: pipeline Oportunidad→Oferta→Contrato→Firmado→Operando→Declinado.

Capa PREVIA a operación — reutiliza Cliente/Proyecto/Contactos/Documentos
existentes. Solo roles admin y comercial (lectura y escritura).

Desde 2026-08-02 la etapa del pipeline es de la OFERTA. El cliente no tiene
estado propio: el que se muestra en su fila es el de su oferta más avanzada.
"""
import json
import re
import unicodedata
from datetime import datetime, date
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario
from app.models.clientes import Cliente, ClienteDocumentoComercial
from app.models.contactos import Contacto
from app.api.v1.clientes import buscar_cliente_duplicado
from app.utils.nombre_matching import mejor_candidato
from app.models.proyectos import Proyecto, ProyectoInversionista
from app.models.operadores_red import OperadorRed
from app.models.comercial import (
    Oportunidad, OportunidadEstadoHistorial, OportunidadGestion, OportunidadOferta,
    oportunidad_oferta_proyectos_table,
)
from app.models.contratos import PPAContrato, PPATarifa
from app.schemas.comercial import (
    OportunidadCreate, OportunidadUpdate, EstadoChangeIn, GestionCreate, ProyectoDesdeCRMIn,
    OfertaCreate, OfertaUpdate, FirmarOfertaIn, RegistroComercialIn,
)
from app.services.comercial import (
    ETAPAS_CON_PPA, ETAPAS_CONSULTABLES, ETAPAS_ENTREGABLES, TIPOS_ENERGIA,
    UMBRAL_VINCULO,
    ahora_colombia, calcular_alerta, col_now,
    contexto_ficha, estado_a_resultado, ficha_operativa, ppas_del_pipeline,
    resumen_etapas, vincular_proyectos,
)

router = APIRouter(prefix="/comercial", tags=["comercial"])


def _check_comercial(current: Usuario):
    if current.rol.value not in ("admin", "comercial"):
        raise HTTPException(403, "Requiere rol comercial o admin")


def _get_oportunidad_or_404(id: int, db: Session) -> Oportunidad:
    op = (
        db.query(Oportunidad)
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    return op


def _validar_operador_red(db: Session, operador_red_id: int | None) -> None:
    """El FK al catálogo se valida aquí y no en la BD: sin esto, un id inventado
    revienta como IntegrityError 500 en vez de un 422 con mensaje."""
    if operador_red_id is None:
        return
    if not db.query(OperadorRed.id).filter(OperadorRed.id == operador_red_id).first():
        raise HTTPException(422, "operador_red_id no existe en el catálogo de operadores")


def _proyecto_out(p: Proyecto) -> dict:
    return {
        "id": p.id,
        "nombre_comercial": p.nombre_comercial,
        "potencia_instalada_kwp": float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
        "departamento": p.departamento,
        "municipio": p.municipio,
        "operador_red": p.operador_red,
        "operador_red_id": p.operador_red_id,
        "estado": p.estado if isinstance(p.estado, str) else p.estado.value,
        "fecha_estimada_energizacion": p.fecha_estimada_energizacion,
        "fecha_inicio_comercializacion": p.fecha_inicio_comercializacion,
        "mwh_mes_estimado": float(p.mwh_mes_estimado) if p.mwh_mes_estimado is not None else None,
    }


# Código de seguimiento: prefijo estandarizado OF→OP (oferta y oportunidad).
# Segmento de tipo para ofertas NUEVAS (las existentes conservan su segmento real,
# p. ej. 'REPCGM'): compra de energía = COM, servicios/representación = REP,
# comunidad energética = CEN.
_SEG_TIPO = {
    "servicios_operacionales": "REP",
    "compra_energia": "COM",
    "comunidad_energetica": "CEN",
}
_RE_CONSECUTIVO = re.compile(r"No\.\s*(\d+)")


def _norm_codigo(s: str | None) -> str | None:
    """Estandariza el prefijo del código de seguimiento OF→OP. Idempotente."""
    if s and s[:2].upper() == "OF":
        return "OP" + s[2:]
    return s


def _next_consecutivo(db: Session) -> int:
    """Siguiente consecutivo global (máx NNNN visto en los códigos + 1)."""
    mx = 0
    for (c,) in db.query(OportunidadOferta.numero_oferta).filter(
            OportunidadOferta.numero_oferta.isnot(None)).all():
        m = _RE_CONSECUTIVO.search(c or "")
        if m:
            mx = max(mx, int(m.group(1)))
    return mx + 1


def _gen_codigo(db: Session, tipo: str, fecha) -> str:
    """Genera un código de seguimiento OP.{SEG} No.{NNNN}-{MM}-{YYYY} para una
    oferta nueva sin número. MM/YYYY salen de `fecha` (o del ahora Colombia)."""
    ref = fecha or col_now()
    seg = _SEG_TIPO.get(tipo, "REP")
    return f"OP.{seg} No.{_next_consecutivo(db):04d}-{ref.month}-{ref.year}"


def _valor(v):
    """Enum de SQLAlchemy → str; deja pasar lo que ya es str o None."""
    return v if isinstance(v, (str, type(None))) else v.value


def _plantas_de_ofertas(db: Session, ofertas) -> dict[int, list]:
    """{oferta_id: [plantas]} en dos consultas, no en dos por oferta.

    La versión por lotes de _plantas_de_la_oferta(): la lista de /comercial/ofertas
    trae decenas de filas y resolver la M2M de a una la volvía un N+1.
    """
    ids = [o.id for o in ofertas]
    if not ids:
        return {}
    pares = db.execute(
        oportunidad_oferta_proyectos_table.select().where(
            oportunidad_oferta_proyectos_table.c.oferta_id.in_(ids))).all()
    # Fallback al `proyecto_id` único para las ofertas que no tienen filas en la
    # M2M — mismo criterio que usa /firmar, para que la UI muestre exactamente
    # las plantas que se van a firmar.
    por_oferta: dict[int, list[int]] = {}
    for oferta_id, proyecto_id in pares:
        por_oferta.setdefault(oferta_id, []).append(proyecto_id)
    for o in ofertas:
        if o.id not in por_oferta and o.proyecto_id:
            por_oferta[o.id] = [o.proyecto_id]
    todos = {pid for lista in por_oferta.values() for pid in lista}
    if not todos:
        return {}
    proyectos = {
        p.id: p for p in db.query(Proyecto).filter(
            Proyecto.id.in_(todos), Proyecto.deleted_at.is_(None)).all()
    }
    return {
        oid: [_proyecto_out(proyectos[pid]) for pid in lista if pid in proyectos]
        for oid, lista in por_oferta.items()
    }


def _set_plantas(db: Session, oferta: OportunidadOferta, proyecto_ids: list[int]) -> None:
    """Reescribe las plantas de la oferta (M2M). Lista vacía = desvincular todas.

    Mantiene `proyecto_id` en la primera de la lista: el vinculador, la ficha
    operativa y proyectos_operando siguen leyendo esa columna, así que dejarla
    desincronizada haría que la oferta se viera con una planta en el drawer y con
    otra en la API de integración.
    """
    ids: list[int] = []
    for pid in proyecto_ids:
        if pid not in ids:
            ids.append(pid)
    if ids:
        existen = {
            i for (i,) in db.query(Proyecto.id).filter(
                Proyecto.id.in_(ids), Proyecto.deleted_at.is_(None)).all()
        }
        faltan = [i for i in ids if i not in existen]
        if faltan:
            raise HTTPException(422, f"Proyectos inexistentes: {faltan}")
    db.execute(oportunidad_oferta_proyectos_table.delete().where(
        oportunidad_oferta_proyectos_table.c.oferta_id == oferta.id))
    for pid in ids:
        db.execute(oportunidad_oferta_proyectos_table.insert().values(
            oferta_id=oferta.id, proyecto_id=pid))
    oferta.proyecto_id = ids[0] if ids else None


def _oferta_out(o: OportunidadOferta, ficha: dict | None = None,
                plantas: list | None = None) -> dict:
    return {
        "id": o.id, "oportunidad_id": o.oportunidad_id,
        "tipo": _valor(o.tipo),
        "planta_nombre": o.planta_nombre, "proyecto_id": o.proyecto_id,
        # Todas las plantas de la oferta: es lo que /firmar pasa al contrato.
        "plantas": plantas if plantas is not None else [],
        "numero_oferta": o.numero_oferta,
        "codigo_seguimiento": _norm_codigo(o.numero_oferta),
        "precio_detalle": o.precio_detalle,
        # Etapa propia de la oferta. `resultado` se deriva de ella y viaja solo
        # para que no se rompa lo que ya lo leía.
        "estado": _valor(o.estado),
        "estado_desde": o.estado_desde,
        "resultado": _valor(o.resultado),
        "etapa_texto": o.etapa_texto, "fecha_oferta": o.fecha_oferta,
        "fecha_tentativa_inicio": o.fecha_tentativa_inicio,
        # Fin tentativo del suministro: con el inicio, es el periodo que declara
        # un PPA todavía en borrador.
        "fecha_fin_tentativa": o.fecha_fin_tentativa,
        "contrato_firmado": o.contrato_firmado, "detalle": o.detalle, "notas": o.notas,
        "seguimientos": o.seguimientos or 0,
        "fecha_ultima_respuesta": o.fecha_ultima_respuesta,
        "documento_url": o.documento_url,
        # En qué contrato desembocó. Las condiciones viven allá, no aquí.
        "ppa_contrato_id": o.ppa_contrato_id,
        "contrato_servicio_id": o.contrato_servicio_id,
        # Lo DECLARADO en la oferta, en crudo: el editor necesita distinguirlo de
        # lo resuelto en `ficha` (que puede venir del Proyecto).
        "municipio": o.municipio,
        "departamento": o.departamento,
        "operador_red_id": o.operador_red_id,
        "energia_promedio_kwh_mes": (float(o.energia_promedio_kwh_mes)
                                     if o.energia_promedio_kwh_mes is not None else None),
        # Los 6 parámetros resueltos por cascada + de dónde salió cada uno.
        "ficha": ficha,
        "created_at": o.created_at, "updated_at": o.updated_at,
    }


def _oferta_full(db: Session, o: OportunidadOferta) -> dict:
    """Respuesta completa de UNA oferta (ficha + plantas). La usan los endpoints
    que devuelven la fila recién escrita, para que el front no tenga que recargar
    la lista entera después de cada edición."""
    return _oferta_out(o, _fichas(db, [o])[o.id], _plantas_de_ofertas(db, [o]).get(o.id, []))


def _fichas(db: Session, ofertas) -> dict[int, dict]:
    """{oferta_id: ficha} con la precarga por lotes hecha una sola vez."""
    ctx = contexto_ficha(db, ofertas)
    return {o.id: ficha_operativa(o, **ctx[o.id]) for o in ofertas}


def _resumen_ofertas(ofertas) -> dict:
    """Conteo de ofertas por tipo, p.ej. {'servicios_operacionales': 3, 'compra_energia': 1}."""
    out: dict = {}
    for o in ofertas:
        t = o.tipo if isinstance(o.tipo, str) else o.tipo.value
        out[t] = out.get(t, 0) + 1
    return out


def _op_base_out(op: Oportunidad, cliente: Cliente, ultima_gestion, ahora: datetime,
                 ofertas_estado: list[tuple] | None = None) -> dict:
    """`ofertas_estado` es [(estado, estado_desde), …] de las ofertas del cliente.

    Un cliente NO tiene etapa: el negocio es la oferta. Por eso aquí va
    `etapas` —el conteo por etapa de sus ofertas— y no un estado único. La
    alerta sí se agrega: es la de la oferta más rezagada de las abiertas, para
    que una sola oferta olvidada marque al cliente en la lista.
    """
    etapas = resumen_etapas(e for e, _ in (ofertas_estado or []))
    dias, alerta = 0, False
    for e, desde in (ofertas_estado or []):
        d, a = calcular_alerta(e, desde or op.estado_desde, ultima_gestion,
                               settings.COMERCIAL_ALERTA_DIAS, ahora)
        if a and (not alerta or d > dias):
            dias, alerta = d, True
        elif not alerta and d > dias:
            dias = d
    return {
        "id": op.id,
        "etapas": etapas,
        "nombre": op.nombre or cliente.razon_social_nombre,
        "cliente_id": op.cliente_id,
        "cliente_razon_social": cliente.razon_social_nombre,
        "cliente_nit": cliente.nit_cedula,
        "tipo_servicio": op.tipo_servicio if isinstance(op.tipo_servicio, (str, type(None))) else op.tipo_servicio.value,
        "numero_oferta": op.numero_oferta,
        "es_migrada": op.es_migrada,
        "dias_sin_respuesta": dias,
        "alerta": alerta,
        "ultima_gestion_fecha": ultima_gestion,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
    }


@router.get("/config")
def get_config(_=Depends(get_current_user)):
    return {"alerta_dias": settings.COMERCIAL_ALERTA_DIAS}


@router.get("/oportunidades")
def list_oportunidades(
    estado: str | None = Query(None),
    tipo_servicio: str | None = Query(None),
    cliente_id: int | None = Query(None),
    q: str | None = Query(None),
    solo_alerta: bool = Query(False),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    ult_sq = (
        db.query(OportunidadGestion.oportunidad_id.label("oid"),
                 func.max(OportunidadGestion.fecha).label("ultima"))
        .group_by(OportunidadGestion.oportunidad_id).subquery()
    )
    proy_sq = (
        db.query(Proyecto.oportunidad_id.label("oid"),
                 func.count(Proyecto.id).label("n"),
                 func.coalesce(func.sum(Proyecto.potencia_instalada_kwp), 0).label("kwp"))
        .filter(Proyecto.deleted_at.is_(None), Proyecto.oportunidad_id.isnot(None))
        .group_by(Proyecto.oportunidad_id).subquery()
    )
    qy = (
        db.query(Oportunidad, Cliente, ult_sq.c.ultima, proy_sq.c.n, proy_sq.c.kwp)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id)
        .outerjoin(ult_sq, ult_sq.c.oid == Oportunidad.id)
        .outerjoin(proy_sq, proy_sq.c.oid == Oportunidad.id)
        .filter(Oportunidad.deleted_at.is_(None), Cliente.deleted_at.is_(None))
    )
    if estado:
        # El estado ya no es del cliente: se filtra por tener ≥1 oferta en esa etapa.
        con_estado = db.query(OportunidadOferta.oportunidad_id).filter(
            OportunidadOferta.estado == estado).subquery()
        qy = qy.filter(Oportunidad.id.in_(db.query(con_estado.c.oportunidad_id)))
    if tipo_servicio:
        # Nuevo: filtra oportunidades que tengan ≥1 sub-oferta de ese tipo.
        con_oferta = db.query(OportunidadOferta.oportunidad_id).filter(
            OportunidadOferta.tipo == tipo_servicio).subquery()
        qy = qy.filter(Oportunidad.id.in_(db.query(con_oferta.c.oportunidad_id)))
    if cliente_id:
        qy = qy.filter(Oportunidad.cliente_id == cliente_id)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(
            Oportunidad.nombre.ilike(like) | Cliente.razon_social_nombre.ilike(like)
        )
    ahora = col_now()
    filas = qy.order_by(Oportunidad.updated_at.desc()).all()
    # Conteo de ofertas por (oportunidad, tipo) en una sola consulta.
    op_ids = [op.id for op, *_ in filas]
    resumen_por_op: dict = {}
    if op_ids:
        cont = (
            db.query(OportunidadOferta.oportunidad_id, OportunidadOferta.tipo,
                     func.count(OportunidadOferta.id))
            .filter(OportunidadOferta.oportunidad_id.in_(op_ids))
            .group_by(OportunidadOferta.oportunidad_id, OportunidadOferta.tipo).all()
        )
        for oid, tipo, n in cont:
            t = tipo if isinstance(tipo, str) else tipo.value
            resumen_por_op.setdefault(oid, {})[t] = int(n)
    # Oferta "principal" por oportunidad (la más reciente por fecha/id): de ahí sale
    # el código de seguimiento que se muestra en la fila. La oportunidad "hereda" la
    # identidad de su oferta líder; todas comparten la familia OP.*.
    lead_por_op: dict = {}
    num_ofertas_por_op: dict = {}
    estados_por_op: dict = {}
    if op_ids:
        ofs = (
            db.query(OportunidadOferta.oportunidad_id, OportunidadOferta.numero_oferta,
                     OportunidadOferta.planta_nombre, OportunidadOferta.tipo,
                     OportunidadOferta.proyecto_id, OportunidadOferta.fecha_oferta,
                     OportunidadOferta.id, OportunidadOferta.estado,
                     OportunidadOferta.estado_desde)
            .filter(OportunidadOferta.oportunidad_id.in_(op_ids)).all()
        )
        for oid, num, planta, tipo, pid, fecha, ofid, estado, estado_desde in ofs:
            num_ofertas_por_op[oid] = num_ofertas_por_op.get(oid, 0) + 1
            estados_por_op.setdefault(oid, []).append((_valor(estado), estado_desde))
            # clave de "más reciente": fecha_oferta (date.min si falta) y luego id
            clave = (fecha or date.min, ofid)
            prev = lead_por_op.get(oid)
            if prev is None or clave > prev[0]:
                lead_por_op[oid] = (clave, {
                    "codigo_seguimiento": _norm_codigo(num),
                    "planta_nombre": planta,
                    "tipo": tipo if isinstance(tipo, str) else tipo.value,
                    "proyecto_id": pid,
                })
    out = []
    for op, cli, ultima, n_proy, kwp in filas:
        row = _op_base_out(op, cli, ultima, ahora, estados_por_op.get(op.id))
        row["num_proyectos"] = int(n_proy or 0)
        row["capacidad_total_kwp"] = float(kwp or 0)
        row["resumen_ofertas"] = resumen_por_op.get(op.id, {})
        row["num_ofertas"] = num_ofertas_por_op.get(op.id, 0)
        lead = lead_por_op.get(op.id)
        row["oferta_principal"] = lead[1] if lead else None
        # Código de seguimiento de la fila: el de la oferta líder o, si no hay
        # ofertas, el consecutivo propio de la oportunidad (también normalizado).
        row["codigo_seguimiento"] = (lead[1]["codigo_seguimiento"] if lead
                                     else _norm_codigo(op.numero_oferta))
        if solo_alerta and not row["alerta"]:
            continue
        out.append(row)
    return out


class _UltimaGestion:
    """Última gestión relevante PARA UNA OFERTA: la más reciente entre las suyas
    (`oferta_id` = ella) y las del cliente (`oferta_id` NULL, que cuentan para
    todas sus ofertas).

    Se agrega en Python en vez de en SQL porque el "o es de esta oferta o no es de
    ninguna" no cabe en un GROUP BY simple, y la bitácora es chica. Antes se
    agrupaba solo por oportunidad_id: registrar la llamada por Margaritas 1
    apagaba la alerta de Margaritas 2, que seguía muda.
    """

    def __init__(self, del_cliente: dict, de_la_oferta: dict):
        self._cliente = del_cliente
        self._oferta = de_la_oferta

    def para(self, oportunidad_id: int, oferta_id: int):
        candidatas = [f for f in (self._cliente.get(oportunidad_id),
                                  self._oferta.get(oferta_id)) if f is not None]
        return max(candidatas) if candidatas else None


def _ultima_gestion(db: Session) -> _UltimaGestion:
    filas = (
        db.query(OportunidadGestion.oportunidad_id, OportunidadGestion.oferta_id,
                 func.max(OportunidadGestion.fecha))
        .group_by(OportunidadGestion.oportunidad_id, OportunidadGestion.oferta_id)
        .all()
    )
    del_cliente: dict = {}
    de_la_oferta: dict = {}
    for oportunidad_id, oferta_id, fecha in filas:
        if fecha is None:
            continue
        if oferta_id is None:
            previa = del_cliente.get(oportunidad_id)
            if previa is None or fecha > previa:
                del_cliente[oportunidad_id] = fecha
        else:
            de_la_oferta[oferta_id] = fecha
    return _UltimaGestion(del_cliente, de_la_oferta)


@router.get("/ofertas")
def list_ofertas_todas(
    tipo: str | None = Query(None),
    estado: str | None = Query(None),
    resultado: str | None = Query(None),
    q: str | None = Query(None),
    solo_alerta: bool = Query(False),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Lista PLANA de todas las ofertas (la oferta es la unidad). Cada fila trae
    su código de seguimiento, tipo, planta/proyecto, resultado y —heredados de su
    oportunidad— el estado del pipeline, el cliente y la alerta. Ordenada por la
    más reciente. Esta es la fuente de la vista principal de /comercial."""
    _check_comercial(current)
    qy = (
        db.query(OportunidadOferta, Oportunidad, Cliente)
        .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id)
        .filter(Oportunidad.deleted_at.is_(None), Cliente.deleted_at.is_(None))
    )
    if tipo:
        qy = qy.filter(OportunidadOferta.tipo == tipo)
    if estado:
        qy = qy.filter(OportunidadOferta.estado == estado)
    if resultado:
        qy = qy.filter(OportunidadOferta.resultado == resultado)
    if q:
        like = f"%{q.strip()}%"
        qy = qy.filter(
            OportunidadOferta.numero_oferta.ilike(like)
            | OportunidadOferta.planta_nombre.ilike(like)
            | Cliente.razon_social_nombre.ilike(like)
            | Oportunidad.nombre.ilike(like)
        )
    ahora = col_now()
    filas = qy.order_by(OportunidadOferta.updated_at.desc(), OportunidadOferta.id.desc()).all()
    ofertas = [of for of, _, _ in filas]
    fichas = _fichas(db, ofertas)
    plantas = _plantas_de_ofertas(db, ofertas)
    gestiones = _ultima_gestion(db)
    out = []
    for of, op, cli in filas:
        # La alerta es de la oferta: cuenta desde que ENTRÓ a su etapa actual, no
        # desde que el cliente cambió de estado. Una oferta firmada ya no alerta
        # aunque su hermana lleve meses sin respuesta.
        dias, alerta = calcular_alerta(_valor(of.estado), of.estado_desde or op.estado_desde,
                                       gestiones.para(op.id, of.id),
                                       settings.COMERCIAL_ALERTA_DIAS, ahora)
        row = _oferta_out(of, fichas[of.id], plantas.get(of.id, []))
        row.update({
            "cliente_id": op.cliente_id,
            "cliente_razon_social": cli.razon_social_nombre,
            "cliente_nit": cli.nit_cedula,
            "oportunidad_nombre": op.nombre or cli.razon_social_nombre,
            "dias_sin_respuesta": dias,
            "alerta": alerta,
        })
        if solo_alerta and not alerta:
            continue
        out.append(row)
    return out


@router.get("/proyectos-operando")
def list_ppas_del_pipeline(
    estado_pipeline: list[str] | None = Query(
        None,
        description="Etapas comerciales a devolver. Por defecto las cuatro que "
                    "producen un PPA. Repetible: ?estado_pipeline=operando"),
    todas_las_etapas: bool = Query(
        False,
        description="Ya es el comportamiento por defecto. Se conserva para no "
                    "romper las llamadas que lo vienen mandando"),
    q: str | None = Query(None, description="Filtra por planta, cliente, código de seguimiento o contrato"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Los **contratos de energía** del pipeline: un árbol PPA → PROYECTOS → detalles.

    Un nodo por PPA, con las plantas de ese contrato colgando y, en cada planta,
    su ficha completa: ubicación (con coordenadas y dirección), operador de red,
    potencia, estado, energía promedio mensual, y además `identificacion` (con
    qué id se cruza la planta en cada sistema), `clasificacion` regulatoria,
    ficha `tecnica` (paneles, inversores cargados, almacenamiento, marcas),
    `fronteras[]` comerciales, `servicios` activos, `construccion` y la curva
    `simulacion` P50/P90/P99. `fuentes` dice de dónde salió cada dato de los que
    se resuelven por cascada Proyecto→oferta. Es la superficie para integrar la
    plataforma con otra. Ver `docs/API_PPA_PIPELINE.md`.

    **Un PPA no firmado no existe como contrato.** La oferta del CRM *es* el PPA
    hasta que se firma, y `ppa.id` lo dice sin ambigüedad:

    - `ppa.id === null` → **borrador**. No hay fila en `ppa_contratos`, así que no
      aparece en `/servicios`. Sus condiciones son las tentativas de la oferta y
      `condiciones.origen` vale `"oferta"`.
    - `ppa.id` con valor → el contrato existe. Aparece en `/servicios`, y las
      condiciones salen del contrato (`condiciones.origen == "contrato"`).

    `aparece_en_servicios` viaja como booleano y es el mismo hecho, para que quien
    integre no tenga que deducirlo.

    **`estado_ppa`** resume eso en un slug:

    | Valor | Qué es |
    |---|---|
    | `borrador` | Etapa `oferta` o `contrato`: el PPA está en preparación |
    | `firmado` | El contrato existe en `ppa_contratos` |
    | `sin_contrato` | **Inconsistencia.** La oferta está `firmado`/`operando` pero no hay PPA cargado: el negocio cerró y el contrato falta |

    `sin_contrato` no se rellena inventando un contrato de campos nulos — eso
    metería compromisos fantasma en Cumplimiento. Se muestra para que se cargue.

    **Solo contratos de energía.** `compra_energia` y `comunidad_energetica`; las
    ofertas de servicios (representación, CGM) desembocan en `contratos_servicio`
    y no son PPAs. Comunidad energética no es un tipo aparte: es un PPA con
    `es_comunidad_energetica: true`.

    Las **salidas** del pipeline (`declinado`, `terminado`) no producen PPA: un
    negocio caído no es un contrato en preparación.

    A diferencia del resto de `/comercial`, **no exige rol comercial**: es de solo
    lectura y no expone precios, márgenes ni bitácora comercial.
    """
    if estado_pipeline:
        etapas = tuple(estado_pipeline)
    else:
        etapas = ETAPAS_CON_PPA
    invalidas = [e for e in etapas if e not in ETAPAS_CON_PPA]
    if invalidas:
        # 422 explícito y no una lista vacía: pedir una etapa que no produce PPAs
        # y recibir 200 con cero filas se lee como "no hay ninguno", que es otra
        # cosa. Vale también para `declinado`/`terminado`, que existen en el CRM
        # pero nunca tienen contrato.
        raise HTTPException(
            422,
            f"Etapa no válida: {', '.join(invalidas)}. "
            f"Las etapas que producen un PPA son: {', '.join(ETAPAS_CON_PPA)}.",
        )
    nodos = ppas_del_pipeline(db, q=q, estados=etapas)
    por_estado: dict[str, int] = {}
    for n in nodos:
        clave = n["ppa"]["estado_ppa"]
        por_estado[clave] = por_estado.get(clave, 0) + 1
    return {
        # ahora_colombia() y no col_now(): esta fecha viaja hacia afuera y tiene
        # que traer su offset real (-05:00). Ver el docstring de col_now().
        "generado_en": ahora_colombia(),
        "estados_pipeline": list(etapas),
        "total": len(nodos),
        # Cuántos PPAs hay de cada estado, para no tener que contarlos del lado de
        # quien integra. Solo los estados presentes: un cero explícito de un
        # estado que no se pidió es ruido.
        "por_estado_ppa": por_estado,
        "ppas": nodos,
    }


@router.post("/ofertas/vincular-proyectos")
def vincular_ofertas_a_proyectos(
    dry_run: bool = Query(True, description="Solo previsualizar, sin escribir"),
    estado: list[str] | None = Query(
        None, description="Etapas a mirar. Por defecto firmado y operando. Repetible"),
    todas_las_etapas: bool = Query(False, description="Mirar todo el pipeline, no solo firmado/operando"),
    umbral: float = Query(UMBRAL_VINCULO, ge=0.5, le=1.0,
                          description="Qué tan parecido tiene que ser el nombre para proponer el vínculo"),
    oferta_id: list[int] | None = Query(None, description="Aplicar solo a estas ofertas (para aceptar unas y descartar otras)"),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Vincula por nombre las ofertas del CRM con las plantas ya cargadas.

    El pipeline comercial se cargó desde hojas donde la planta es texto libre
    ("Catedral" contra "La Catedral", "Taurus IX" contra "GD Taurus IX"), así que
    muchas ofertas no apuntan al Proyecto aunque la planta exista. Sin ese
    vínculo, `GET /comercial/proyectos-operando` devuelve el nombre y poco más:
    la ubicación, el operador, la generación y el contrato viven en el Proyecto.

    Por defecto mira las etapas **firmado y operando**, que son las que alimentan
    esa API; con `todas_las_etapas=true` recorre todo el pipeline.

    **Por defecto no escribe** (`dry_run=true`): devuelve `propuestos` (lo que
    haría), `sin_candidato` (con el mejor puntaje que encontró, para saber si
    faltó poco o no hay nada parecido) y `sin_nombre`. Revisá esa lista antes de
    correrlo con `dry_run=false`.

    Idempotente: solo toca ofertas sin proyecto. Para deshacer un vínculo, poner
    el proyecto en NULL desde la ficha de la oferta.

    Solo admin: escribe en el CRM.
    """
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin puede vincular ofertas a proyectos")
    etapas = None if todas_las_etapas else (tuple(estado) if estado else ETAPAS_ENTREGABLES)
    return vincular_proyectos(db, estados=etapas, umbral=umbral,
                              dry_run=dry_run, solo_ofertas=oferta_id)


def _resolver_cliente(db: Session, cliente_id: int | None, cliente_nuevo,
                      forzar_duplicado: bool) -> Cliente:
    """El cliente existente, o uno nuevo con sus contactos. Sin commit.

    El 409 de duplicado trae `candidato_id` a propósito: la UI ofrece "usar ese
    cliente" en vez de dejar al comercial trabado con un error rojo.
    """
    if cliente_id:
        cliente = (
            db.query(Cliente)
            .filter(Cliente.id == cliente_id, Cliente.deleted_at.is_(None))
            .first()
        )
        if not cliente:
            raise HTTPException(422, "Cliente no encontrado")
        return cliente

    cn = cliente_nuevo
    if not forzar_duplicado:
        duplicado = buscar_cliente_duplicado(db, cn.razon_social_nombre)
        if duplicado:
            raise HTTPException(
                409,
                {
                    "mensaje": (
                        f"Ya existe un cliente con un nombre muy parecido: "
                        f"'{duplicado.razon_social_nombre}' (ID {duplicado.id})."
                    ),
                    "duplicado_nombre": True,
                    "candidato_id": duplicado.id,
                    "candidato_nombre": duplicado.razon_social_nombre,
                },
            )
    cliente = Cliente(
        razon_social_nombre=cn.razon_social_nombre,
        nit_cedula=cn.nit_cedula or None,
        origen_tipo=cn.origen_tipo,
        origen_detalle=cn.origen_detalle,
    )
    db.add(cliente)
    db.flush()  # asigna cliente.id sin cerrar la transacción
    for c in cn.contactos:
        db.add(Contacto(cliente_id=cliente.id, nombre=c.nombre,
                        telefono=c.telefono, email=c.email, tipo=c.tipo))
    return cliente


def _nueva_oportunidad(db: Session, cliente: Cliente, nombre: str | None,
                       tipo_servicio, notas: str | None,
                       current: Usuario) -> Oportunidad:
    """La oportunidad y su fila de histórico, sin commit."""
    op = Oportunidad(
        cliente_id=cliente.id,
        nombre=nombre,
        tipo_servicio=tipo_servicio,
        notas=notas,
        estado="oportunidad",          # SIEMPRE server-side (spec §3.1)
        estado_desde=col_now(),
        creado_por_usuario_id=current.id,
    )
    db.add(op)
    db.flush()
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=op.id, estado_anterior=None,
        estado_nuevo="oportunidad", usuario_id=current.id))
    return op


@router.post("/oportunidades", status_code=201)
def create_oportunidad(
    data: OportunidadCreate,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Crea la oportunidad SOLA, sin ofertas. Se conserva para el import y para
    quien la consuma por API; el registro de la UI usa POST /comercial/registrar,
    porque una oportunidad sin ofertas no se ve en ninguna vista."""
    _check_comercial(current)
    cliente = _resolver_cliente(db, data.cliente_id, data.cliente_nuevo,
                                data.forzar_cliente_duplicado)
    op = _nueva_oportunidad(db, cliente, data.nombre, data.tipo_servicio,
                            data.notas, current)
    db.commit()
    db.refresh(op)
    return _op_base_out(op, cliente, None, col_now()) | {"num_proyectos": 0, "capacidad_total_kwp": 0.0}


@router.post("/registrar", status_code=201)
def registrar(
    data: RegistroComercialIn,
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Registro comercial completo en UNA transacción: cliente + oportunidad +
    sus ofertas. Es lo que usa el wizard de la UI.

    Todo o nada a propósito. En dos llamadas, cuando la segunda fallaba quedaba
    una oportunidad sin ofertas: la UI decía "creado" y después no aparecía en
    ninguna vista, porque el tablero y la tabla se alimentan de las ofertas.
    """
    _check_comercial(current)
    cliente = _resolver_cliente(db, data.cliente_id, data.cliente_nuevo,
                                data.forzar_cliente_duplicado)
    op = _nueva_oportunidad(db, cliente, data.nombre, None, data.notas, current)
    ofertas = [_nueva_oferta(db, op.id, oferta, current) for oferta in data.ofertas]
    db.commit()
    db.refresh(op)
    for o in ofertas:
        db.refresh(o)
    fichas = _fichas(db, ofertas)
    plantas = _plantas_de_ofertas(db, ofertas)
    base = _op_base_out(op, cliente, None, col_now(),
                        [(_valor(o.estado), o.estado_desde) for o in ofertas])
    return base | {
        "num_proyectos": 0,
        "capacidad_total_kwp": 0.0,
        "ofertas": [_oferta_out(o, fichas[o.id], plantas.get(o.id, [])) for o in ofertas],
    }


@router.get("/oportunidades/{id}")
def get_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    op = (
        db.query(Oportunidad)
        .options(
            selectinload(Oportunidad.cliente).selectinload(Cliente.contactos),
            selectinload(Oportunidad.proyectos),
            selectinload(Oportunidad.gestiones),
            selectinload(Oportunidad.historial),
            selectinload(Oportunidad.documentos),
            selectinload(Oportunidad.ofertas),
        )
        .filter(Oportunidad.id == id, Oportunidad.deleted_at.is_(None))
        .first()
    )
    if not op:
        raise HTTPException(404, "Oportunidad no encontrada")
    ultima = op.gestiones[0].fecha if op.gestiones else None
    base = _op_base_out(op, op.cliente, ultima, col_now(),
                        [(_valor(o.estado), o.estado_desde) for o in op.ofertas])
    fichas_op = _fichas(db, op.ofertas)
    plantas_op = _plantas_de_ofertas(db, op.ofertas)
    base.update({
        "notas": op.notas,
        "fecha_tentativa_inicio_representacion": op.fecha_tentativa_inicio_representacion,
        "fecha_tentativa_inicio_compra_energia": op.fecha_tentativa_inicio_compra_energia,
        "fecha_estimada_firma": op.fecha_estimada_firma,
        "cliente": {
            "id": op.cliente.id,
            "razon_social_nombre": op.cliente.razon_social_nombre,
            "nit_cedula": op.cliente.nit_cedula,
            "origen_tipo": op.cliente.origen_tipo,
            "origen_detalle": op.cliente.origen_detalle,
        },
        "proyectos": [_proyecto_out(p) for p in op.proyectos if p.deleted_at is None],
        "documentos": [
            {"id": d.id, "tipo": d.tipo if isinstance(d.tipo, str) else d.tipo.value,
             "nombre": d.nombre, "numero": d.numero,
             "estado": d.estado if isinstance(d.estado, str) else d.estado.value,
             "archivo_url": d.archivo_url, "archivo_nombre": d.archivo_nombre,
             "fecha": d.fecha}
            for d in op.documentos
        ],
        "gestiones": [
            {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
             "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id,
             "oferta_id": g.oferta_id}
            for g in op.gestiones
        ],
        "historial": [
            {"id": h.id, "estado_anterior": h.estado_anterior,
             "estado_nuevo": h.estado_nuevo, "fecha": h.created_at,
             "usuario_id": h.usuario_id, "oferta_id": h.oferta_id}
            for h in op.historial
        ],
        "ofertas": [_oferta_out(o, fichas_op[o.id], plantas_op.get(o.id, []))
                    for o in op.ofertas],
        "resumen_ofertas": _resumen_ofertas(op.ofertas),
    })
    return base


@router.patch("/oportunidades/{id}")
def update_oportunidad(
    id: int, data: OportunidadUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(op, k, v)
    db.commit()
    return {"ok": True, "id": op.id}


@router.delete("/oportunidades/{id}", status_code=204)
def delete_oportunidad(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin puede eliminar oportunidades")
    op = _get_oportunidad_or_404(id, db)
    # Los proyectos NO se borran: se desvinculan (spec §7).
    db.query(Proyecto).filter(Proyecto.oportunidad_id == id).update({"oportunidad_id": None})
    op.deleted_at = col_now()
    db.commit()


@router.post("/oportunidades/{id}/estado")
def cambiar_estado(
    id: int, data: EstadoChangeIn,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Mueve TODAS las ofertas del cliente a una etapa. Se conserva porque el
    tablero viejo arrastra la tarjeta del cliente; para mover una sola oferta
    —que es lo normal— está POST /ofertas/{id}/estado."""
    _check_comercial(current)
    op = _get_oportunidad_or_404(id, db)
    ofertas = db.query(OportunidadOferta).filter(
        OportunidadOferta.oportunidad_id == op.id).all()
    ahora = col_now()
    movidas = 0
    for o in ofertas:
        actual = _valor(o.estado)
        if actual == data.estado:
            continue
        db.add(OportunidadEstadoHistorial(
            oportunidad_id=op.id, oferta_id=o.id, estado_anterior=actual,
            estado_nuevo=data.estado, usuario_id=current.id))
        o.estado = data.estado
        o.estado_desde = ahora
        o.resultado = estado_a_resultado(data.estado)
        movidas += 1
    # Espejo en la columna deprecada: hay históricos y consultas que aún la leen.
    if _valor(op.estado) != data.estado:
        if not ofertas:
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=op.id, estado_anterior=_valor(op.estado),
                estado_nuevo=data.estado, usuario_id=current.id))
        op.estado = data.estado
        op.estado_desde = ahora
    elif not movidas:
        raise HTTPException(409, f"Todo el negocio ya está en '{data.estado}'")
    db.commit()
    return {"ok": True, "estado": data.estado, "estado_desde": ahora,
            "ofertas_movidas": movidas}


@router.post("/ofertas/{oferta_id}/estado")
def cambiar_estado_oferta(
    oferta_id: int, data: EstadoChangeIn,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Mueve UNA oferta de etapa. Es la operación normal del tablero: una oferta
    se firma sin arrastrar a sus hermanas del mismo cliente."""
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if not o:
        raise HTTPException(404, "Oferta no encontrada")
    actual = _valor(o.estado)
    if data.estado == actual:
        raise HTTPException(409, f"La oferta ya está en '{actual}'")
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=o.oportunidad_id, oferta_id=o.id, estado_anterior=actual,
        estado_nuevo=data.estado, usuario_id=current.id))
    o.estado = data.estado
    o.estado_desde = col_now()
    o.resultado = estado_a_resultado(data.estado)
    db.commit()
    db.refresh(o)
    return _oferta_full(db, o)


@router.get("/oportunidades/{id}/gestiones")
def list_gestiones(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    gs = (
        db.query(OportunidadGestion)
        .filter(OportunidadGestion.oportunidad_id == id)
        .order_by(OportunidadGestion.fecha.desc())
        .all()
    )
    return [
        {"id": g.id, "tipo": g.tipo if isinstance(g.tipo, str) else g.tipo.value,
         "descripcion": g.descripcion, "fecha": g.fecha, "usuario_id": g.usuario_id,
         "oferta_id": g.oferta_id}
        for g in gs
    ]


@router.post("/oportunidades/{id}/gestiones", status_code=201)
def add_gestion(
    id: int, data: GestionCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    # Una gestión puede ser DE UNA OFERTA (apaga solo su alerta) o del cliente
    # (oferta_id NULL: cuenta para todas). Se valida la pertenencia para que no
    # se pueda colgar la llamada de un cliente en la oferta de otro.
    if data.oferta_id is not None:
        propia = db.query(OportunidadOferta.id).filter(
            OportunidadOferta.id == data.oferta_id,
            OportunidadOferta.oportunidad_id == id).first()
        if not propia:
            raise HTTPException(422, "La oferta no pertenece a esta oportunidad")
    g = OportunidadGestion(
        oportunidad_id=id, oferta_id=data.oferta_id, tipo=data.tipo,
        descripcion=data.descripcion,
        fecha=data.fecha or col_now(), usuario_id=current.id)
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "tipo": data.tipo, "descripcion": g.descripcion,
            "fecha": g.fecha, "oferta_id": g.oferta_id}


@router.post("/oportunidades/{id}/proyectos", status_code=201)
def add_proyecto(
    id: int, data: ProyectoDesdeCRMIn,
    forzar: bool = Query(False, description="true: crear aunque exista un nombre muy parecido"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Agregar proyecto desde el CRM. El proyecto creado ES un Proyecto normal
    de la plataforma (misma tabla); solo queda vinculado a la oportunidad.
    Validación bloqueante: operador de red obligatorio y del catálogo."""
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    operador = db.query(OperadorRed).filter(OperadorRed.id == data.operador_red_id).first()
    if not operador:
        raise HTTPException(422, "Debes seleccionar un operador de red válido del catálogo")

    # Mismo aviso de duplicado por nombre que el POST /proyectos general.
    from app.api.v1.proyectos import _buscar_duplicado_por_nombre
    if not forzar:
        duplicado = _buscar_duplicado_por_nombre(db, data.nombre_comercial)
        if duplicado:
            raise HTTPException(409, {
                "codigo": "posible_duplicado",
                "mensaje": f"Ya existe un proyecto con nombre parecido: {duplicado.nombre_comercial}",
                "proyecto_id": duplicado.id,
            })

    p = Proyecto(
        nombre_comercial=data.nombre_comercial,
        potencia_instalada_kwp=data.potencia_instalada_kwp,
        departamento=data.departamento,
        municipio=data.municipio,
        operador_red_id=operador.id,
        # Sincroniza el texto legacy para que las vistas viejas lo muestren.
        operador_red=operador.nombre_comercial or operador.nombre_legal,
        oportunidad_id=id,
        origen="manual",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proyecto_out(p)


@router.get("/oportunidades/{id}/ofertas")
def list_ofertas(id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    ofs = (
        db.query(OportunidadOferta)
        .filter(OportunidadOferta.oportunidad_id == id)
        .order_by(OportunidadOferta.id).all()
    )
    fichas = _fichas(db, ofs)
    plantas = _plantas_de_ofertas(db, ofs)
    return [_oferta_out(o, fichas[o.id], plantas.get(o.id, [])) for o in ofs]


@router.post("/oportunidades/{id}/ofertas", status_code=201)
def create_oferta(
    id: int, data: OfertaCreate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    _get_oportunidad_or_404(id, db)
    o = _nueva_oferta(db, id, data, current)
    db.commit()
    db.refresh(o)
    return _oferta_full(db, o)


def _nueva_oferta(db: Session, oportunidad_id: int, data: OfertaCreate,
                  current: Usuario) -> OportunidadOferta:
    """Crea la oferta y su fila de histórico SIN commit, para que el registro
    completo (cliente + oportunidad + N ofertas) quepa en una transacción."""
    payload = data.model_dump()
    # `proyecto_ids` no es columna: es la M2M, y se escribe cuando la oferta ya
    # tiene id.
    proyecto_ids = payload.pop("proyecto_ids", None)
    _validar_operador_red(db, payload.get("operador_red_id"))
    # Autogenera el código de seguimiento OP.{SEG} No.{NNNN}-{MM}-{YYYY} si no se envió.
    if not payload.get("numero_oferta"):
        payload["numero_oferta"] = _gen_codigo(db, payload["tipo"], payload.get("fecha_oferta"))
    payload["resultado"] = estado_a_resultado(payload["estado"])
    o = OportunidadOferta(oportunidad_id=oportunidad_id, estado_desde=col_now(), **payload)
    db.add(o)
    db.flush()
    if proyecto_ids is not None:
        _set_plantas(db, o, proyecto_ids)
    db.add(OportunidadEstadoHistorial(
        oportunidad_id=oportunidad_id, oferta_id=o.id, estado_anterior=None,
        estado_nuevo=payload["estado"], usuario_id=current.id))
    return o


@router.patch("/ofertas/{oferta_id}")
def update_oferta(
    oferta_id: int, data: OfertaUpdate,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if not o:
        raise HTTPException(404, "Oferta no encontrada")
    cambios = data.model_dump(exclude_unset=True)
    if "operador_red_id" in cambios:
        _validar_operador_red(db, cambios["operador_red_id"])
    # La M2M se escribe aparte y ella misma sincroniza `proyecto_id`, así que se
    # aplica DESPUÉS de los setattr para que no la pise un proyecto_id explícito.
    proyecto_ids = cambios.pop("proyecto_ids", None)
    for k, v in cambios.items():
        setattr(o, k, v)
    if proyecto_ids is not None:
        _set_plantas(db, o, proyecto_ids)
    db.commit()
    db.refresh(o)
    # Devuelve la fila completa (antes: {"ok": true}) para que el autosave del
    # drawer refresque la ficha resuelta sin recargar la lista entera.
    return _oferta_full(db, o)


@router.post("/ofertas/{oferta_id}/firmar", status_code=201)
def firmar_oferta(
    oferta_id: int, data: FirmarOfertaIn,
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """La oferta evoluciona en su contrato PPA y queda 'firmada'.

    Crea el PPAContrato con las condiciones pactadas (y sus ppa_tarifas si hay
    tabla por año), lo enlaza a la oferta y le pasa la planta. Las condiciones
    NO se copian a la oferta: el contrato es la fuente única, que es lo que ya
    leen Cumplimiento y Liquidaciones.

    Idempotente por enlace: si la oferta ya tiene contrato, responde 409 en vez
    de crear un segundo.
    """
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if not o:
        raise HTTPException(404, "Oferta no encontrada")
    if o.ppa_contrato_id:
        raise HTTPException(409, f"La oferta ya tiene el contrato PPA {o.ppa_contrato_id}")
    if _valor(o.tipo) not in TIPOS_ENERGIA:
        raise HTTPException(
            422, "Solo las ofertas de energía (compra o comunidad energética) "
                 "derivan en un PPA; las de servicios usan el contrato de "
                 "representación")
    op = _get_oportunidad_or_404(o.oportunidad_id, db)
    cliente = db.query(Cliente).filter(Cliente.id == op.cliente_id).first()

    contrato = PPAContrato(
        numero_codigo_contrato=data.numero_codigo_contrato or _norm_codigo(o.numero_oferta),
        nombre_interno=data.nombre_interno or o.planta_nombre,
        # Unergy compra la energía al generador: el cliente de la oferta vende.
        vendedor_id=op.cliente_id,
        vendedor_nombre=cliente.razon_social_nombre if cliente else None,
        vendedor_nit=cliente.nit_cedula if cliente else None,
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        tarifa_base=data.tarifa_base or _tarifa_del_primer_anio(data),
        indice_indexacion=data.indice_indexacion,
        periodo_indexacion_base=data.periodo_indexacion_base,
        cantidad_minima_kwh_mes=data.cantidad_minima_kwh_mes,
        carpeta_link=data.carpeta_link,
        tipo_contrato="compra",
        # La característica pasa a vivir en el contrato: si mañana se borra la
        # oferta, el PPA sigue sabiendo lo que es.
        es_comunidad_energetica=(_valor(o.tipo) == "comunidad_energetica"),
    )
    # TODAS las plantas de la oferta, no solo la del proyecto_id: una oferta que
    # cubre dos plantas debe firmar un contrato con las dos, o Cumplimiento mediría
    # el compromiso entero contra la generación de media planta.
    contrato.proyectos = _plantas_de_la_oferta(o, db)
    db.add(contrato)
    db.flush()

    # La tabla de precios por año se expande a las 12 filas mensuales que espera
    # ppa_tarifas, acotada al periodo de suministro real.
    for fila in _tarifas_mensuales(data):
        db.add(PPATarifa(contrato_id=contrato.id, **fila))

    o.ppa_contrato_id = contrato.id
    anterior = _valor(o.estado)
    if anterior != "firmado":
        db.add(OportunidadEstadoHistorial(
            oportunidad_id=op.id, oferta_id=o.id, estado_anterior=anterior,
            estado_nuevo="firmado", usuario_id=current.id))
        o.estado = "firmado"
        o.estado_desde = col_now()
        o.resultado = estado_a_resultado("firmado")
    db.commit()
    db.refresh(o)
    return {"oferta": _oferta_full(db, o), "ppa_contrato_id": contrato.id,
            "tarifas_creadas": len(_tarifas_mensuales(data)),
            # Cuántas plantas quedaron en el contrato. Firmar con 0 es legítimo
            # —la planta puede no existir todavía como Proyecto— pero Cumplimiento
            # no puede medir ese PPA, así que el dato viaja para que la UI avise en
            # vez de dejarlo pasar en silencio.
            "plantas_del_contrato": len(contrato.proyectos)}


def _plantas_de_la_oferta(oferta, db) -> list:
    """Las plantas asociadas a la oferta: las de la M2M si tiene, y si no la del
    `proyecto_id` único. Mismo criterio que usa la vista PPA-céntrica, para que lo
    que se firma sea exactamente lo que se venía mostrando en el borrador."""
    ids = [pid for (pid,) in db.execute(
        oportunidad_oferta_proyectos_table.select().with_only_columns(
            oportunidad_oferta_proyectos_table.c.proyecto_id)
        .where(oportunidad_oferta_proyectos_table.c.oferta_id == oferta.id)).all()]
    if not ids and oferta.proyecto_id:
        ids = [oferta.proyecto_id]
    if not ids:
        return []
    return db.query(Proyecto).filter(Proyecto.id.in_(ids),
                                     Proyecto.deleted_at.is_(None)).all()


def _tarifa_del_primer_anio(data: FirmarOfertaIn) -> float | None:
    """tarifa_base del contrato cuando el precio viene como tabla por año."""
    if not data.precios_anuales:
        return None
    return min(data.precios_anuales, key=lambda p: p.anio).precio


def _tarifas_mensuales(data: FirmarOfertaIn) -> list[dict]:
    """Expande la tabla anual de la oferta a filas (año, mes, tarifa).

    ppa_tarifas es mensual porque los contratos viejos indexan mes a mes; las
    ofertas nuevas traen un solo precio por año, así que se replica en sus 12
    meses. Se recorta al periodo de suministro: un contrato que arranca en
    octubre no tiene tarifa de enero a septiembre de ese año.
    """
    if not data.precios_anuales:
        return []
    filas = []
    for p in data.precios_anuales:
        desde = data.fecha_inicio.month if p.anio == data.fecha_inicio.year else 1
        hasta = data.fecha_fin.month if p.anio == data.fecha_fin.year else 12
        if p.anio < data.fecha_inicio.year or p.anio > data.fecha_fin.year:
            continue          # año fuera del periodo: la oferta lo trae de más
        for mes in range(desde, hasta + 1):
            filas.append({"año": p.anio, "mes": mes, "tarifa": p.precio})
    return filas


@router.post("/ofertas/{oferta_id}/seguimiento")
def registrar_seguimiento(oferta_id: int, db: Session = Depends(get_db),
                          current: Usuario = Depends(get_current_user)):
    """Un click: suma un toque a la oferta. Es lo que permite mantener el dato
    al día sin volver a exportar correos. NO toca fecha_oferta: el toque de hoy
    no es el primer envío."""
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if not o:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    o.seguimientos = (o.seguimientos or 0) + 1
    db.commit()
    db.refresh(o)
    return _oferta_full(db, o)


@router.delete("/ofertas/{oferta_id}", status_code=204)
def delete_oferta(oferta_id: int, db: Session = Depends(get_db), current: Usuario = Depends(get_current_user)):
    _check_comercial(current)
    o = db.query(OportunidadOferta).filter(OportunidadOferta.id == oferta_id).first()
    if o:
        db.delete(o)
        db.commit()


@router.post("/backfill")
def backfill(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Migración inicial: 1 oportunidad en 'operando' por cliente existente sin
    oportunidad, vinculando sus proyectos (vía ProyectoInversionista — la
    misma relación que usa GET /clientes/{id}/proyectos). Idempotente."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")

    con_oportunidad = {
        cid for (cid,) in db.query(Oportunidad.cliente_id)
        .filter(Oportunidad.deleted_at.is_(None)).distinct().all()
    }
    clientes = (
        db.query(Cliente).filter(Cliente.deleted_at.is_(None))
        .order_by(Cliente.id).all()
    )
    a_migrar = [c for c in clientes if c.id not in con_oportunidad]

    resumen = {"clientes_a_migrar": len(a_migrar), "proyectos_a_vincular": 0, "detalle": []}
    ahora = col_now()
    for c in a_migrar:
        proyecto_ids = [
            pid for (pid,) in (
                db.query(ProyectoInversionista.proyecto_id)
                .join(Proyecto, Proyecto.id == ProyectoInversionista.proyecto_id)
                .filter(ProyectoInversionista.cliente_id == c.id,
                        Proyecto.deleted_at.is_(None),
                        Proyecto.oportunidad_id.is_(None))
                .distinct().all()
            )
        ]
        resumen["proyectos_a_vincular"] += len(proyecto_ids)
        resumen["detalle"].append({"cliente_id": c.id, "razon_social": c.razon_social_nombre,
                                   "proyectos": len(proyecto_ids)})
        if not dry_run:
            op = Oportunidad(cliente_id=c.id, estado="operando", estado_desde=ahora,
                             es_migrada=True, creado_por_usuario_id=current.id)
            db.add(op)
            db.flush()
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=op.id, estado_anterior=None,
                estado_nuevo="operando", usuario_id=current.id))
            if proyecto_ids:
                db.query(Proyecto).filter(Proyecto.id.in_(proyecto_ids)).update(
                    {"oportunidad_id": op.id}, synchronize_session=False)
    if not dry_run:
        db.commit()
    resumen["dry_run"] = dry_run
    return resumen


# ── Importación de las hojas de prospección (Google Sheets → CRM) ──────────────
_SEED_PATH = Path("data/comercial_seed.json")

_ETAPA_A_RESULTADO = {
    "aprobado": "aceptado",
    "denegado": "declinado",
    "propuesta enviada": "pendiente",
    "sin respuesta": "pendiente",
}


def _norm_nombre(s: str | None) -> str:
    """Normaliza razón social / nombre de planta para matching: sin tildes,
    minúsculas, sin sufijos societarios, solo alfanumérico."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(s\.?a\.?s\.?|e\.?s\.?p\.?|s\.?a\.?|bic|ltda)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _parse_fecha(s):
    if not s:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _etapa_global(resultados: set[str]) -> str:
    if "aceptado" in resultados:
        return "operando"
    if resultados & {"pendiente"}:
        return "oferta"
    return "oportunidad"


def _etapa_de_resultado(resultado: str) -> str:
    """Etapa inicial de una oferta importada de las hojas, donde lo único que
    hay es el resultado. 'aceptado' entra como operando porque las hojas solo
    marcaban así lo que ya estaba andando."""
    return {"aceptado": "operando", "declinado": "declinado"}.get(resultado, "oferta")


def _build_detalle(row: dict) -> dict | None:
    """Detalle crudo de la hoja para la sub-oferta. Para servicios_operacionales
    parsea 'Servicios buscados' (viñetas) en una lista para identificar cada
    servicio; agrega FPO y, si vinieran, tiempo/tipo de contrato de energía."""
    d: dict = {}
    sb = row.get("servicios_buscados")
    if sb:
        servicios = [s.strip(" •").strip() for s in str(sb).split("•") if s.strip(" •").strip()]
        if servicios:
            d["servicios"] = servicios
        d["servicios_texto"] = sb
    for k in ("fpo", "tiempo", "tipo_contrato"):
        if row.get(k):
            d[k] = row[k]
    return d or None


@router.post("/importar-hojas")
def importar_hojas(
    dry_run: bool = Query(True),
    crear_faltantes: bool = Query(True, description="false: solo enriquece ofertas ya existentes, no crea nuevas"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Carga/sincroniza las hojas de prospección (Servicios Operacionales +
    Comercialización de Energía + Comunidades) al CRM. Una oportunidad por
    cliente (find-or-create); cada fila de hoja = una sub-oferta. Upsert por
    `numero_oferta` o, si falta, por (cliente, tipo, planta): si la oferta ya
    existe, RELLENA los campos vacíos (detalle/precio/contrato/planta/fecha) sin
    pisar `resultado`/`etapa`. `crear_faltantes=false` solo enriquece. Solo
    admin; `dry_run=true` no escribe."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")
    if not _SEED_PATH.exists():
        raise HTTPException(500, f"No se encontró la semilla en {_SEED_PATH}")
    seed = json.loads(_SEED_PATH.read_text(encoding="utf-8"))

    # Índices para matching.
    proy_idx = {}
    for pid, nom in db.query(Proyecto.id, Proyecto.nombre_comercial).filter(Proyecto.deleted_at.is_(None)).all():
        if nom:
            proy_idx.setdefault(_norm_nombre(nom), pid)

    # planta→empresa dueña (para cruzar la hoja de energía, cuya 'empresa' a veces
    # es el nombre de la planta) usando las filas de servicios como referencia.
    planta_a_empresa = {}
    for row in seed:
        if row.get("planta_nombre"):
            planta_a_empresa[_norm_nombre(row["planta_nombre"])] = row["empresa"]

    cli_idx = {}
    for c in db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all():
        cli_idx.setdefault(_norm_nombre(c.razon_social_nombre), c)

    op_por_cliente = {}
    for op in db.query(Oportunidad).filter(Oportunidad.deleted_at.is_(None)).all():
        op_por_cliente.setdefault(op.cliente_id, op)

    # Clave de dedup/upsert: por numero_oferta si existe; si no, (cliente, tipo, planta).
    of_por_key = {}
    existentes = (
        db.query(OportunidadOferta, Cliente.razon_social_nombre)
        .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id).all()
    )
    for o, razon in existentes:
        t = o.tipo if isinstance(o.tipo, str) else o.tipo.value
        k = o.numero_oferta if o.numero_oferta else (_norm_nombre(razon), t, _norm_nombre(o.planta_nombre))
        of_por_key.setdefault(k, o)
    seen_run = set()   # dedup dentro del propio seed

    res = {
        "dry_run": dry_run,
        "clientes": {"a_crear": 0, "reusados": 0},
        "ofertas": {"creadas": 0, "enriquecidas": 0, "sin_cambio": 0, "faltantes_no_creadas": 0},
        "sin_empresa": 0,
        "detalle": {"clientes_nuevos": [], "sin_match_planta": [], "fusionados_por_similitud": []},
    }
    ahora = col_now()
    # Acumula resultados por cliente para derivar la etapa global de la oportunidad.
    resultados_por_cli: dict = {}
    # Oportunidades creadas en ESTE import (solo a estas se les fija la etapa global;
    # las preexistentes conservan su estado).
    ops_creadas: set = set()

    def resolver_cliente(empresa_raw):
        """Cliente EXISTENTE que corresponde a esta empresa, de forma DETERMINISTA
        (exacto por nombre normalizado, o planta→dueño), o None si habría que
        crearlo. Puro: no crea ni cuenta. NO usa match difuso a propósito: el fuzzy
        cambia entre corridas (crece el set de candidatos) y rompería la
        idempotencia del import; los duplicados por similitud los limpia después
        la tarea `dedup_clientes` (con guarda de ambigüedad y reversible)."""
        key = _norm_nombre(empresa_raw)
        if key in cli_idx:
            return cli_idx[key]
        dueno = planta_a_empresa.get(key)
        if dueno and _norm_nombre(dueno) in cli_idx:
            return cli_idx[_norm_nombre(dueno)]
        return None

    def oportunidad_para(cliente):
        if cliente is None:
            return None
        op = op_por_cliente.get(cliente.id)
        if op:
            return op
        op = Oportunidad(cliente_id=cliente.id, estado="oportunidad",
                         estado_desde=ahora, es_migrada=True,
                         creado_por_usuario_id=current.id)
        db.add(op)
        db.flush()
        db.add(OportunidadEstadoHistorial(
            oportunidad_id=op.id, estado_anterior=None,
            estado_nuevo="oportunidad", usuario_id=current.id))
        op_por_cliente[cliente.id] = op
        ops_creadas.add(op.id)
        return op

    for row in seed:
        empresa = (row.get("empresa") or "").strip()
        if not empresa:
            res["sin_empresa"] += 1
            continue
        tipo = row["tipo"]
        num = row.get("numero_oferta")
        planta = row.get("planta_nombre") or (empresa if tipo == "compra_energia" else None)
        # Clave de dedup coherente con el preload: por consecutivo, o por
        # (razón del cliente RESUELTO, tipo, planta). Usar el razón del cliente
        # resuelto (no el de la hoja) mantiene la idempotencia cuando el match es
        # difuso (empresa de la hoja ≠ razón social del cliente existente).
        resuelto = resolver_cliente(empresa)
        razon_key = _norm_nombre(resuelto.razon_social_nombre) if resuelto else _norm_nombre(empresa)
        key = num if num else (razon_key, tipo, _norm_nombre(planta))
        etapa = (row.get("etapa_texto") or "").strip().lower()
        resultado = _ETAPA_A_RESULTADO.get(etapa, "pendiente")
        proj_id = proy_idx.get(_norm_nombre(planta)) if planta else None
        if planta and proj_id is None:
            res["detalle"]["sin_match_planta"].append(planta)
        detalle = _build_detalle(row)

        existente = of_por_key.get(key)
        if existente is not None:
            # Enriquecer: rellenar SOLO los campos vacíos; nunca pisar resultado/etapa.
            if not dry_run:
                campos = {
                    "detalle": detalle, "precio_detalle": row.get("precio_detalle"),
                    "contrato_firmado": row.get("contrato_firmado"), "planta_nombre": planta,
                    "proyecto_id": proj_id, "fecha_oferta": _parse_fecha(row.get("fecha_oferta")),
                }
                cambio = False
                for campo, val in campos.items():
                    if val is not None and getattr(existente, campo) in (None, "", {}):
                        setattr(existente, campo, val)
                        cambio = True
                res["ofertas"]["enriquecidas" if cambio else "sin_cambio"] += 1
            else:
                res["ofertas"]["enriquecidas"] += 1
            continue

        if key in seen_run:      # duplicado dentro del propio seed
            res["ofertas"]["sin_cambio"] += 1
            continue
        seen_run.add(key)

        if not crear_faltantes:
            res["ofertas"]["faltantes_no_creadas"] += 1
            continue

        # Resolver-o-crear el cliente (ya pasado el dedup, solo al crear la oferta).
        if resuelto is not None:
            cliente = resuelto
            res["clientes"]["reusados"] += 1
            if _norm_nombre(empresa) != _norm_nombre(cliente.razon_social_nombre):
                res["detalle"]["fusionados_por_similitud"].append(
                    {"empresa_hoja": empresa, "cliente_existente": cliente.razon_social_nombre})
        else:
            res["clientes"]["a_crear"] += 1
            res["detalle"]["clientes_nuevos"].append(empresa)
            cliente = None
            if not dry_run:
                cliente = Cliente(razon_social_nombre=empresa)
                db.add(cliente)
                db.flush()
                cli_idx[_norm_nombre(empresa)] = cliente
        if not dry_run and cliente is not None:
            op = oportunidad_para(cliente)
            if op is not None:
                nueva = OportunidadOferta(
                    oportunidad_id=op.id, tipo=tipo, planta_nombre=planta,
                    proyecto_id=proj_id, numero_oferta=num,
                    precio_detalle=row.get("precio_detalle"), resultado=resultado,
                    estado=_etapa_de_resultado(resultado), estado_desde=col_now(),
                    etapa_texto=row.get("etapa_texto"),
                    contrato_firmado=row.get("contrato_firmado"),
                    fecha_oferta=_parse_fecha(row.get("fecha_oferta")),
                    detalle=detalle)
                db.add(nueva)
                of_por_key[key] = nueva
                resultados_por_cli.setdefault(cliente.id, set()).add(resultado)
        res["ofertas"]["creadas"] += 1

    # Etapa global solo de las oportunidades creadas en este import.
    if not dry_run:
        for cli_id, resultados in resultados_por_cli.items():
            op = op_por_cliente.get(cli_id)
            if op and op.id in ops_creadas:
                op.estado = _etapa_global(resultados)
        db.commit()
    return res


@router.post("/dedup-clientes")
def dedup_clientes(
    dry_run: bool = Query(True),
    umbral: float = Query(0.85, description="score mínimo para auto-fusionar (evita falsos positivos por palabras genéricas como 'energia')"),
    db: Session = Depends(get_db), current: Usuario = Depends(get_current_user),
):
    """Limpia los clientes-prospecto que el import creó por duplicado cuando ya
    existía el cliente operativo. CONSERVADOR y REVERSIBLE:
    - candidato = cliente con origen_tipo NULL + oportunidad es_migrada con ≥1
      oferta + SIN huella operativa (no inversionista/contrato/PPA); o sea un
      prospecto puro creado por el import.
    - canónico: vía el matcher difuso compartido (app.utils.nombre_matching, con
      guarda de ambigüedad): (a) la planta de alguna de sus ofertas coincide con
      un Proyecto existente cuyo dueño (inversionista) es un cliente NO prospecto
      → ese dueño; o (b) la razón social coincide con otro cliente no prospecto.
      Si no hay match confiable/único, se deja intacto (sin_canonico).
    - acción: mueve las ofertas al canónico (enlazando proyecto_id) y hace
      soft-delete del prospecto y su oportunidad (deleted_at; reversible).
    Idempotente. Solo admin; dry_run=true no escribe."""
    if current.rol.value != "admin":
        raise HTTPException(403, "Solo admin")
    from app.services.clientes_panel import proyectos_por_cliente

    # Candidatos: clientes con oportunidad es_migrada que tiene ofertas.
    cand_ids = {
        cid for (cid,) in db.query(Oportunidad.cliente_id)
        .join(OportunidadOferta, OportunidadOferta.oportunidad_id == Oportunidad.id)
        .filter(Oportunidad.deleted_at.is_(None), Oportunidad.es_migrada.is_(True))
        .distinct().all()
    }
    footprint = proyectos_por_cliente(db, cand_ids) if cand_ids else {}
    prospect_ids = {
        c.id for c in db.query(Cliente).filter(Cliente.id.in_(cand_ids)).all()
        if c.id in cand_ids and c.origen_tipo is None and c.deleted_at is None
        and not footprint.get(c.id)
    } if cand_ids else set()

    # Candidatos para el matcher difuso compartido (app.utils.nombre_matching):
    # tolera tildes/typos, ignora ruido del sector (solar/granja/gd…) y NO adivina
    # si dos candidatos quedan parejos (guarda de ambigüedad).
    proy_items = [
        (pid, [nom]) for pid, nom in
        db.query(Proyecto.id, Proyecto.nombre_comercial).filter(Proyecto.deleted_at.is_(None)).all()
        if nom
    ]
    owners: dict = {}
    for pid, cid in db.query(ProyectoInversionista.proyecto_id, ProyectoInversionista.cliente_id).all():
        owners.setdefault(pid, []).append(cid)
    cli_items = [
        (c.id, [c.razon_social_nombre])
        for c in db.query(Cliente).filter(Cliente.deleted_at.is_(None)).all()
        if c.id not in prospect_ids and c.razon_social_nombre
    ]

    res = {"dry_run": dry_run, "prospectos": len(prospect_ids),
           "fusionados": 0, "sin_canonico": 0, "detalle": [], "sin_canonico_nombres": []}

    for C in db.query(Cliente).filter(Cliente.id.in_(prospect_ids)).all() if prospect_ids else []:
        ofertas = (
            db.query(OportunidadOferta)
            .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
            .filter(Oportunidad.cliente_id == C.id, Oportunidad.deleted_at.is_(None)).all()
        )
        canonico = None
        matched_proy = None
        regla = None
        # 1) La planta de alguna oferta (o la razón social, útil cuando la "empresa"
        #    de la hoja de energía era el nombre de la planta) matchea un Proyecto
        #    existente → su dueño operativo es el canónico.
        for nombre in [o.planta_nombre for o in ofertas if o.planta_nombre] + [C.razon_social_nombre]:
            pid, score = mejor_candidato(nombre, proy_items)
            if pid and score >= umbral:
                for owner in owners.get(pid, []):
                    if owner not in prospect_ids and owner != C.id:
                        canonico, matched_proy, regla = owner, pid, f"planta→dueño ({score})"
                        break
            if canonico:
                break
        # 2) Si no, la razón social matchea directamente un cliente operativo.
        if not canonico:
            did, score = mejor_candidato(C.razon_social_nombre, cli_items)
            if did and did != C.id and score >= umbral:
                canonico, regla = did, f"nombre ({score})"
        if not canonico:
            res["sin_canonico"] += 1
            if len(res["sin_canonico_nombres"]) < 80:
                res["sin_canonico_nombres"].append(C.razon_social_nombre)
            continue

        res["fusionados"] += 1
        res["detalle"].append({"prospecto_id": C.id, "prospecto": C.razon_social_nombre,
                               "canonico_id": canonico, "regla": regla,
                               "ofertas": len(ofertas), "proyecto": matched_proy})
        if dry_run:
            continue

        # Oportunidad destino del canónico (reusar o crear).
        d_op = (db.query(Oportunidad)
                .filter(Oportunidad.cliente_id == canonico, Oportunidad.deleted_at.is_(None))
                .order_by(Oportunidad.id).first())
        if not d_op:
            d_op = Oportunidad(cliente_id=canonico, estado="operando",
                               estado_desde=col_now(), es_migrada=True,
                               creado_por_usuario_id=current.id)
            db.add(d_op)
            db.flush()
            db.add(OportunidadEstadoHistorial(
                oportunidad_id=d_op.id, estado_anterior=None,
                estado_nuevo="operando", usuario_id=current.id))
        for o in ofertas:
            o.oportunidad_id = d_op.id
            if matched_proy and o.proyecto_id is None:
                o.proyecto_id = matched_proy
        # Soft-delete del prospecto y sus oportunidades (ya vacías).
        for op in db.query(Oportunidad).filter(Oportunidad.cliente_id == C.id, Oportunidad.deleted_at.is_(None)).all():
            op.deleted_at = col_now()
        C.deleted_at = col_now()

    if not dry_run:
        db.commit()
    return res


ARCHIVO_ACTUALIZACION = "comercial_actualizacion_2026-07.json"


def ruta_actualizacion() -> Path:
    """data/comercial_actualizacion_2026-07.json, desde la raíz del repo
    (app/api/v1/comercial.py → tres niveles arriba de `app`)."""
    return Path(__file__).resolve().parents[3] / "data" / ARCHIVO_ACTUALIZACION


@router.post("/aplicar-actualizacion")
def aplicar_actualizacion(
    dry_run: bool = Query(True),
    db: Session = Depends(get_db),
    current: Usuario = Depends(get_current_user),
):
    """Aplica data/comercial_actualizacion_2026-07.json (envíos de oferta y
    estados reportados por Alejandro). Admin. dry_run por defecto: devuelve el
    reporte sin escribir nada."""
    from app.services.comercial_actualizacion import aplicar, validar, ya_aplicado

    rol = current.rol if isinstance(current.rol, str) else current.rol.value
    if rol != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")
    ruta = ruta_actualizacion()
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="Archivo de actualización no encontrado")
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    problemas = validar(datos)
    if problemas and not dry_run:
        raise HTTPException(status_code=422, detail={"problemas_del_archivo": problemas})
    rep = aplicar(db, datos, dry_run=dry_run)
    rep["problemas_del_archivo"] = problemas
    rep["ya_aplicado"] = ya_aplicado(db)
    return rep
