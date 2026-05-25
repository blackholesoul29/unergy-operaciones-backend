from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import GeneracionDiaria
from app.models.proyectos import Proyecto
from app.schemas.generacion import (
    GeneracionDiariaCreate, GeneracionDiariaUpdate, GeneracionDiariaOut,
    GeneracionDiariaBulkCreate, GeneracionDiariaBulkResult,
)
from app.schemas.common import PaginatedResponse
from app.utils.proyecto_matching import find_proyecto_by_name

router = APIRouter(prefix="/generacion", tags=["Generación"])


@router.get("", response_model=PaginatedResponse[GeneracionDiariaOut])
def list_generacion(
    proyecto_id: int | None = Query(None),
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(90, ge=1, le=1000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload
    q = db.query(GeneracionDiaria).options(selectinload(GeneracionDiaria.proyecto))
    if proyecto_id:
        q = q.filter(GeneracionDiaria.proyecto_id == proyecto_id)
    if fecha_inicio:
        q = q.filter(GeneracionDiaria.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.filter(GeneracionDiaria.fecha <= fecha_fin)
    total = q.count()
    items = q.order_by(GeneracionDiaria.fecha.desc()).offset((page - 1) * size).limit(size).all()
    return {"items": items, "total": total, "page": page, "size": size, "pages": -(-total // size)}


@router.post("", response_model=GeneracionDiariaOut, status_code=201)
def create_generacion(
    data: GeneracionDiariaCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload
    existing = db.query(GeneracionDiaria).filter(
        GeneracionDiaria.proyecto_id == data.proyecto_id,
        GeneracionDiaria.fecha == data.fecha,
    ).first()
    if existing:
        raise HTTPException(409, f"Ya existe un registro para proyecto {data.proyecto_id} en {data.fecha}. Usa PUT para actualizar.")
    row = GeneracionDiaria(**data.model_dump())
    db.add(row)
    db.commit()
    return db.query(GeneracionDiaria).options(selectinload(GeneracionDiaria.proyecto)).filter(GeneracionDiaria.id == row.id).first()


@router.put("/{id}", response_model=GeneracionDiariaOut)
def update_generacion(
    id: int,
    data: GeneracionDiariaUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload
    row = db.query(GeneracionDiaria).filter(GeneracionDiaria.id == id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    return db.query(GeneracionDiaria).options(selectinload(GeneracionDiaria.proyecto)).filter(GeneracionDiaria.id == id).first()


@router.delete("/{id}", status_code=204)
def delete_generacion(id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    row = db.query(GeneracionDiaria).filter(GeneracionDiaria.id == id).first()
    if not row:
        raise HTTPException(404, "Registro no encontrado")
    db.delete(row)
    db.commit()


@router.post("/bulk", response_model=GeneracionDiariaBulkResult)
def bulk_upsert_generacion(
    payload: GeneracionDiariaBulkCreate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Importación masiva. Usa proyecto_id si viene; si no, resuelve por nombre fuzzy.
    Con overwrite=True hace upsert; con overwrite=False omite duplicados."""
    proyectos_cache: dict[str, Proyecto | None] = {}
    insertados = actualizados = omitidos = 0
    errores: list[str] = []

    for item in payload.items:
        try:
            proyecto_id = item.proyecto_id
            if not proyecto_id:
                nombre = item.proyecto_nombre_externo or ""
                if nombre not in proyectos_cache:
                    proyectos_cache[nombre] = find_proyecto_by_name(db, nombre)
                proy = proyectos_cache[nombre]
                if not proy:
                    errores.append(f"No se encontró proyecto para '{nombre}' en {item.fecha}")
                    omitidos += 1
                    continue
                proyecto_id = proy.id

            existing = db.query(GeneracionDiaria).filter(
                GeneracionDiaria.proyecto_id == proyecto_id,
                GeneracionDiaria.fecha == item.fecha,
            ).first()

            if existing:
                if payload.overwrite:
                    for field in ("kwh_real", "kwh_p90", "kwh_autoconsumo", "fuente", "notas"):
                        val = getattr(item, field)
                        if val is not None:
                            setattr(existing, field, val)
                    actualizados += 1
                else:
                    omitidos += 1
            else:
                row = GeneracionDiaria(
                    proyecto_id=proyecto_id,
                    fecha=item.fecha,
                    kwh_real=item.kwh_real,
                    kwh_p90=item.kwh_p90,
                    kwh_autoconsumo=item.kwh_autoconsumo,
                    fuente=item.fuente,
                    notas=item.notas,
                )
                db.add(row)
                insertados += 1
        except Exception as e:
            errores.append(f"Error en {item.fecha}: {e}")
            omitidos += 1

    db.commit()
    return GeneracionDiariaBulkResult(
        insertados=insertados,
        actualizados=actualizados,
        omitidos=omitidos,
        errores=errores,
    )


@router.get("/resumen/por-proyecto", tags=["Generación"])
def resumen_por_proyecto(
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    q = db.query(
        GeneracionDiaria.proyecto_id,
        Proyecto.nombre_comercial,
        func.sum(GeneracionDiaria.kwh_real).label("total_kwh_real"),
        func.sum(GeneracionDiaria.kwh_p90).label("total_kwh_p90"),
        func.count(GeneracionDiaria.id).label("dias_con_dato"),
        func.min(GeneracionDiaria.fecha).label("fecha_inicio"),
        func.max(GeneracionDiaria.fecha).label("fecha_fin"),
    ).join(Proyecto, GeneracionDiaria.proyecto_id == Proyecto.id)
    if fecha_inicio:
        q = q.filter(GeneracionDiaria.fecha >= fecha_inicio)
    if fecha_fin:
        q = q.filter(GeneracionDiaria.fecha <= fecha_fin)
    rows = q.group_by(GeneracionDiaria.proyecto_id, Proyecto.nombre_comercial).all()
    return [
        {
            "proyecto_id": r.proyecto_id,
            "nombre_comercial": r.nombre_comercial,
            "total_kwh_real": float(r.total_kwh_real) if r.total_kwh_real else None,
            "total_kwh_p90": float(r.total_kwh_p90) if r.total_kwh_p90 else None,
            "dias_con_dato": r.dias_con_dato,
            "fecha_inicio": r.fecha_inicio,
            "fecha_fin": r.fecha_fin,
        }
        for r in rows
    ]
