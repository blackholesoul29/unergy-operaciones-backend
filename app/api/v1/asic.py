from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import AsicSolicitud, PPAContrato, Proyecto
from app.models.asic import (
    AsicCambioContrato, GesconDiccionario,
    TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum,
)
from app.models.cumplimiento import CumplimientoMensual
from app.schemas.asic import (
    AsicSolicitudOut, AsicSolicitudCreate, AsicSolicitudUpdate,
    AsicModificacionCreate, AsicModificacionOut,
    AsicTerminacionCreate, AsicTerminacionOut,
    AsicCambioCreate, AsicCambioOut, GesconDiccionarioCreate, GesconDiccionarioOut,
)
from app.utils.gescon_vigencia import resolver_vigencias

router = APIRouter(prefix="/asic", tags=["ASIC"])


def _auto_terminate(db: Session, solicitud: AsicSolicitud) -> list[AsicSolicitud]:
    """
    Al publicar una terminación, su `fecha_fin` se estampa como `fecha_fin` del/los
    registro(s) vigente(s) del MISMO código SIC (nivel planta). Los registros NO se
    marcan 'terminado': siguen 'publicado' para que Cumplimiento los prorratee HASTA la
    fecha y los excluya DESPUÉS — el histórico previo a la terminación queda intacto.

    El `fecha_fin` del contrato PPA comercial es un campo manual (fuente de verdad del
    contrato firmado): esta función NO lo toca. Inferirlo automáticamente a partir de
    fechas sueltas en registros/modificaciones de ASIC resultó frágil — cualquier
    `fecha_fin` cargada en una planta por un motivo ajeno a una terminación real (p.ej.
    vigencia de registro GESCON) contaminaba el cierre del contrato completo. Si el
    contrato macro debe cerrarse, se edita directamente en la pestaña PPA. Ver
    `_validar_fecha_fin_vs_ppa` para la regla inversa: ninguna planta puede tener una
    fecha_fin posterior a la del contrato macro.

    Devuelve los registros a los que efectivamente se les estampó la fecha (los que
    ya terminaban antes no se tocan), para poder reportarlos a quien la radica.
    """
    if (
        solicitud.tipo_solicitud != TipoSolicitudAsicEnum.terminacion
        or solicitud.estado_solicitud != EstadoSolicitudAsicEnum.publicado
        or not solicitud.codigo_sic_contrato
        or solicitud.fecha_fin is None
    ):
        return []

    fecha_term = solicitud.fecha_fin

    # Nivel planta: estampar fecha_fin en los registros del mismo SIC.
    targets = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.id != solicitud.id,
            AsicSolicitud.codigo_sic_contrato == solicitud.codigo_sic_contrato,
            AsicSolicitud.estado_solicitud == EstadoSolicitudAsicEnum.publicado,
            AsicSolicitud.tipo_solicitud.in_([
                TipoSolicitudAsicEnum.registro,
                TipoSolicitudAsicEnum.modificacion,
            ]),
        )
        .all()
    )

    cerrados = []
    for t in targets:
        if t.fecha_fin is None or t.fecha_fin > fecha_term:
            t.fecha_fin = fecha_term
            cerrados.append(t)

    return cerrados


def _validar_fecha_fin_vs_ppa(db: Session, solicitud: AsicSolicitud) -> None:
    """Ninguna fecha_fin de un registro GESCON puede ser posterior a la fecha_fin
    (manual) de su contrato PPA macro. Evita que una planta quede "vigente" mas alla
    de lo que el contrato comercial permite."""
    if solicitud.fecha_fin is None:
        return
    ppa = _resolver_ppa_para(solicitud, db)
    if ppa is None or ppa.fecha_fin is None:
        return
    if solicitud.fecha_fin > ppa.fecha_fin:
        nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
        raise HTTPException(
            422,
            f"La fecha de fin ({solicitud.fecha_fin.isoformat()}) no puede ser "
            f"posterior a la del contrato PPA \"{nombre_ppa}\" "
            f"({ppa.fecha_fin.isoformat()}). Corrige la fecha o actualiza primero "
            f"el contrato macro.",
        )


def _validar_flags_exclusivos(es_duplicado: bool, uso_del_recurso: bool) -> None:
    """'Compra en bolsa' (es_duplicado) y 'Uso del recurso' son figuras distintas:
    la primera es compra real en el mercado spot; la segunda, compromiso de pagarle
    al cliente a precio bolsa una planta que entra al contrato. No pueden coexistir."""
    if es_duplicado and uso_del_recurso:
        raise HTTPException(
            422,
            "Un registro no puede ser 'Compra en bolsa' y 'Uso del recurso' a la vez. "
            "Marca 'Compra en bolsa' si la planta coexiste en otro contrato con origen "
            "bolsa, o 'Uso del recurso' si el cliente está en bolsa y Unergy usa la "
            "planta para cumplir este contrato.",
        )


