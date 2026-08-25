from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.api.v1.inicio_operacion import (
    _estacion_meteo_estado, _frontera_estado, _frontera_live,
    _fusion_solar_estado, _inversores_solenium, _reconectador_estado,
    _reconectador_live,
)
from app.core.database import get_db
from app.models.informe_om import ProyectoInformeOM
from app.models.inicio_operacion import ProyectoInicioOperacion
from app.models.proyectos import Proyecto, TipoProyectoEnum
from app.schemas.informe_om import (
    InformeOMDetail, InformeOMFicha, InformeOMKpis,
    InformeOMListItem, InformeOMProyecto,
)
from app.services.drive_evidencia import eliminar_archivo, subir_archivo

router = APIRouter(prefix="/informe-om", tags=["Informe de Puesta en Marcha"])


def _kpis(f: ProyectoInformeOM | None) -> InformeOMKpis:
    pruebas = (f.protocolo_pruebas if f else []) or []
    eventos = (f.eventos_operativos if f else []) or []

    conformes = sum(1 for p in pruebas if (p or {}).get("resultado") == "conforme")
    no_conformes = sum(1 for p in pruebas if (p or {}).get("resultado") == "no_conforme")
    cerrados = sum(1 for e in eventos if (e or {}).get("estado") == "cerrada")
    abiertos_o_gestion = sum(1 for e in eventos if (e or {}).get("estado") in ("abierta", "en_gestion"))

    estado_global = "atencion" if (no_conformes > 0 or abiertos_o_gestion > 0) else "operativo"

    return InformeOMKpis(
        pruebas_ejecutadas=len(pruebas),
        pruebas_conformes=conformes,
        pruebas_no_conformes=no_conformes,
        eventos_total=len(eventos),
        eventos_cerrados=cerrados,
        eventos_en_gestion=sum(1 for e in eventos if (e or {}).get("estado") == "en_gestion"),
        estado_global=estado_global,
    )


def _ficha_de(f: ProyectoInformeOM | None) -> InformeOMFicha:
    return InformeOMFicha(
        version=f.version if f else None,
        elaborado_por=(f.elaborado_por if f else None) or "Operaciones Unergy",
        actividad=(f.actividad if f else None) or "Puesta en marcha del sistema de monitoreo",
        objetivo_alcance=(f.objetivo_alcance if f else {}) or {},
        datos_generales=(f.datos_generales if f else {}) or {},
        arquitectura_comunicacion=(f.arquitectura_comunicacion if f else {}) or {},
        equipos=(f.equipos if f else []) or [],
        variables_monitoreadas=(f.variables_monitoreadas if f else []) or [],
        configuracion_monitoreo=(f.configuracion_monitoreo if f else {}) or {},
        protocolo_pruebas=(f.protocolo_pruebas if f else []) or [],
        eventos_operativos=(f.eventos_operativos if f else []) or [],
        observaciones=(f.observaciones if f else {}) or {},
        recomendaciones=(f.recomendaciones if f else []) or [],
        conclusion=f.conclusion if f else None,
        firmas=(f.firmas if f else []) or [],
        evidencia_arquitectura=(f.evidencia_arquitectura if f else []) or [],
    )


def _evidencia_relacionada(checklist: dict, inversores: list[dict], evidencia_arquitectura: list) -> list[dict]:
    """Toda la evidencia ya subida (Inicio de Operación + Arquitectura de este
    informe), para que el Informe la muestre y el PDF la enlace -- sin volver
    a subir nada, es la misma evidencia."""
    items: list[dict] = []

    def _add(seccion: str, lista):
        for ev in (lista or []):
            if ev.get("url"):
                items.append({"seccion": seccion, "nombre": ev.get("nombre") or "Archivo", "url": ev["url"]})

    inv_items = ((checklist.get("inversores") or {}).get("items") or {})
    inv_nombre = {str(i["id"]): i.get("nombre") for i in inversores}
    for inv_id, item in inv_items.items():
        _add(f"Strings — {inv_nombre.get(inv_id, f'Inversor {inv_id}')}", (item or {}).get("strings_evidencia"))

    monitoreo = checklist.get("monitoreo") or {}
    _add("Starlink", (monitoreo.get("starlink") or {}).get("evidencia"))
    _add("Fusion Solar", (monitoreo.get("fusion_solar") or {}).get("evidencia"))

    frontera = checklist.get("frontera") or {}
    _add("Frontera — Medidor principal", (frontera.get("principal") or {}).get("evidencia"))
    _add("Frontera — Medidor de respaldo", (frontera.get("respaldo") or {}).get("evidencia"))

    meteo = checklist.get("estacion_meteo") or {}
    _add("Estación meteorológica", (meteo.get("reporta_datos") or {}).get("evidencia"))

    _add("Reconectador", (checklist.get("reconectador") or {}).get("evidencia"))
    _add("Arquitectura de comunicación", evidencia_arquitectura)

    return items


