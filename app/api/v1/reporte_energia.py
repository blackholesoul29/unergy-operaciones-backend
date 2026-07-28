"""API del reporte de energía (Quoia · Solenium · ASIC) -- reemplaza el
placeholder ReporteEnergiaAutomatizacionView.vue del frontend.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.models.usuarios import Usuario
from app.schemas.reporte_energia import (
    FronteraReporteItem, ResumenReporteEnergia, DetalleFronteraReporte,
    EditarCurvaRequest, ValidarResponse, EjecutarDiaResponse, EnviarReporteEnergiaResponse,
)
from app.services.reporte_energia import curvas, solenium as solenium_svc, orquestador, excel as excel_svc
from app.services.reporte_energia.utils import curva_a_lista, lista_a_curva
from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient

router = APIRouter(prefix="/reporte-energia", tags=["Reporte de Energía"])


def _semaforo(caso, revisar: bool) -> str:
    if revisar:
        return "critical"
    if str(caso) in ("1", "CGM"):
        return "success"
    return "warning"


@router.get("/resumen", response_model=ResumenReporteEnergia)
def resumen(fecha: date = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    gen = db.execute(
        select(ReporteEnergiaGeneracion.caso, ReporteEnergiaGeneracion.revisar_manualmente)
        .where(ReporteEnergiaGeneracion.fecha == fecha)
    ).all()
    con = db.execute(
        select(ReporteEnergiaConsumo.caso, ReporteEnergiaConsumo.revisar_manualmente)
        .where(ReporteEnergiaConsumo.fecha == fecha)
    ).all()

    filas = list(gen) + list(con)
    total = len(filas)
    revisar = sum(1 for _, r in filas if r)
    confiado = sum(1 for c, r in filas if not r and str(c) in ("1", "CGM"))
    corregido = total - revisar - confiado

    return ResumenReporteEnergia(
        fecha=fecha, total=total, revisar=revisar, corregido_automatico=corregido,
        confiado=confiado, puede_enviar=(revisar == 0 and total > 0),
    )


@router.get("/fronteras", response_model=list[FronteraReporteItem])
def listar_fronteras(
    fecha: date = Query(...),
    tipo: str | None = Query(None, description="generacion | consumo"),
    solo_pendientes: bool = Query(False),
    q: str | None = Query(None, description="buscar por nombre de proyecto"),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    items: list[FronteraReporteItem] = []

    if tipo in (None, "generacion"):
        filas = db.execute(
            select(ReporteEnergiaGeneracion, Frontera, Proyecto.id)
            .join(Frontera, Frontera.id == ReporteEnergiaGeneracion.frontera_id)
            .join(Proyecto, Proyecto.id == Frontera.proyecto_id, isouter=True)
            .where(ReporteEnergiaGeneracion.fecha == fecha)
        ).all()
        for rep, front, proyecto_id in filas:
            if solo_pendientes and not rep.revisar_manualmente:
                continue
            if q and q.lower() not in (front.nombre_frontera or "").lower():
                continue
            items.append(FronteraReporteItem(
                frontera_id=front.id, proyecto_id=proyecto_id, nombre_proyecto=front.nombre_frontera,
                tipo="generacion", caso=str(rep.caso), medidor_usado=rep.medidor_usado,
                energia_final_kwh=float(rep.energia_final_kwh) if rep.energia_final_kwh is not None else None,
                revisar_manualmente=rep.revisar_manualmente, editado_manualmente=rep.editado_manualmente,
                nota_solenium=rep.nota_solenium,
            ))

    if tipo in (None, "consumo"):
        filas = db.execute(
            select(ReporteEnergiaConsumo, Frontera, Proyecto.id)
            .join(Frontera, Frontera.id == ReporteEnergiaConsumo.frontera_id)
            .join(Proyecto, Proyecto.id == Frontera.proyecto_id, isouter=True)
            .where(ReporteEnergiaConsumo.fecha == fecha)
        ).all()
        for rep, front, proyecto_id in filas:
            if solo_pendientes and not rep.revisar_manualmente:
                continue
            if q and q.lower() not in (front.nombre_frontera or "").lower():
                continue
            items.append(FronteraReporteItem(
                frontera_id=front.id, proyecto_id=proyecto_id, nombre_proyecto=front.nombre_frontera,
                tipo="consumo", caso=rep.caso, medidor_usado=rep.medidor_usado,
                energia_final_kwh=float(rep.energia_final_kwh) if rep.energia_final_kwh is not None else None,
                revisar_manualmente=rep.revisar_manualmente, editado_manualmente=rep.editado_manualmente,
            ))

    # Prioridad: revisar primero, luego corregido, luego confiado
    orden = {"critical": 0, "warning": 1, "success": 2}
    items.sort(key=lambda i: orden[_semaforo(i.caso, i.revisar_manualmente)])
    return items


def _fila_por_id(db: Session, frontera_id: int, fecha: date):
    front = db.get(Frontera, frontera_id)
    if front is None:
        raise HTTPException(404, "Frontera no encontrada")
    Modelo = ReporteEnergiaGeneracion if front.tipo_frontera == TipoFronteraEnum.generacion else ReporteEnergiaConsumo
    rep = db.execute(
        select(Modelo).where(Modelo.frontera_id == frontera_id, Modelo.fecha == fecha)
    ).scalar_one_or_none()
    if rep is None:
        raise HTTPException(404, "No hay reporte para esa frontera y fecha")
    return front, rep, Modelo


def _construir_detalle(db: Session, frontera_id: int, fecha: date) -> DetalleFronteraReporte:
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    es_generacion = Modelo is ReporteEnergiaGeneracion

    # Curvas de referencia (medidor, Solenium) siempre en vivo, sin importar
    # qué Caso ganó -- para que el revisor pueda comparar visualmente.
    curva_medidor_ppal = curva_medidor_resp = curva_sol = None
    try:
        gaia = GaiaClient()
        mapa_nodo = curvas.construir_mapa_medidor_nodo(gaia)
        borders = {}
        for p in gaia.get_all_borders():
            for key in ("frt_generation", "frt_consumption"):
                frt = p.get(key)
                if frt and frt.get("frt_code"):
                    borders[frt["frt_code"].strip().lower()] = frt
        meta = borders.get((front.codigo_frontera or "").strip().lower())
        if meta:
            c = curvas.curvas_de_frontera(
                gaia, mapa_nodo, meta.get("main_meter"), meta.get("backup_meter"),
                str(fecha), front.codigo_frontera,
            )
            curva_medidor_ppal = curva_a_lista(c["curva_ppal"])
            curva_medidor_resp = curva_a_lista(c["curva_resp"])
        if es_generacion and front.proyecto_id:
            proyecto = db.get(Proyecto, front.proyecto_id)
            if proyecto and proyecto.project_id_solenium and proyecto.project_id_solenium.isdigit():
                sol = SoleniumClient()
                curva_s, _ = solenium_svc.curva_generacion(sol, int(proyecto.project_id_solenium), str(fecha))
                curva_sol = curva_a_lista(curva_s)
    except Exception:
        pass  # las curvas de referencia son informativas -- si fallan, se muestra igual el resultado ya guardado

    return DetalleFronteraReporte(
        frontera_id=front.id, proyecto_id=front.proyecto_id, nombre_proyecto=front.nombre_frontera,
        tipo="generacion" if es_generacion else "consumo", fecha=fecha,
        caso=str(rep.caso), medidor_usado=rep.medidor_usado,
        energia_final_kwh=float(rep.energia_final_kwh) if rep.energia_final_kwh is not None else None,
        curva_final=rep.curva_final or [None] * 24,
        fp=float(rep.fp) if es_generacion and rep.fp is not None else None,
        fp_calculada=float(rep.fp_calculada) if es_generacion and rep.fp_calculada is not None else None,
        error_final_pct=float(rep.error_final_pct) if es_generacion and rep.error_final_pct is not None else None,
        energia_cgm_kwh=float(rep.energia_cgm_kwh) if rep.energia_cgm_kwh is not None else None,
        estado_reporte=rep.estado_reporte,
        energia_solenium_kwh=float(rep.energia_solenium_kwh) if es_generacion and rep.energia_solenium_kwh is not None else None,
        solenium_completo=rep.solenium_completo if es_generacion else None,
        nota_solenium=rep.nota_solenium if es_generacion else None,
        horas_rellenadas_reconectador=rep.horas_rellenadas_reconectador if es_generacion else None,
        horas_rellenadas_solenium=rep.horas_rellenadas_solenium if es_generacion else None,
        horas_rellenadas_historico=rep.horas_rellenadas_historico,
        recuperacion_datos=rep.recuperacion_datos,
        revisar_manualmente=rep.revisar_manualmente, editado_manualmente=rep.editado_manualmente,
        validado_por=rep.validado_por.nombre if rep.validado_por else None,
        validado_en=rep.validado_en,
        curva_medidor_principal=curva_medidor_ppal,
        curva_medidor_respaldo=curva_medidor_resp,
        curva_solenium=curva_sol,
    )


@router.get("/fronteras/{frontera_id}", response_model=DetalleFronteraReporte)
def detalle_frontera(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    return _construir_detalle(db, frontera_id, fecha)


@router.patch("/fronteras/{frontera_id}", response_model=DetalleFronteraReporte)
def editar_curva(
    frontera_id: int, body: EditarCurvaRequest, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    front, rep, _Modelo = _fila_por_id(db, frontera_id, fecha)
    if len(body.curva_final) != 24:
        raise HTTPException(422, "curva_final debe tener 24 valores")

    curva = lista_a_curva(body.curva_final)
    rep.curva_final = curva_a_lista(curva)
    rep.energia_final_kwh = float(curva.fillna(0).sum())
    rep.editado_manualmente = True
    # La corrección manual queda registrada por el sistema de auditoría
    # (audit_log, vía el usuario autenticado) -- no se toca aquí
    # 'revisar_manualmente': queda pendiente de un "Validar" explícito.
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.post("/fronteras/{frontera_id}/validar", response_model=ValidarResponse)
def validar(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user),
):
    front, rep, _Modelo = _fila_por_id(db, frontera_id, fecha)
    rep.revisar_manualmente = False
    rep.validado_por_id = usuario.id
    rep.validado_en = datetime.now(timezone.utc)
    db.commit()
    return ValidarResponse(
        frontera_id=frontera_id, fecha=fecha, revisar_manualmente=False,
        validado_por=usuario.nombre, validado_en=rep.validado_en,
    )


@router.get("/excel")
def descargar_excel(fecha: date = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Excel en el formato manual (hoja "datos") -- disponible siempre, sin
    restricciones (a diferencia de /enviar, que sí se bloquea con pendientes)."""
    contenido = excel_svc.generar_excel_dia(db, fecha)
    return StreamingResponse(
        iter([contenido]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="reporte-energia-{fecha}.xlsx"'},
    )


@router.post("/ejecutar", response_model=EjecutarDiaResponse)
def ejecutar(fecha: date = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Corre (o re-corre) la clasificación de un día. Filas ya editadas a
    mano no se pisan (ver orquestador._upsert_*)."""
    resultado = orquestador.ejecutar_dia(db, fecha)
    return EjecutarDiaResponse(
        fecha=fecha, generacion=resultado["generacion"], consumo=resultado["consumo"],
        omitidas=resultado["omitidas"],
    )


@router.post("/enviar", response_model=EnviarReporteEnergiaResponse)
def enviar(fecha: date = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Envía el reporte del día a Quoia -- bloqueado si queda alguna
    frontera con 'Revisar Manualmente' pendiente (huecos sin fuente).

    NOTA: GaiaClient.post_report() todavía no se ha probado contra un envío
    real -- coordinar con el equipo antes de habilitar este botón en
    producción.
    """
    pendientes_gen = db.execute(
        select(ReporteEnergiaGeneracion.id).where(
            ReporteEnergiaGeneracion.fecha == fecha, ReporteEnergiaGeneracion.revisar_manualmente.is_(True),
        )
    ).first()
    pendientes_con = db.execute(
        select(ReporteEnergiaConsumo.id).where(
            ReporteEnergiaConsumo.fecha == fecha, ReporteEnergiaConsumo.revisar_manualmente.is_(True),
        )
    ).first()
    if pendientes_gen or pendientes_con:
        return EnviarReporteEnergiaResponse(
            fecha=fecha, enviados=0, fallidos=[], bloqueado=True,
            motivo_bloqueo="Quedan fronteras con horas sin fuente (Revisar Manualmente) sin validar.",
        )

    raise HTTPException(501, "Envío real a Quoia pendiente de habilitar -- ver GaiaClient.post_report().")