def _to_out(s: AsicSolicitud) -> AsicSolicitudOut:
    d = AsicSolicitudOut.model_validate(s)
    if s.proyecto:
        d.planta_nombre = s.proyecto.nombre_comercial
    return d


def _aplicar_vigencia(db: Session, outs: list[AsicSolicitudOut]) -> list[AsicSolicitudOut]:
    """Rellena fecha_fin_efectiva / es_version_vigente en cada salida.

    La resolución corre SIEMPRE sobre el universo completo de solicitudes
    publicadas (no sobre el subconjunto filtrado del request): el relevo que
    recorta a una fila puede venir de otra planta u otro contrato que el filtro
    excluyó. Filas no publicadas o desistimientos no participan del walk:
    conservan su fecha_fin cruda y es_version_vigente=False.
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
    vigencias = resolver_vigencias(universo)
    for o in outs:
        v = vigencias.get(o.id)
        if v is not None:
            o.fecha_fin_efectiva = v.fecha_fin_efectiva
            o.es_version_vigente = v.vigente
        else:
            o.fecha_fin_efectiva = o.fecha_fin
            o.es_version_vigente = False
    return outs


def _planta_por_sic(db: Session, sics: set[str]) -> dict[str, str]:
    """
    Mapa código SIC -> nombre(s) de planta, derivado de los registros vigentes
    (registro/modificacion) que SÍ tienen proyecto. Sirve para mostrar la planta
    en filas que no llevan proyecto_id (p. ej. terminaciones), sin almacenar el FK
    —lo que reintroduciría el bug de Cumplimiento—. Display-only.
    """
    if not sics:
        return {}
    rows = (
        db.query(AsicSolicitud)
        .options(joinedload(AsicSolicitud.proyecto))
        .filter(
            AsicSolicitud.codigo_sic_contrato.in_(sics),
            AsicSolicitud.proyecto_id.isnot(None),
            AsicSolicitud.tipo_solicitud.in_([
                TipoSolicitudAsicEnum.registro,
                TipoSolicitudAsicEnum.modificacion,
            ]),
        )
        .all()
    )
    nombres: dict[str, list[str]] = {}
    for r in rows:
        if not r.proyecto or not r.proyecto.nombre_comercial:
            continue
        nm = r.proyecto.nombre_comercial
        bucket = nombres.setdefault(r.codigo_sic_contrato, [])
        if nm not in bucket:
            bucket.append(nm)
    return {sic: " · ".join(ns) for sic, ns in nombres.items()}


def _enriquecer_planta(db: Session, outs: list[AsicSolicitudOut]) -> list[AsicSolicitudOut]:
    """Rellena planta_nombre en filas sin proyecto resuelto, vía su código SIC."""
    pendientes = {o.codigo_sic_contrato for o in outs if not o.planta_nombre and o.codigo_sic_contrato}
    if not pendientes:
        return outs
    mapa = _planta_por_sic(db, pendientes)
    for o in outs:
        if not o.planta_nombre and o.codigo_sic_contrato:
            o.planta_nombre = mapa.get(o.codigo_sic_contrato)
    return outs


@router.get("", response_model=list[AsicSolicitudOut])
def list_solicitudes(
    codigo_sic_contrato: str | None = Query(None),
    contrato_interno: str | None = Query(None),
    proyecto_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto))
    if codigo_sic_contrato:
        q = q.filter(AsicSolicitud.codigo_sic_contrato == codigo_sic_contrato)
    if contrato_interno:
        q = q.filter(AsicSolicitud.contrato_interno == contrato_interno)
    if proyecto_id:
        q = q.filter(AsicSolicitud.proyecto_id == proyecto_id)
    rows = q.order_by(AsicSolicitud.fecha_solicitud.desc().nullslast(), AsicSolicitud.id.desc()).all()
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s) for s in rows]))


@router.patch("/{id}", response_model=AsicSolicitudOut)
def patch_solicitud(
    id: int,
    data: AsicSolicitudUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    if not s:
        raise HTTPException(404, "No encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    _validar_flags_exclusivos(bool(s.es_duplicado), bool(s.uso_del_recurso))
    _validar_fecha_fin_vs_ppa(db, s)
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == id).first()
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s)]))[0]


@router.post("", response_model=AsicSolicitudOut, status_code=201)
def create_solicitud(
    data: AsicSolicitudCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = AsicSolicitud(**data.model_dump())
    _validar_flags_exclusivos(bool(s.es_duplicado), bool(s.uso_del_recurso))
    db.add(s)
    db.flush()
    _validar_fecha_fin_vs_ppa(db, s)
    _auto_terminate(db, s)
    db.commit()
    db.refresh(s)
    s = db.query(AsicSolicitud).options(joinedload(AsicSolicitud.proyecto)).filter(AsicSolicitud.id == s.id).first()
    return _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(s)]))[0]


# ── Modificación de un contrato ya registrado ────────────────────────────
# Una modificación NO es un registro nuevo: es otra versión del MISMO código
# SIC. Lo único que puede cambiar es la fecha de fin, la planta inscrita, su %
# de despacho y su modalidad de suministro. El resto se hereda de la versión
# vigente — pedirlo de nuevo es ruido y dejarlo vacío saca la fila de
# Cumplimiento, que agrupa por `contrato_interno`.

MODALIDADES_SUMINISTRO = ("normal", "duplicado", "uso_recurso")

_CAMPOS_HEREDADOS = (
    "codigo_sic_contrato", "codigo_sic_vendedor", "codigo_sic_comprador",
    "cedula_agente_vendedor", "cedula_agente_comprador", "contrato_interno",
    "nombre_interno", "nombre_contacto_solicitante", "prioridad_limitacion",
    "tipo_mercado", "tipo_asignacion", "porcentaje_fncer", "contrato_ppa_id",
)


def _versiones_vigentes_sic(
    db: Session, codigo_sic: str, en_fecha: date | None = None
) -> list[AsicSolicitud]:
    """Filas registro/modificación que son la versión vigente de un SIC.

    Puede devolver más de una: un SIC admite varias plantas coexistiendo
    (reemplaza_anterior=False). La resolución corre sobre el universo completo
    de publicadas, igual que en GET /asic — el relevo que recorta a una fila
    puede venir de otra planta.

    `en_fecha` deja solo las que siguen en vigor ese día: una planta que ya
    salió del SIC no debe contar como inscrita para una modificación posterior.
    Ojo: `es_version_vigente` significa "última versión de su SIC", no "en
    curso" — una fila con fecha_fin pasada sigue siendo la última versión.
    """
    universo = (
        db.query(AsicSolicitud)
        .options(joinedload(AsicSolicitud.proyecto))
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
    vigencias = resolver_vigencias(universo)
    vigentes = [
        r for r in universo
        if r.codigo_sic_contrato == codigo_sic
        and r.tipo_solicitud in (TipoSolicitudAsicEnum.registro, TipoSolicitudAsicEnum.modificacion)
        and vigencias[r.id].vigente
    ]
    if en_fecha is None:
        return vigentes
    en_vigor = [r for r in vigentes if r.fecha_fin is None or r.fecha_fin >= en_fecha]
    # Si a esa fecha ya no quedaba ninguna en vigor (caso: se está atrasando la
    # fecha de fin de un contrato que ya venció), se trabaja sobre las últimas
    # versiones; las validaciones de fecha de más abajo deciden si tiene sentido.
    return en_vigor or vigentes


def _nombre_planta(db: Session, proyecto_id: int | None) -> str:
    if proyecto_id is None:
        return "sin planta"
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id).first()
    return (p.nombre_comercial if p else None) or f"planta {proyecto_id}"


def _listado_plantas(db: Session, filas: list[AsicSolicitud]) -> str:
    return ", ".join(_nombre_planta(db, f.proyecto_id) for f in filas)


def _fmt_fecha(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "sin fecha"


def _pct(v) -> float | None:
    """Fracción 0-1 normalizada a float. Evita comparar Decimal contra float
    (Decimal('0.85') != 0.85 en Python) al detectar si el % realmente cambió."""
    return None if v is None else round(float(v), 4)


@router.post("/modificacion", response_model=AsicModificacionOut, status_code=201)
def create_modificacion(
    data: AsicModificacionCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Registra una modificación sobre un contrato GESCON existente.

    Pide solo lo que cambia (fecha de fin, planta, % de despacho, modalidad),
    la fecha en que entra en vigencia y el requerimiento nuevo; hereda el resto
    de la versión vigente del mismo código SIC. La modificación no surte efecto
    antes de `fecha_entrada`: se guarda como `fecha_inicio` y el resolutor de
    vigencias (app/utils/gescon_vigencia.py) recorta la versión anterior al día
    previo.
    """
    sic = (data.codigo_sic_contrato or "").strip()
    if not sic:
        raise HTTPException(422, "El código SIC del contrato a modificar es obligatorio.")

    activos = _versiones_vigentes_sic(db, sic, en_fecha=data.fecha_entrada)
    if not activos:
        raise HTTPException(
            404,
            f"No hay ningún registro publicado y vigente con el código SIC \"{sic}\". "
            "Una modificación solo se hace sobre un contrato ya registrado: revisa el "
            "código, o crea primero el registro.",
        )

    # ── Fila base: la versión que esta modificación releva ──
    if data.proyecto_saliente_id is not None:
        base = next((a for a in activos if a.proyecto_id == data.proyecto_saliente_id), None)
        if base is None:
            raise HTTPException(
                422,
                f"La planta indicada como saliente no está inscrita en el SIC \"{sic}\" al "
                f"{_fmt_fecha(data.fecha_entrada)}. Plantas inscritas: {_listado_plantas(db, activos)}.",
            )
    elif len(activos) == 1:
        base = activos[0]
    else:
        base = next(
            (a for a in activos if data.proyecto_id is not None and a.proyecto_id == data.proyecto_id),
            None,
        )
        if base is None:
            raise HTTPException(
                422,
                f"El SIC \"{sic}\" tiene {len(activos)} plantas inscritas a la vez "
                f"({_listado_plantas(db, activos)}). Indica cuál de ellas modifica esta "
                "solicitud (proyecto_saliente_id): de lo contrario no se sabe a cuál releva.",
            )

    # ── Lo modificable. Ausente = se hereda de la versión vigente ──
    proyecto_id = data.proyecto_id if data.proyecto_id is not None else base.proyecto_id
    fecha_fin = data.fecha_fin if data.fecha_fin is not None else base.fecha_fin
    porcentaje = data.porcentaje_despacho if data.porcentaje_despacho is not None else base.porcentaje_despacho

    if data.porcentaje_despacho is not None and not 0 <= data.porcentaje_despacho <= 1:
        raise HTTPException(
            422,
            "El % de despacho se almacena como fracción 0-1 (0.85 = 85%). "
            f"Se recibió {data.porcentaje_despacho}: un valor fuera de escala rompe el "
            "cálculo de Cumplimiento (generación × porcentaje_despacho).",
        )

    cambia_planta = proyecto_id != base.proyecto_id
    if cambia_planta:
        if proyecto_id is not None and not db.query(Proyecto.id).filter(Proyecto.id == proyecto_id).first():
            raise HTTPException(404, f"La planta {proyecto_id} no existe.")
        ya_inscrita = next((a for a in activos if a.proyecto_id == proyecto_id and a.id != base.id), None)
        if ya_inscrita is not None:
            raise HTTPException(
                422,
                f"{_nombre_planta(db, proyecto_id)} ya está inscrita en el SIC \"{sic}\". "
                "Para cambiarle el % o la fecha, modifica esa planta directamente.",
            )

    # La modalidad es de la planta, no del contrato: una planta nueva que no la
    # declara entra como normal; si la planta no cambia, se conserva la suya.
    if data.modalidad is not None and data.modalidad not in MODALIDADES_SUMINISTRO:
        raise HTTPException(
            422,
            f"Modalidad de suministro inválida: \"{data.modalidad}\". "
            f"Opciones: {', '.join(MODALIDADES_SUMINISTRO)}.",
        )
    if data.modalidad is None:
        es_duplicado = bool(base.es_duplicado) and not cambia_planta
        uso_del_recurso = bool(base.uso_del_recurso) and not cambia_planta
    else:
        es_duplicado = data.modalidad == "duplicado"
        uso_del_recurso = data.modalidad == "uso_recurso"

    # ── Validaciones de vigencia ──
    if base.fecha_inicio is not None and data.fecha_entrada <= base.fecha_inicio:
        raise HTTPException(
            422,
            f"La modificación entraría en vigencia el {_fmt_fecha(data.fecha_entrada)}, pero la "
            f"versión que modifica arranca el {_fmt_fecha(base.fecha_inicio)}. La fecha de "
            "entrada tiene que ser posterior al inicio de la versión vigente.",
        )
    if fecha_fin is not None and data.fecha_entrada > fecha_fin:
        raise HTTPException(
            422,
            f"La fecha de entrada ({_fmt_fecha(data.fecha_entrada)}) es posterior a la fecha de "
            f"fin ({_fmt_fecha(fecha_fin)}): la modificación nacería vencida.",
        )

    requerimiento = (data.requerimiento_asic or "").strip()
    if not requerimiento:
        raise HTTPException(422, "El número de requerimiento ASIC de la modificación es obligatorio.")
    if base.requerimiento_asic and requerimiento == base.requerimiento_asic.strip():
        raise HTTPException(
            422,
            f"El requerimiento \"{requerimiento}\" es el mismo de la versión vigente. Cada "
            "modificación se radica ante XM con un requerimiento nuevo (el código SIC sí se conserva).",
        )

    try:
        estado = EstadoSolicitudAsicEnum(data.estado_solicitud)
    except ValueError:
        raise HTTPException(
            422,
            f"Estado inválido: \"{data.estado_solicitud}\". "
            f"Opciones: {', '.join(e.value for e in EstadoSolicitudAsicEnum)}.",
        )

    nueva = AsicSolicitud(
        tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
        estado_solicitud=estado,
        requerimiento_asic=requerimiento,
        fecha_solicitud=data.fecha_solicitud or date.today(),
        fecha_inicio=data.fecha_entrada,
        fecha_fin=fecha_fin,
        proyecto_id=proyecto_id,
        porcentaje_despacho=porcentaje,
        es_duplicado=es_duplicado,
        uso_del_recurso=uso_del_recurso,
        link_archivo=data.link_archivo,
        observaciones=data.observaciones,
        **{campo: getattr(base, campo) for campo in _CAMPOS_HEREDADOS},
    )

    otras_plantas = [a for a in activos if a.id != base.id]
    saliente: AsicSolicitud | None = None
    if not cambia_planta:
        # Supersesión en sitio: el resolutor recorta la versión anterior de esta
        # misma planta. Se conserva su flag para no alterar la coexistencia que
        # la planta ya tenía dentro del SIC.
        nueva.reemplaza_anterior = bool(base.reemplaza_anterior)
    elif not otras_plantas:
        # Relevo limpio (el caso normal: una sola planta en el SIC). No se toca
        # la fila vieja: gescon_vigencia la recorta a fecha_entrada − 1.
        nueva.reemplaza_anterior = True
    else:
        # El SIC tiene más plantas inscritas: un relevo global se las llevaría
        # por delante. La nueva entra coexistiendo y se cierra SOLO la que sale.
        nueva.reemplaza_anterior = False
        corte = data.fecha_entrada - timedelta(days=1)
        if base.fecha_fin is None or base.fecha_fin > corte:
            base.fecha_fin = corte
        saliente = base

    _validar_flags_exclusivos(es_duplicado, uso_del_recurso)
    try:
        db.add(nueva)
        db.flush()
        _validar_fecha_fin_vs_ppa(db, nueva)
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    cambios = []
    if cambia_planta:
        cambios.append(f"sale {_nombre_planta(db, base.proyecto_id)} y entra {_nombre_planta(db, proyecto_id)}")
    if _pct(porcentaje) != _pct(base.porcentaje_despacho):
        viejo = "—" if _pct(base.porcentaje_despacho) is None else f"{_pct(base.porcentaje_despacho) * 100:g}%"
        nuevo = "—" if _pct(porcentaje) is None else f"{_pct(porcentaje) * 100:g}%"
        cambios.append(f"despacho {viejo} → {nuevo}")
    if fecha_fin != base.fecha_fin:
        cambios.append(f"fin {_fmt_fecha(base.fecha_fin)} → {_fmt_fecha(fecha_fin)}")
    if not cambios:
        cambios.append("sin cambios de planta, % ni fecha de fin")
    resumen = f"Desde el {_fmt_fecha(data.fecha_entrada)}: " + "; ".join(cambios) + "."

    filas = [nueva] if saliente is None else [nueva, saliente]
    outs = _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(f) for f in filas]))
    return AsicModificacionOut(
        modificacion=outs[0],
        saliente=outs[1] if saliente is not None else None,
        resumen=resumen,
    )


