from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera
from app.models.polizas import Poliza
from app.models.proyectos import Proyecto
from app.schemas.polizas import PolizaOut, PolizaUpsert

router = APIRouter(prefix="/polizas", tags=["Pólizas"])


def calcular_derivados(
    mano_obra: float | None,
    estructura: float | None,
    paneles: float | None,
    inversores: float | None,
    otros: float | None,
    ipp_base: float | None,
    ipp_provisional: float | None,
    tarifa_base: float | None,
    generacion_anual_p90_kwh: float | None,
) -> tuple[float | None, float | None]:
    """Recalcula valor_total_proyecto y valor_lucro_cesante a partir de sus
    insumos. Se llama siempre al guardar una póliza (PUT /polizas/{id}) para
    que ambos campos queden persistidos pero nunca desincronizados de sus
    insumos -- ver docs/superpowers/specs/2026-08-11-vista-polizas-design.md."""
    componentes = [c for c in (mano_obra, estructura, paneles, inversores, otros) if c is not None]
    valor_total_proyecto = sum(float(c) for c in componentes) if componentes else None

    valor_lucro_cesante = None
    if (
        ipp_base is not None and float(ipp_base) != 0
        and ipp_provisional is not None
        and tarifa_base is not None
        and generacion_anual_p90_kwh is not None
    ):
        tarifa_indexada = float(tarifa_base) * float(ipp_provisional) / float(ipp_base)
        valor_lucro_cesante = tarifa_indexada * float(generacion_anual_p90_kwh)

    return valor_total_proyecto, valor_lucro_cesante


def _num(v) -> float | None:
    return float(v) if v is not None else None


def _to_out(p: Proyecto, poliza: Poliza | None) -> PolizaOut:
    info = p.info_tecnica
    return PolizaOut(
        proyecto_id=p.id,
        nombre_comercial=p.nombre_comercial,
        tipo_proyecto=p.tipo_proyecto,
        municipio=p.municipio,
        departamento=p.departamento,
        direccion_vereda=p.direccion_vereda,
        marca_paneles=info.marca_paneles if info else None,
        cantidad_total_paneles=info.cantidad_total_paneles if info else None,
        marca_inversores=info.marca_inversores if info else None,
        cantidad_inversores=info.cantidad_inversores if info else None,
        capacidad_instalada_kwp=_num(info.capacidad_instalada_kwp) if info else None,
        operador_red=p.operador_red_legal,
        voltaje_red=info.voltaje_red if info else None,
        potencia_panel_kwp=info.potencia_panel_kwp if info else None,
        potencia_inversores_kwp=info.potencia_inversores_kwp if info else None,
        potencia_ac_kw=_num(info.potencia_ac_kw) if info else None,
        numero_poliza=poliza.numero_poliza if poliza else None,
        poliza_om=poliza.poliza_om if poliza else False,
        fecha_vencimiento=poliza.fecha_vencimiento if poliza else None,
        valor_poliza=_num(poliza.valor_poliza) if poliza else None,
        mano_obra=_num(poliza.mano_obra) if poliza else None,
        estructura=_num(poliza.estructura) if poliza else None,
        paneles=_num(poliza.paneles) if poliza else None,
        inversores=_num(poliza.inversores) if poliza else None,
        otros=_num(poliza.otros) if poliza else None,
        valor_total_proyecto=_num(poliza.valor_total_proyecto) if poliza else None,
        link_estudio_suelos=poliza.link_estudio_suelos if poliza else None,
        ipp_base=_num(poliza.ipp_base) if poliza else None,
        ipp_base_fecha=poliza.ipp_base_fecha if poliza else None,
        ipp_provisional=_num(poliza.ipp_provisional) if poliza else None,
        ipp_provisional_fecha=poliza.ipp_provisional_fecha if poliza else None,
        tarifa_base=_num(poliza.tarifa_base) if poliza else None,
        generacion_anual_p90_kwh=_num(poliza.generacion_anual_p90_kwh) if poliza else None,
        valor_lucro_cesante=_num(poliza.valor_lucro_cesante) if poliza else None,
        updated_at=poliza.updated_at if poliza else None,
    )


@router.get("", response_model=list[PolizaOut])
def listar(
    search: str | None = Query(None),
    tipo_proyecto: str | None = Query(None),
    poliza_om: bool | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = (
        db.query(Proyecto, Poliza)
        .outerjoin(Poliza, Poliza.proyecto_id == Proyecto.id)
        .options(
            selectinload(Proyecto.info_tecnica),
            selectinload(Proyecto.operador),
            selectinload(Proyecto.fronteras).selectinload(Frontera.operador),
        )
        .filter(Proyecto.deleted_at.is_(None))
    )
    if search:
        like = f"%{search}%"
        q = q.filter(
            Proyecto.nombre_comercial.ilike(like)
            | Proyecto.municipio.ilike(like)
            | Proyecto.departamento.ilike(like)
        )
    if tipo_proyecto:
        q = q.filter(Proyecto.tipo_proyecto == tipo_proyecto)
    if poliza_om is not None:
        q = q.filter(Poliza.poliza_om == poliza_om)
    rows = q.order_by(Proyecto.nombre_comercial).all()
    return [_to_out(p, poliza) for p, poliza in rows]


@router.put("/{proyecto_id}", response_model=PolizaOut)
def guardar(
    proyecto_id: int,
    body: PolizaUpsert,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    proyecto = (
        db.query(Proyecto)
        .options(
            selectinload(Proyecto.info_tecnica),
            selectinload(Proyecto.operador),
            selectinload(Proyecto.fronteras).selectinload(Frontera.operador),
        )
        .filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None))
        .first()
    )
    if not proyecto:
        raise HTTPException(404, "Proyecto no encontrado")

    poliza = db.query(Poliza).filter(Poliza.proyecto_id == proyecto_id).first()
    if not poliza:
        poliza = Poliza(proyecto_id=proyecto_id)
        db.add(poliza)

    for field, val in body.model_dump().items():
        setattr(poliza, field, val)

    poliza.valor_total_proyecto, poliza.valor_lucro_cesante = calcular_derivados(
        poliza.mano_obra, poliza.estructura, poliza.paneles, poliza.inversores, poliza.otros,
        poliza.ipp_base, poliza.ipp_provisional, poliza.tarifa_base, poliza.generacion_anual_p90_kwh,
    )

    db.commit()
    db.refresh(poliza)
    db.refresh(proyecto)
    return _to_out(proyecto, poliza)
