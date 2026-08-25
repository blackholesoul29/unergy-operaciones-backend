"""API del módulo "Retos Q" — tablero trimestral compartido del equipo.

El router solo orquesta: consulta, delega el cálculo en `app/services/retos.py`
y arma el schema. Contrato normativo: CONTRATO_RETOS_Q.md sección 5.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models.usuarios import Usuario
from app.models.retos import RetoTrimestre, RetoMetrica, RetoValorSemanal
from app.schemas.retos import (
    MetricaCreate, MetricaResumen, MetricaUpdate, RetoDetalle, RetoResumen,
    RetoUpdate, RetosAnioOut, SemanaOut, SeriePunto, ValorCelda, ValorSemanalIn,
)
from app.services import retos as svc

router = APIRouter(prefix="/retos", tags=["Retos trimestrales"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validar_catalogos(tipo_agregacion: str | None, direccion: str | None) -> None:
    if tipo_agregacion is not None and tipo_agregacion not in svc.TIPOS_AGREGACION:
        raise HTTPException(
            400, f"tipo_agregacion inválido. Valores permitidos: {', '.join(svc.TIPOS_AGREGACION)}"
        )
    if direccion is not None and direccion not in svc.DIRECCIONES:
        raise HTTPException(
            400, f"direccion inválida. Valores permitidos: {', '.join(svc.DIRECCIONES)}"
        )


def _clamp_decimales(valor: int | None) -> int | None:
    if valor is None:
        return None
    return max(0, min(4, int(valor)))


def _armar_metrica(m: RetoMetrica, semanas: list[dict], corridas: int) -> MetricaResumen:
    """MetricaResumen con consolidado, meta esperada, estado y serie completa."""
    por_lunes = {v.semana_inicio: v for v in m.valores}
    serie: list[SeriePunto] = []
    ordenados: list[float | None] = []
    con_dato = 0
    for s in semanas:
        fila = por_lunes.get(s["inicio"])
        val = float(fila.valor) if (fila is not None and fila.valor is not None) else None
        if val is not None:
            con_dato += 1
        ordenados.append(val)
        serie.append(SeriePunto(semana=s["numero"], valor=svc.redondear(val)))

    meta = float(m.meta) if m.meta is not None else None
    consolidado = svc.consolidar(ordenados, m.tipo_agregacion)
    esperada = svc.meta_esperada(meta, m.tipo_agregacion, corridas, len(semanas))
    return MetricaResumen(
        id=m.id,
        reto_id=m.reto_id,
        nombre=m.nombre,
        descripcion=m.descripcion,
        unidad=m.unidad,
        meta=svc.redondear(meta),
        tipo_agregacion=m.tipo_agregacion,
        direccion=m.direccion,
        decimales=m.decimales,
        responsable=m.responsable,
        orden=m.orden,
        activa=m.activa,
        consolidado=svc.redondear(consolidado),
        meta_esperada=svc.redondear(esperada),
        avance_pct=svc.redondear(svc.avance_pct(consolidado, meta), 1),
        cumplimiento_pct=svc.redondear(
            svc.cumplimiento_pct(consolidado, esperada, m.direccion), 1
        ),
        estado=svc.clasificar_estado(consolidado, esperada, m.direccion),
        semanas_con_dato=con_dato,
        serie=serie,
    )


def _armar_reto(reto: RetoTrimestre, hoy: date | None = None) -> tuple[RetoResumen, list[dict]]:
    """RetoResumen + las semanas generadas (reusadas por el detalle)."""
    hoy = hoy or date.today()
    semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, hoy)
    corridas = svc.semanas_transcurridas(semanas, reto.fecha_inicio, reto.fecha_fin, hoy)
    metricas = [_armar_metrica(m, semanas, corridas) for m in reto.metricas]

    activas = [m for m in metricas if m.activa]
    semanas_con_datos = 0
    for idx in range(len(semanas)):
        if any(m.serie[idx].valor is not None for m in activas):
            semanas_con_datos += 1

    resumen = RetoResumen(
        id=reto.id,
        anio=reto.anio,
        trimestre=reto.trimestre,
        nombre=reto.nombre,
        descripcion=reto.descripcion,
        fecha_inicio=reto.fecha_inicio,
        fecha_fin=reto.fecha_fin,
        total_semanas=len(semanas),
        semana_actual=svc.numero_semana_actual(semanas, reto.fecha_inicio, reto.fecha_fin, hoy),
        estado_periodo=svc.estado_periodo(reto.fecha_inicio, reto.fecha_fin, hoy),
        total_metricas=len(activas),
        semanas_con_datos=semanas_con_datos,
        avance_global_pct=svc.redondear(
            svc.promedio_cumplimiento([m.cumplimiento_pct for m in activas]), 1
        ),
        metricas=metricas,
    )
    return resumen, semanas


def _armar_detalle(reto: RetoTrimestre, hoy: date | None = None) -> RetoDetalle:
    resumen, semanas = _armar_reto(reto, hoy)
    lunes_validos = {s["inicio"] for s in semanas}

    valores: dict[str, dict[str, ValorCelda]] = {}
    for m in reto.metricas:
        celdas: dict[str, ValorCelda] = {}
        for v in m.valores:
            if v.semana_inicio not in lunes_validos:
                continue  # valor anclado fuera del rango actual del Q: no se muestra
            celdas[v.semana_inicio.isoformat()] = ValorCelda(
                valor=svc.redondear(float(v.valor)) if v.valor is not None else None,
                nota=v.nota,
                actualizado_por=v.actualizado_por.nombre if v.actualizado_por else None,
                updated_at=v.updated_at,
            )
        # Siempre se publica la clave de la métrica (aunque no tenga datos) para
        # que el front pueda indexar valores[metrica_id][semana] sin comprobar.
        valores[str(m.id)] = celdas

    return RetoDetalle(
        **resumen.model_dump(),
        semanas=[SemanaOut(**s) for s in semanas],
        valores=valores,
    )


def _cargar_reto(db: Session, reto_id: int) -> RetoTrimestre:
    reto = db.execute(
        select(RetoTrimestre)
        .options(
            selectinload(RetoTrimestre.metricas)
            .selectinload(RetoMetrica.valores)
            .selectinload(RetoValorSemanal.actualizado_por)
        )
        .where(RetoTrimestre.id == reto_id)
    ).scalars().first()
    if not reto:
        raise HTTPException(404, "Reto no encontrado")
    return reto


def _cargar_metrica(db: Session, metrica_id: int) -> RetoMetrica:
    metrica = db.execute(
        select(RetoMetrica)
        .options(selectinload(RetoMetrica.valores))
        .where(RetoMetrica.id == metrica_id)
    ).scalars().first()
    if not metrica:
        raise HTTPException(404, "Métrica no encontrada")
    return metrica


def _metrica_recalculada(db: Session, metrica: RetoMetrica) -> MetricaResumen:
    reto = db.get(RetoTrimestre, metrica.reto_id)
    hoy = date.today()
    semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, hoy)
    corridas = svc.semanas_transcurridas(semanas, reto.fecha_inicio, reto.fecha_fin, hoy)
    return _armar_metrica(metrica, semanas, corridas)


def _asegurar_trimestres(db: Session, anio: int) -> None:
    """Autocrea los 4 trimestres calendario del año si faltan."""
    existentes = {
        t for (t,) in db.execute(
            select(RetoTrimestre.trimestre).where(RetoTrimestre.anio == anio)
        ).all()
    }
    faltantes = [q for q in (1, 2, 3, 4) if q not in existentes]
    if not faltantes:
        return
    for q in faltantes:
        inicio, fin = svc.rango_trimestre(anio, q)
        db.add(RetoTrimestre(
            anio=anio, trimestre=q, nombre=svc.nombre_trimestre(anio, q),
            fecha_inicio=inicio, fecha_fin=fin,
        ))
    try:
        db.commit()
    except IntegrityError:
        # Otro request creó los mismos trimestres en paralelo: no es un error.
        db.rollback()


def _validar_rango(fecha_inicio: date, fecha_fin: date) -> None:
    if fecha_fin <= fecha_inicio:
        raise HTTPException(400, "La fecha de fin debe ser posterior a la de inicio")
    if svc.contar_semanas(fecha_inicio, fecha_fin) > svc.TOPE_SEMANAS:
        raise HTTPException(400, "El rango no puede superar 60 semanas")


# ---------------------------------------------------------------------------
# Listado por año
# ---------------------------------------------------------------------------

@router.get("", response_model=RetosAnioOut)
def listar_retos(anio: int | None = None, db: Session = Depends(get_db),
                 _=Depends(get_current_user)):
    anio = anio or date.today().year
    _asegurar_trimestres(db, anio)

    retos = db.execute(
        select(RetoTrimestre)
        .options(selectinload(RetoTrimestre.metricas).selectinload(RetoMetrica.valores))
        .where(RetoTrimestre.anio == anio)
        .order_by(RetoTrimestre.trimestre)
    ).scalars().all()

    anios = {a for (a,) in db.execute(select(RetoTrimestre.anio).distinct()).all()}
    anios.update({anio - 1, anio, anio + 1})

    hoy = date.today()
    return RetosAnioOut(
        anio=anio,
        anios_disponibles=sorted(anios),
        retos=[_armar_reto(r, hoy)[0] for r in retos],
    )


# ---------------------------------------------------------------------------
# Métricas (declaradas antes de /{id} para que "metricas" no se lea como id)
# ---------------------------------------------------------------------------

@router.patch("/metricas/{metrica_id}", response_model=MetricaResumen)
def actualizar_metrica(metrica_id: int, data: MetricaUpdate,
                       db: Session = Depends(get_db),
                       current: Usuario = Depends(get_current_user)):
    metrica = _cargar_metrica(db, metrica_id)
    cambios = data.model_dump(exclude_unset=True)
    _validar_catalogos(cambios.get("tipo_agregacion"), cambios.get("direccion"))
    if "decimales" in cambios:
        cambios["decimales"] = _clamp_decimales(cambios["decimales"])
    for campo, valor in cambios.items():
        if valor is None and campo in ("nombre", "tipo_agregacion", "direccion",
                                       "decimales", "orden", "activa"):
            continue  # campos NOT NULL: un null explícito se ignora
        setattr(metrica, campo, valor)
    db.commit()
    db.refresh(metrica)
    return _metrica_recalculada(db, metrica)


@router.delete("/metricas/{metrica_id}", status_code=204)
def eliminar_metrica(metrica_id: int, db: Session = Depends(get_db),
                     current: Usuario = Depends(get_current_user)):
    metrica = _cargar_metrica(db, metrica_id)
    db.delete(metrica)
    db.commit()


@router.put("/metricas/{metrica_id}/valores/{semana_inicio}", response_model=MetricaResumen)
def guardar_valor(metrica_id: int, semana_inicio: date, data: ValorSemanalIn,
                  db: Session = Depends(get_db),
                  current: Usuario = Depends(get_current_user)):
    metrica = _cargar_metrica(db, metrica_id)
    if semana_inicio.weekday() != 0:
        raise HTTPException(400, "La semana debe empezar en lunes")

    reto = db.get(RetoTrimestre, metrica.reto_id)
    hoy = date.today()
    semanas = svc.generar_semanas(reto.fecha_inicio, reto.fecha_fin, hoy)
    if semana_inicio not in {s["inicio"] for s in semanas}:
        raise HTTPException(400, "La semana está fuera del rango del trimestre")

    fila = db.execute(
        select(RetoValorSemanal).where(
            RetoValorSemanal.metrica_id == metrica_id,
            RetoValorSemanal.semana_inicio == semana_inicio,
        )
    ).scalars().first()
    if fila is None:
        fila = RetoValorSemanal(metrica_id=metrica_id, semana_inicio=semana_inicio)
        db.add(fila)
    fila.valor = data.valor
    fila.nota = data.nota
    fila.actualizado_por_id = getattr(current, "id", None)
    db.commit()

    db.refresh(metrica)
    corridas = svc.semanas_transcurridas(semanas, reto.fecha_inicio, reto.fecha_fin, hoy)
    return _armar_metrica(metrica, semanas, corridas)


# ---------------------------------------------------------------------------
# Trimestre
# ---------------------------------------------------------------------------

@router.get("/{id}", response_model=RetoDetalle)
def obtener_reto(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    return _armar_detalle(_cargar_reto(db, id))


@router.patch("/{id}", response_model=RetoDetalle)
def actualizar_reto(id: int, data: RetoUpdate, db: Session = Depends(get_db),
                    current: Usuario = Depends(get_current_user)):
    reto = _cargar_reto(db, id)
    cambios = data.model_dump(exclude_unset=True)

    nuevo_inicio = cambios.get("fecha_inicio") or reto.fecha_inicio
    nuevo_fin = cambios.get("fecha_fin") or reto.fecha_fin
    if "fecha_inicio" in cambios or "fecha_fin" in cambios:
        _validar_rango(nuevo_inicio, nuevo_fin)

    for campo, valor in cambios.items():
        if valor is None and campo in ("fecha_inicio", "fecha_fin"):
            continue  # campos NOT NULL: un null explícito se ignora
        setattr(reto, campo, valor)
    db.commit()
    db.refresh(reto)
    return _armar_detalle(reto)


@router.post("/{id}/metricas", response_model=MetricaResumen, status_code=201)
def crear_metrica(id: int, data: MetricaCreate, db: Session = Depends(get_db),
                  current: Usuario = Depends(get_current_user)):
    reto = db.get(RetoTrimestre, id)
    if not reto:
        raise HTTPException(404, "Reto no encontrado")
    _validar_catalogos(data.tipo_agregacion, data.direccion)

    orden = data.orden
    if orden is None:
        maximo = db.execute(
            select(RetoMetrica.orden).where(RetoMetrica.reto_id == id)
            .order_by(RetoMetrica.orden.desc()).limit(1)
        ).scalars().first()
        orden = (maximo + 1) if maximo is not None else 0

    metrica = RetoMetrica(
        reto_id=id,
        nombre=data.nombre,
        descripcion=data.descripcion,
        unidad=data.unidad,
        meta=data.meta,
        tipo_agregacion=data.tipo_agregacion,
        direccion=data.direccion,
        decimales=_clamp_decimales(data.decimales if data.decimales is not None else 0),
        responsable=data.responsable,
        orden=orden,
        activa=True,
    )
    db.add(metrica)
    db.commit()
    db.refresh(metrica)
    return _metrica_recalculada(db, metrica)


@router.post("/{id}/metricas/copiar-desde/{origen_id}", response_model=list[MetricaResumen])
def copiar_metricas(id: int, origen_id: int, db: Session = Depends(get_db),
                    current: Usuario = Depends(get_current_user)):
    if origen_id == id:
        raise HTTPException(400, "El reto de origen debe ser distinto al de destino")
    destino = db.get(RetoTrimestre, id)
    if not destino:
        raise HTTPException(404, "Reto no encontrado")
    origen = db.get(RetoTrimestre, origen_id)
    if not origen:
        raise HTTPException(404, "Reto de origen no encontrado")

    existentes = {
        (n or "").strip().lower()
        for (n,) in db.execute(
            select(RetoMetrica.nombre).where(RetoMetrica.reto_id == id)
        ).all()
    }
    origenes = db.execute(
        select(RetoMetrica)
        .where(RetoMetrica.reto_id == origen_id, RetoMetrica.activa.is_(True))
        .order_by(RetoMetrica.orden, RetoMetrica.id)
    ).scalars().all()

    creadas: list[RetoMetrica] = []
    for m in origenes:
        clave = (m.nombre or "").strip().lower()
        if clave in existentes:
            continue
        existentes.add(clave)
        nueva = RetoMetrica(
            reto_id=id,
            nombre=m.nombre,
            descripcion=m.descripcion,
            unidad=m.unidad,
            meta=m.meta,
            tipo_agregacion=m.tipo_agregacion,
            direccion=m.direccion,
            decimales=m.decimales,
            responsable=m.responsable,
            orden=m.orden,
            activa=True,
        )
        db.add(nueva)
        creadas.append(nueva)
    db.commit()

    hoy = date.today()
    semanas = svc.generar_semanas(destino.fecha_inicio, destino.fecha_fin, hoy)
    corridas = svc.semanas_transcurridas(semanas, destino.fecha_inicio, destino.fecha_fin, hoy)
    salida = []
    for nueva in creadas:
        db.refresh(nueva)
        salida.append(_armar_metrica(nueva, semanas, corridas))
    return salida