# ── Terminación de un contrato ya registrado ─────────────────────────────
# Misma dinámica que la modificación: se elige el SIC y la identidad del
# contrato se hereda. Lo que NO se hereda es la planta — ver docstring de
# AsicTerminacionCreate: guardar proyecto_id en una terminación hace que
# Cumplimiento borre la planta del mes en vez de prorratearla hasta la fecha.

_CAMPOS_HEREDADOS_TERMINACION = (
    "codigo_sic_contrato", "codigo_sic_vendedor", "codigo_sic_comprador",
    "contrato_interno", "nombre_interno", "prioridad_limitacion",
    "tipo_mercado", "tipo_asignacion", "contrato_ppa_id",
)


@router.post("/terminacion", response_model=AsicTerminacionOut, status_code=201)
def create_terminacion(
    data: AsicTerminacionCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Registra la terminación de un contrato GESCON heredando su identidad.

    Solo pide lo que XM exige (SIC, fecha, requerimiento, cédulas, soporte). Al
    publicarla, `_auto_terminate` estampa la fecha de fin en los registros
    vigentes del mismo SIC: Cumplimiento los prorratea HASTA esa fecha y los
    excluye después, dejando el histórico previo intacto.
    """
    sic = (data.codigo_sic_contrato or "").strip()
    if not sic:
        raise HTTPException(422, "El código SIC del contrato a terminar es obligatorio.")

    activos = _versiones_vigentes_sic(db, sic, en_fecha=data.fecha_terminacion)
    if not activos:
        raise HTTPException(
            404,
            f"No hay ningún registro publicado y vigente con el código SIC \"{sic}\". "
            "Revisa el código: una terminación se radica sobre un contrato registrado.",
        )

    # La identidad es del contrato, no de una planta: sirve cualquier versión
    # vigente del SIC, prefiriendo una que sí tenga el contrato interno.
    base = next((a for a in activos if (a.contrato_interno or "").strip()), activos[0])

    inicios = [a.fecha_inicio for a in activos if a.fecha_inicio is not None]
    if inicios and data.fecha_terminacion < min(inicios):
        raise HTTPException(
            422,
            f"La fecha de terminación ({_fmt_fecha(data.fecha_terminacion)}) es anterior al "
            f"inicio del contrato ({_fmt_fecha(min(inicios))}).",
        )

    requerimiento = (data.requerimiento_asic or "").strip() or None
    if requerimiento and base.requerimiento_asic and requerimiento == base.requerimiento_asic.strip():
        raise HTTPException(
            422,
            f"El requerimiento \"{requerimiento}\" es el mismo del registro vigente. El código "
            "SIC sí se conserva, pero la terminación se radica con un requerimiento propio.",
        )

    try:
        estado = EstadoSolicitudAsicEnum(data.estado_solicitud)
    except ValueError:
        raise HTTPException(
            422,
            f"Estado inválido: \"{data.estado_solicitud}\". "
            f"Opciones: {', '.join(e.value for e in EstadoSolicitudAsicEnum)}.",
        )

    nueva = AsicSolicitud(
        tipo_solicitud=TipoSolicitudAsicEnum.terminacion,
        estado_solicitud=estado,
        requerimiento_asic=requerimiento,
        fecha_solicitud=data.fecha_solicitud or date.today(),
        fecha_inicio=None,
        fecha_fin=data.fecha_terminacion,
        proyecto_id=None,  # deliberado: ver docstring de AsicTerminacionCreate
        # Las cédulas son de la radicación; si no vienen, se toman del registro.
        cedula_agente_vendedor=data.cedula_agente_vendedor or base.cedula_agente_vendedor,
        cedula_agente_comprador=data.cedula_agente_comprador or base.cedula_agente_comprador,
        link_archivo=data.link_archivo,
        observaciones=data.observaciones,
        reemplaza_anterior=True,
        es_duplicado=False,
        uso_del_recurso=False,
        **{campo: getattr(base, campo) for campo in _CAMPOS_HEREDADOS_TERMINACION},
    )

    try:
        db.add(nueva)
        db.flush()
        _validar_fecha_fin_vs_ppa(db, nueva)
        cerrados = _auto_terminate(db, nueva)
        db.commit()
    except HTTPException:
        db.rollback()
        raise

    etiqueta = base.contrato_interno or base.nombre_interno or f"SIC {sic}"
    if cerrados:
        plantas = ", ".join(sorted({_nombre_planta(db, c.proyecto_id) for c in cerrados}))
        detalle = f"se cerró la vigencia de {len(cerrados)} registro(s): {plantas}"
    else:
        detalle = (
            "no había registros vigentes que cerrar"
            if estado == EstadoSolicitudAsicEnum.publicado
            else "queda en borrador: no cierra nada hasta que se publique"
        )
    resumen = (
        f"{etiqueta} (SIC {sic}) termina el {_fmt_fecha(data.fecha_terminacion)}; {detalle}."
    )

    outs = _aplicar_vigencia(db, _enriquecer_planta(db, [_to_out(f) for f in [nueva, *cerrados]]))
    return AsicTerminacionOut(terminacion=outs[0], cerrados=outs[1:], resumen=resumen)


@router.delete("/{id}", status_code=204)
def delete_solicitud(
    id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    s = db.query(AsicSolicitud).filter(AsicSolicitud.id == id).first()
    if not s:
        raise HTTPException(404, "Registro GESCON no encontrado")

    razones = []

    n_cambios = (
        db.query(AsicCambioContrato)
        .filter(AsicCambioContrato.solicitud_id == id)
        .count()
    )
    if n_cambios:
        razones.append(f"Tiene {n_cambios} cambio(s) de contrato asociados")

    # Las terminaciones quedan exentas del bloqueo por cumplimiento: la regla
    # protege filas cuya energía alimenta el cálculo, y una terminación no
    # aporta ninguna (Cumplimiento la salta). Sin la exención serían
    # imposibles de borrar desde que heredan `contrato_interno`, y radicar una
    # terminación equivocada dejaría de tener arreglo desde la vista.
    # Ojo: borrar la terminación NO devuelve la fecha_fin que estampó en los
    # registros del SIC — eso se corrige editando cada registro.
    if s.tipo_solicitud == TipoSolicitudAsicEnum.terminacion:
        pass  # exenta: ver comentario arriba
    elif s.contrato_ppa_id:
        n_cumpl = (
            db.query(CumplimientoMensual)
            .filter(CumplimientoMensual.contrato_ppa_id == s.contrato_ppa_id)
            .count()
        )
        if n_cumpl:
            ppa = db.query(PPAContrato).filter(PPAContrato.id == s.contrato_ppa_id).first()
            nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}" if ppa else f"ID {s.contrato_ppa_id}"
            razones.append(f"Vinculado al contrato PPA \"{nombre_ppa}\" que tiene {n_cumpl} registro(s) de cumplimiento")
    elif s.contrato_interno:
        ppa = (
            db.query(PPAContrato)
            .filter(
                PPAContrato.numero_codigo_contrato == s.contrato_interno,
                PPAContrato.deleted_at.is_(None),
            )
            .first()
        )
        if ppa:
            n_cumpl = (
                db.query(CumplimientoMensual)
                .filter(CumplimientoMensual.contrato_ppa_id == ppa.id)
                .count()
            )
            if n_cumpl:
                nombre_ppa = ppa.nombre_interno or ppa.numero_codigo_contrato or f"ID {ppa.id}"
                razones.append(f"Vinculado al contrato PPA \"{nombre_ppa}\" que tiene {n_cumpl} registro(s) de cumplimiento")

    if razones:
        raise HTTPException(409, f"No se puede eliminar: {'; '.join(razones)}.")

    db.delete(s)
    db.commit()


def _resolver_ppa_para(s: AsicSolicitud, db: Session) -> PPAContrato | None:
    """Contrato PPA canónico de un registro GESCON: por FK contrato_ppa_id, o si no,
    casando el código `contrato_interno` con `numero_codigo_contrato` (no borrado)."""
    if s.contrato_ppa_id:
        return (
            db.query(PPAContrato)
            .filter(PPAContrato.id == s.contrato_ppa_id, PPAContrato.deleted_at.is_(None))
            .first()
        )
    if s.contrato_interno and s.contrato_interno.strip():
        return (
            db.query(PPAContrato)
            .filter(
                PPAContrato.numero_codigo_contrato == s.contrato_interno,
                PPAContrato.deleted_at.is_(None),
            )
            .first()
        )
    return None


@router.post("/backfill-nombre-interno")
def backfill_nombre_interno(
    dry_run: bool = Query(True, description="true (default): solo reporta, no modifica."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Completa `nombre_interno` en registros GESCON que lo tienen vacío, copiándolo del
    contrato PPA al que pertenecen (nombre real, "alusivo al contrato específico"). De paso
    vincula `contrato_ppa_id` si faltaba. No inventa nombres: los que no tienen PPA con
    nombre se reportan sin tocar. Idempotente. `dry_run=false` aplica en una transacción."""
    faltantes = (
        db.query(AsicSolicitud)
        .filter(
            or_(AsicSolicitud.nombre_interno.is_(None), func.trim(AsicSolicitud.nombre_interno) == ""),
            or_(
                AsicSolicitud.contrato_ppa_id.isnot(None),
                and_(AsicSolicitud.contrato_interno.isnot(None), func.trim(AsicSolicitud.contrato_interno) != ""),
            ),
        )
        .all()
    )

    resueltos, no_resueltos = [], []
    for s in faltantes:
        ppa = _resolver_ppa_para(s, db)
        nombre = (ppa.nombre_interno or "").strip() if ppa else ""
        if ppa and nombre:
            resueltos.append({
                "id": s.id,
                "contrato_interno": s.contrato_interno,
                "nombre_propuesto": nombre,
                "vincula_ppa_id": (ppa.id if not s.contrato_ppa_id else None),
            })
        else:
            no_resueltos.append({
                "id": s.id,
                "contrato_interno": s.contrato_interno,
                "motivo": "sin PPA que casar" if not ppa else "el PPA no tiene nombre_interno",
            })

    reporte = {
        "dry_run": dry_run,
        "total_sin_nombre": len(faltantes),
        "a_actualizar": len(resueltos),
        "sin_resolver": len(no_resueltos),
        "resueltos": resueltos,
        "no_resueltos": no_resueltos,
    }
    if dry_run:
        return reporte

    try:
        for r in resueltos:
            s = db.query(AsicSolicitud).filter(AsicSolicitud.id == r["id"]).first()
            if not s:
                continue
            s.nombre_interno = r["nombre_propuesto"]
            if r["vincula_ppa_id"] and not s.contrato_ppa_id:
                s.contrato_ppa_id = r["vincula_ppa_id"]
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"El backfill falló y se revirtió: {type(e).__name__}: {e}")

    reporte["ejecutado"] = True
    return reporte