def _detail(p: Proyecto, f: ProyectoInformeOM | None, db: Session) -> InformeOMDetail:
    io = db.query(ProyectoInicioOperacion).filter(ProyectoInicioOperacion.proyecto_id == p.id).first()
    checklist = (io.checklist if io else {}) or {}
    inversores = _inversores_solenium(p)

    return InformeOMDetail(
        proyecto=InformeOMProyecto.model_validate(p),
        ficha=_ficha_de(f),
        kpis=_kpis(f),
        fecha_energizacion=io.fecha_energizacion.isoformat() if (io and io.fecha_energizacion) else None,
        fecha_inicio_operacion=io.fecha_inicio_operacion.isoformat() if (io and io.fecha_inicio_operacion) else None,
        empresa_contratista=io.empresa_contratista if io else None,
        inversores=inversores,
        pendientes=(io.pendientes if io else []) or [],
        fusion_solar_estado=_fusion_solar_estado(checklist),
        frontera_estado=_frontera_estado(checklist),
        estacion_meteo_estado=_estacion_meteo_estado(checklist),
        reconectador_estado=_reconectador_estado(checklist),
        reconectador_live=_reconectador_live(p),
        frontera_live=_frontera_live(p, db),
        evidencia_relacionada=_evidencia_relacionada(checklist, inversores, (f.evidencia_arquitectura if f else []) or []),
    )


@router.get("/proyectos", response_model=list[InformeOMListItem])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Minigranjas en operación con servicio de operación (mismo filtro que Inicio de Operación)."""
    proyectos = (
        db.query(Proyecto)
        .filter(
            Proyecto.srv_operacion == True,  # noqa: E712
            Proyecto.tipo_proyecto == TipoProyectoEnum.minigranja,
            Proyecto.estado == "en_operacion",
            Proyecto.deleted_at.is_(None),
        )
        .order_by(Proyecto.nombre_comercial)
        .all()
    )
    fichas = {f.proyecto_id: f for f in db.query(ProyectoInformeOM).all()}
    out = []
    for p in proyectos:
        f = fichas.get(p.id)
        out.append(InformeOMListItem(
            id=p.id,
            nombre_comercial=p.nombre_comercial,
            municipio=p.municipio,
            departamento=p.departamento,
            potencia_instalada_kwp=float(p.potencia_instalada_kwp) if p.potencia_instalada_kwp is not None else None,
            tiene_ficha=f is not None,
            estado_global=_kpis(f).estado_global,
        ))
    return out


@router.get("/{proyecto_id}", response_model=InformeOMDetail)
def obtener(proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    return _detail(p, f, db)


@router.put("/{proyecto_id}", response_model=InformeOMDetail)
def guardar(
    proyecto_id: int,
    body: InformeOMFicha,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInformeOM(proyecto_id=proyecto_id)
        db.add(f)

    f.version = body.version
    f.elaborado_por = body.elaborado_por
    f.actividad = body.actividad
    f.objetivo_alcance = body.objetivo_alcance or {}
    f.datos_generales = body.datos_generales or {}
    f.arquitectura_comunicacion = body.arquitectura_comunicacion or {}
    f.equipos = body.equipos or []
    f.variables_monitoreadas = body.variables_monitoreadas or []
    f.configuracion_monitoreo = body.configuracion_monitoreo or {}
    f.protocolo_pruebas = body.protocolo_pruebas or []
    f.eventos_operativos = body.eventos_operativos or []
    f.observaciones = body.observaciones or {}
    f.recomendaciones = body.recomendaciones or []
    f.conclusion = body.conclusion
    f.firmas = body.firmas or []
    f.evidencia_arquitectura = body.evidencia_arquitectura or []

    db.commit()
    db.refresh(f)
    return _detail(p, f, db)


def _get_or_create_ficha(proyecto_id: int, db: Session) -> tuple[ProyectoInformeOM, Proyecto]:
    p = db.query(Proyecto).filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None)).first()
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    f = db.query(ProyectoInformeOM).filter(ProyectoInformeOM.proyecto_id == proyecto_id).first()
    if not f:
        f = ProyectoInformeOM(proyecto_id=proyecto_id)
        db.add(f)
        db.flush()
    return f, p


@router.post("/{proyecto_id}/archivos/arquitectura")
async def subir_evidencia_arquitectura(
    proyecto_id: int,
    archivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f, p = _get_or_create_ficha(proyecto_id, db)
    nuevo = await subir_archivo(archivo, [p.nombre_comercial, "Arquitectura de comunicación"])
    f.evidencia_arquitectura = [*(f.evidencia_arquitectura or []), nuevo]
    db.commit()
    return nuevo


@router.delete("/{proyecto_id}/archivos/arquitectura/{archivo_id}")
def eliminar_evidencia_arquitectura(
    proyecto_id: int,
    archivo_id: str,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    f, _p = _get_or_create_ficha(proyecto_id, db)
    lista = f.evidencia_arquitectura or []
    nueva_lista = [x for x in lista if x.get("id") != archivo_id]
    if len(nueva_lista) == len(lista):
        raise HTTPException(404, "Archivo no encontrado")
    eliminar_archivo(archivo_id)
    f.evidencia_arquitectura = nueva_lista
    db.commit()
    return {"status": "ok"}