@router.post("/backfill-terminaciones")
def backfill_terminaciones(
    dry_run: bool = Query(True, description="true (default): solo reporta, no modifica."),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Completa la identidad de las terminaciones ya registradas.

    Hasta que existió POST /asic/terminacion, el formulario guardaba la
    terminación con SIC, fecha y cédulas y nada más: sin contrato interno ni
    nombre interno, así que salían en blanco en la tabla y en el Excel. Este
    backfill los rellena desde los registros del MISMO código SIC.

    NO toca `proyecto_id`: una terminación se guarda sin planta a propósito
    (con planta, Cumplimiento borra la planta del mes de la terminación en vez
    de prorratearla). Idempotente: solo llena campos vacíos.
    """
    campos = (
        "contrato_interno", "nombre_interno", "codigo_sic_vendedor",
        "codigo_sic_comprador", "tipo_mercado", "tipo_asignacion",
    )

    terminaciones = (
        db.query(AsicSolicitud)
        .filter(
            AsicSolicitud.tipo_solicitud == TipoSolicitudAsicEnum.terminacion,
            AsicSolicitud.codigo_sic_contrato.isnot(None),
        )
        .order_by(AsicSolicitud.id)
        .all()
    )

    # Fuente por SIC: los registros/modificaciones de ese contrato, del más
    # reciente al más viejo, para tomar el primero que tenga cada dato.
    sics = {t.codigo_sic_contrato for t in terminaciones}
    fuentes: dict[str, list[AsicSolicitud]] = {}
    if sics:
        for r in (
            db.query(AsicSolicitud)
            .filter(
                AsicSolicitud.codigo_sic_contrato.in_(sics),
                AsicSolicitud.tipo_solicitud.in_([
                    TipoSolicitudAsicEnum.registro,
                    TipoSolicitudAsicEnum.modificacion,
                ]),
            )
            .order_by(AsicSolicitud.fecha_inicio.desc().nullslast(), AsicSolicitud.id.desc())
            .all()
        ):
            fuentes.setdefault(r.codigo_sic_contrato, []).append(r)

    resueltos, no_resueltos = [], []
    for t in terminaciones:
        candidatos = fuentes.get(t.codigo_sic_contrato, [])
        if not candidatos:
            no_resueltos.append({
                "id": t.id,
                "codigo_sic_contrato": t.codigo_sic_contrato,
                "motivo": "no hay registros con ese código SIC",
            })
            continue

        cambios = {}
        for campo in campos:
            if (getattr(t, campo) or "").strip():
                continue
            valor = next(
                (v for v in ((getattr(c, campo) or "").strip() for c in candidatos) if v),
                None,
            )
            if valor:
                cambios[campo] = valor
        if t.prioridad_limitacion is None:
            prio = next((c.prioridad_limitacion for c in candidatos if c.prioridad_limitacion is not None), None)
            if prio is not None:
                cambios["prioridad_limitacion"] = prio
        if t.contrato_ppa_id is None:
            ppa_id = next((c.contrato_ppa_id for c in candidatos if c.contrato_ppa_id), None)
            if ppa_id:
                cambios["contrato_ppa_id"] = ppa_id

        if cambios:
            resueltos.append({
                "id": t.id,
                "codigo_sic_contrato": t.codigo_sic_contrato,
                "fecha_fin": t.fecha_fin.isoformat() if t.fecha_fin else None,
                "cambios": cambios,
            })

    reporte = {
        "dry_run": dry_run,
        "total_terminaciones": len(terminaciones),
        "a_actualizar": len(resueltos),
        "sin_resolver": len(no_resueltos),
        "resueltos": resueltos,
        "no_resueltos": no_resueltos,
    }
    if dry_run:
        return reporte

    try:
        for r in resueltos:
            t = db.query(AsicSolicitud).filter(AsicSolicitud.id == r["id"]).first()
            if not t:
                continue
            for campo, valor in r["cambios"].items():
                setattr(t, campo, valor)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"El backfill falló y se revirtió: {type(e).__name__}: {e}")

    reporte["ejecutado"] = True
    return reporte


@router.post("/cambios", response_model=AsicCambioOut, status_code=201)
def create_cambio(
    data: AsicCambioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    obj = AsicCambioContrato(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/gescon/diccionario", response_model=list[GesconDiccionarioOut])
def list_diccionario(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(GesconDiccionario).order_by(GesconDiccionario.codigo_contrato).all()


@router.post("/gescon/diccionario", response_model=GesconDiccionarioOut, status_code=201)
def upsert_diccionario(
    data: GesconDiccionarioCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    existing = db.query(GesconDiccionario).filter_by(codigo_contrato=data.codigo_contrato).first()
    if existing:
        existing.nombre = data.nombre
        db.commit()
        db.refresh(existing)
        return existing
    obj = GesconDiccionario(**data.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
