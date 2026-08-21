"""API del reporte de energía (Quoia · Solenium · ASIC) -- reemplaza el
placeholder ReporteEnergiaAutomatizacionView.vue del frontend.
"""
from __future__ import annotations

import json
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo, ReporteEnergiaExclusion
from app.models.usuarios import Usuario
from app.schemas.reporte_energia import (
    FronteraReporteItem, ResumenReporteEnergia, DetalleFronteraReporte,
    EditarCurvaRequest, ValidarResponse, EjecutarDiaResponse, EnviarReporteEnergiaResponse,
    EdicionAuditoria, EstadoCorridaResponse, CancelarCorridaResponse,
    CrearExclusionRequest, ExclusionOut, EditarExclusionRequest, CurvaTipicaResponse,
    CargaExcelTercerosResponse,
)
from app.services.reporte_energia import curvas, orquestador, excel as excel_svc, historial, reconectador, recuperacion
from app.services.reporte_energia import excel_terceros
from app.services.reporte_energia.clasificador import FRONTERAS_TERCEROS
from app.services.reporte_energia.clasificador_consumo import rellenar_horas_faltantes_consumo
from app.services.reporte_energia.utils import curva_a_lista, lista_a_curva, escalar_curva, rellenar_con_otro_medidor
from app.services.reporte_cgm import resolver_borders
from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient

router = APIRouter(prefix="/reporte-energia", tags=["Reporte de Energía"])

# Correcciones cosméticas de nombre_frontera SOLO para esta vista -- el
# campo real en `fronteras` no se toca (puede reflejar el registro tal como
# quedó cargado, con errores de digitación incluidos, y otras pantallas ya
# lo muestran así). frontera_id -> nombre a mostrar acá.
_NOMBRES_CORREGIDOS: dict[int, str] = {
    6: "MINIGRANJA SOLAR BARAYA SERV AUX",  # BD: "MINIGRANJA SOLAR BRAYA SERV AUX"
}


def _nombre_frontera(front: Frontera) -> str:
    return _NOMBRES_CORREGIDOS.get(front.id, front.nombre_frontera)


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
            if q and q.lower() not in (_nombre_frontera(front) or "").lower():
                continue
            items.append(FronteraReporteItem(
                frontera_id=front.id, proyecto_id=proyecto_id, nombre_proyecto=_nombre_frontera(front),
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
            if q and q.lower() not in (_nombre_frontera(front) or "").lower():
                continue
            items.append(FronteraReporteItem(
                frontera_id=front.id, proyecto_id=proyecto_id, nombre_proyecto=_nombre_frontera(front),
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


def _curva_cambio(persistida: list | None, viva: list | None, tolerancia: float = 0.01) -> bool | None:
    """True si la curva en vivo difiere de la persistida por más del 1% del
    total del día -- señal de que Quoia corrigió algo desde que se
    clasificó (ver MGS 0032 El Paso Norte 2026-08-05: medidor doblado al
    momento de clasificar, ya corregido para cuando se revisó). None si no
    hay curva persistida con qué comparar (fila anterior a este fix)."""
    if persistida is None or viva is None:
        return None
    total_p = sum(v for v in persistida if v is not None)
    total_v = sum(v for v in viva if v is not None)
    base = max(abs(total_p), abs(total_v))
    if base == 0:
        return False
    return abs(total_p - total_v) / base > tolerancia


def _construir_detalle(db: Session, frontera_id: int, fecha: date) -> DetalleFronteraReporte:
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    es_generacion = Modelo is ReporteEnergiaGeneracion

    # Curvas de referencia -- se prefiere lo que quedó GUARDADO al momento de
    # clasificar (no existía antes de este fix: MGS 0032 El Paso Norte
    # 2026-08-05, medidor doblado por un glitch de Quoia mostraba un número
    # arriba y otro distinto en "Detalle de las fuentes", sin explicación).
    # Se sigue consultando Quoia en vivo IGUAL que antes, pero ahora solo
    # para detectar si algo cambió desde entonces (medidor_actualizado_en_quoia)
    # -- si la fila es de antes de este fix (columnas en null), se cae a lo
    # que ya se hacía: mostrar directo lo que Quoia tiene ahora.
    curva_medidor_ppal_bd = rep.curva_medidor_principal
    curva_medidor_resp_bd = rep.curva_medidor_respaldo
    curva_sol_bd = rep.curva_solenium_referencia if es_generacion else None
    # Igual que Solenium -- persistida, sin re-consultar en vivo (sería una
    # llamada más a la API de Solenium en cada apertura del panel). Casi
    # siempre en null: solo se llenó si el reconectador se consultó ese día.
    curva_reconectador_bd = rep.curva_reconectador_referencia if es_generacion else None

    # Solenium ya NO se consulta en vivo acá -- costaba ~2s en cada apertura
    # del panel, solo para detectar si Solenium cambió desde que se
    # clasificó (un caso mucho menos común que el del medidor). Se usa
    # directo lo que quedó persistido; si la fila es de antes del fix de
    # persistencia, simplemente no hay curva de Solenium que mostrar acá.
    curva_medidor_ppal_viva = curva_medidor_resp_viva = None
    try:
        gaia = GaiaClient()
        # Cacheados (ver curvas._CACHE_TTL) -- esta vista se abre repetidas
        # veces por sesión solo para mostrar curvas de referencia, no hace
        # falta traer el catálogo completo de Quoia en cada clic. En frío
        # (TTL vencido) son dos llamadas HTTP independientes -- en paralelo
        # en vez de secuencial, el costo es el máximo de las dos, no la suma.
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_nodo = executor.submit(curvas.construir_mapa_medidor_nodo, gaia)
            fut_borders = executor.submit(curvas.construir_mapa_borders, gaia)
            mapa_nodo = fut_nodo.result()
            borders = fut_borders.result()
        meta = borders.get((front.codigo_frontera or "").strip().lower())
        if meta:
            # curva_medidor_en_vivo() en vez de curvas_de_frontera(): acá solo
            # hace falta UNA variable (eae o iae, según el tipo de frontera) --
            # curvas_de_frontera() trae las 4 (eae+iae x principal+respaldo) de
            # forma secuencial porque el clasificador sí las necesita todas;
            # pedir las 2 de más y en secuencia era la mayor parte de la demora
            # al abrir el panel (2026-08-12). Sin recuperación activa tampoco
            # -- esto es solo para mostrar una curva de referencia, no tiene
            # sentido interrogar el medidor (hasta 90s) por eso.
            var_name = "eae" if es_generacion else "iae"
            curva_p, curva_r = curvas.curva_medidor_en_vivo(
                gaia, mapa_nodo, meta.get("main_meter"), meta.get("backup_meter"),
                str(fecha), front.codigo_frontera, var_name,
            )
            curva_medidor_ppal_viva = curva_a_lista(curva_p)
            curva_medidor_resp_viva = curva_a_lista(curva_r)
    except Exception:
        pass  # las curvas de referencia son informativas -- si fallan, se muestra igual el resultado ya guardado

    # Por medidor, no solo el que ganó como medidor_usado (2026-08-20): si
    # el clasificador usó 'Histórico' porque el medidor estaba mal en ese
    # momento, y luego alguien recupera el medidor (a mano en Quoia, o con
    # el botón "Recuperar medidor"), esto tiene que poder avisarlo igual --
    # antes, al estar escopado solo al medidor usado, ese caso quedaba
    # invisible: ni el aviso ni la opción "(actualizado)" aparecían nunca.
    principal_actualizado_en_quoia = bool(_curva_cambio(curva_medidor_ppal_bd, curva_medidor_ppal_viva))
    respaldo_actualizado_en_quoia = bool(_curva_cambio(curva_medidor_resp_bd, curva_medidor_resp_viva))
    curva_medidor_ppal = curva_medidor_ppal_bd if curva_medidor_ppal_bd is not None else curva_medidor_ppal_viva
    curva_medidor_resp = curva_medidor_resp_bd if curva_medidor_resp_bd is not None else curva_medidor_resp_viva
    curva_sol = curva_sol_bd

    # Curva y total EN VIVO de cada medidor -- para el aviso "el medidor ya
    # muestra un valor distinto en Quoia" (curva_medidor_principal/respaldo
    # ya muestran lo persistido) y para que 'Reportar con otra fuente'
    # pueda ofrecer directamente ese valor actualizado, sin que la persona
    # tenga que copiarlo a mano (pedido 2026-08-12; ampliado a ambos
    # medidores 2026-08-20).
    principal_energia_actual_kwh = None
    principal_curva_actual: list | None = None
    if principal_actualizado_en_quoia and curva_medidor_ppal_viva is not None:
        principal_curva_actual = curva_medidor_ppal_viva
        principal_energia_actual_kwh = sum(v for v in principal_curva_actual if v is not None)

    respaldo_energia_actual_kwh = None
    respaldo_curva_actual: list | None = None
    if respaldo_actualizado_en_quoia and curva_medidor_resp_viva is not None:
        respaldo_curva_actual = curva_medidor_resp_viva
        respaldo_energia_actual_kwh = sum(v for v in respaldo_curva_actual if v is not None)

    return DetalleFronteraReporte(
        frontera_id=front.id, proyecto_id=front.proyecto_id, nombre_proyecto=_nombre_frontera(front),
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
        horas_rellenadas_medidor_cruzado=rep.horas_rellenadas_medidor_cruzado,
        recuperacion_datos=rep.recuperacion_datos,
        revisar_manualmente=rep.revisar_manualmente, editado_manualmente=rep.editado_manualmente,
        validado_por=rep.validado_por.nombre if rep.validado_por else None,
        validado_en=rep.validado_en,
        error_clasificacion=rep.error_clasificacion,
        enviado_quoia_en=rep.enviado_quoia_en, enviado_quoia_ok=rep.enviado_quoia_ok,
        enviado_quoia_error=rep.enviado_quoia_error,
        curva_medidor_principal=curva_medidor_ppal,
        curva_medidor_respaldo=curva_medidor_resp,
        curva_solenium=curva_sol,
        curva_reconectador=curva_reconectador_bd,
        principal_actualizado_en_quoia=principal_actualizado_en_quoia,
        principal_energia_actual_kwh=round(principal_energia_actual_kwh, 4) if principal_energia_actual_kwh is not None else None,
        principal_curva_actual=principal_curva_actual,
        respaldo_actualizado_en_quoia=respaldo_actualizado_en_quoia,
        respaldo_energia_actual_kwh=round(respaldo_energia_actual_kwh, 4) if respaldo_energia_actual_kwh is not None else None,
        respaldo_curva_actual=respaldo_curva_actual,
        curva_respaldo_terceros=rep.curva_respaldo_terceros if es_generacion else None,
        capacidad_efectiva_mw=float(front.capacidad_efectiva_mw) if es_generacion and front.capacidad_efectiva_mw is not None else None,
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
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    if len(body.curva_final) != 24:
        raise HTTPException(422, "curva_final debe tener 24 valores")

    curva = lista_a_curva(body.curva_final)
    rep.curva_final = curva_a_lista(curva)
    rep.energia_final_kwh = float(curva.fillna(0).sum())
    rep.editado_manualmente = True
    # Los flags de 'hora rellenada' (reconectador/Solenium/histórico) eran
    # de la curva ANTERIOR -- si la persona reemplaza curva_final a mano
    # (otra fuente, o celda por celda), esas horas ya no vienen de ese
    # relleno; dejarlos quedaba mostrando el diamante dorado de 'Rellenado'
    # sobre datos que ya no lo son (ver GD Naos 1 2026-08-12: 'Medidor
    # principal' elegido a mano, pero seguía marcando 14h-16h como
    # 'Rellenado (histórico)', dato del clasificador automático original).
    if Modelo is ReporteEnergiaGeneracion:
        rep.horas_rellenadas_reconectador = None
        rep.horas_rellenadas_solenium = None
    rep.horas_rellenadas_historico = None
    # 'Fuente usada' quedaba mostrando lo que el clasificador decidió
    # originalmente (ej. 'Histórico propio') aunque la persona ya hubiera
    # reemplazado la curva con otra fuente ('Reportar con otra fuente') --
    # cualquier guardado manual reemplaza la fuente reportada. Si el editor
    # se llenó desde una de esas opciones, se refleja esa fuente específica
    # (mismos valores que ya usa ETIQUETAS_FUENTE en el front: 'Medidor
    # principal'/'respaldo', 'Inversores × FP', 'Histórico propio'); si fue
    # edición celda por celda sin pasar por ahí, o si se usó 'Matriz de
    # ceros' (no es una fuente real, solo un valor de reemplazo), queda el
    # genérico "Editado manualmente".
    FUENTES_MANUALES_VALIDAS = {"principal", "respaldo", "inversores", "historico"}
    rep.medidor_usado = body.fuente if body.fuente in FUENTES_MANUALES_VALIDAS else "editado_manualmente"
    # Si la fuente elegida es un medidor, lo que se acaba de guardar pasa a
    # ser el nuevo snapshot de ESE medidor -- si no se actualiza, 'Detalle de
    # las fuentes' y el aviso 'el medidor muestra un valor distinto en Quoia'
    # seguian comparando contra el numero congelado de la clasificacion
    # original, aunque la persona ya hubiera adoptado la opcion '(actualizado)'
    # de 'Reportar con otra fuente' (esa opcion cambia curva_final pero nunca
    # tocaba curva_medidor_principal/respaldo, ver captura 2026-08-20).
    if body.fuente == "principal":
        rep.curva_medidor_principal = rep.curva_final
    elif body.fuente == "respaldo":
        rep.curva_medidor_respaldo = rep.curva_final
    # Si la persona confirma que el MEDIDOR (no una estimación) es la
    # fuente correcta, 'caso' se actualiza para que esta fila SÍ pueda
    # alimentar la mediana/forma histórica de días futuros -- antes quedaba
    # congelado en lo que decidió el clasificador automático (ej. caso
    # 'Histórico' o 3), y CASOS_CONFIABLES_GENERACION/CONSUMO en
    # historial.py filtran por ese campo, no por medidor_usado, así que una
    # corrección manual con dato real nunca contaba (ver Valencia Oriente 2
    # Consumo 2026-08-12: editada a 'Medidor principal' y validada, pero
    # 'caso' seguía en 'Histórico'). 'Inversores × FP', 'Histórico propio' y
    # 'Matriz de ceros' siguen sin tocar 'caso' -- son estimaciones o un
    # valor de reemplazo, no una lectura real del medidor (mismo criterio
    # que ya excluye el Caso 3 -- Inversores × FP automático -- de
    # CASOS_CONFIABLES_GENERACION).
    if body.fuente in ("principal", "respaldo"):
        rep.caso = "Medidor" if Modelo is ReporteEnergiaConsumo else 5
    # La corrección manual queda registrada por el sistema de auditoría
    # (audit_log, vía el usuario autenticado) -- no se toca aquí
    # 'revisar_manualmente': queda pendiente de un "Validar" explícito.
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.post("/fronteras/{frontera_id}/rellenar-horario", response_model=DetalleFronteraReporte)
def rellenar_horario(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Rellena a mano las horas que quedaron sin dato en 'curva_final' --
    acción explícita, ya NO pasa sola durante la clasificación automática
    (decisión 2026-08-12: mezclar otra fuente en la curva final sin que
    nadie lo pidiera era demasiado invasivo). Orden de fuentes, la primera
    que tenga dato para cada hora gana:

    1. El OTRO medidor (el que no ganó como medidor_usado) -- mismo
       consumo/generación física, dato real, no una estimación.
    2. Generación: reconectador, luego Solenium × FP.
    3. Histórico propio (mediana × forma) -- último recurso en ambos árboles.

    Aplica a Generación y Consumo. No fuerza revisar_manualmente -- es una
    acción manual y consciente, igual que editar_curva(); queda pendiente
    de un "Validar Frontera" explícito.
    """
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    es_generacion = Modelo is ReporteEnergiaGeneracion

    curva_actual = lista_a_curva(rep.curva_final)
    if not curva_actual.isna().any():
        raise HTTPException(400, "Esta curva no tiene horas sin dato para rellenar")

    curva_actual, horas_medidor_cruzado = rellenar_con_otro_medidor(
        curva_actual, rep.medidor_usado, rep.curva_medidor_principal, rep.curva_medidor_respaldo,
    )

    horas_reconectador, horas_solenium_h, horas_historico = set(), set(), set()
    curva_reconectador_ref = None
    fp = fp_calc = None
    if curva_actual.isna().any():
        if es_generacion:
            proyecto = front.proyecto
            project_id_solenium = (
                int(proyecto.project_id_solenium)
                if proyecto and proyecto.project_id_solenium and str(proyecto.project_id_solenium).isdigit()
                else None
            )
            curva_solenium = lista_a_curva(rep.curva_solenium_referencia) if rep.curva_solenium_referencia else None
            if rep.fp is not None:
                fp, fp_calc = float(rep.fp), float(rep.fp_calculada) if rep.fp_calculada is not None else None
            else:
                fp, fp_calc = historial.get_factor_perdida_detalle(db, frontera_id, fecha)

            sol = SoleniumClient()
            curva_actual, horas_reconectador, horas_solenium_h, horas_historico, curva_reconectador_ref = (
                reconectador.rellenar_horas_faltantes(
                    db, sol, curva_actual, project_id_solenium, str(fecha),
                    frontera_id=frontera_id, curva_solenium=curva_solenium, fp=fp,
                )
            )
        else:
            curva_actual, horas_historico = rellenar_horas_faltantes_consumo(db, curva_actual, frontera_id, fecha)

    if not (horas_medidor_cruzado or horas_reconectador or horas_solenium_h or horas_historico):
        raise HTTPException(400, "Ninguna fuente tenía dato para las horas faltantes")

    rep.curva_final = curva_a_lista(curva_actual)
    rep.energia_final_kwh = float(curva_actual.fillna(0).sum())
    rep.horas_rellenadas_medidor_cruzado = sorted(horas_medidor_cruzado) or None
    rep.horas_rellenadas_historico = sorted(horas_historico) or None
    if es_generacion:
        rep.horas_rellenadas_reconectador = sorted(horas_reconectador) or None
        rep.horas_rellenadas_solenium = sorted(horas_solenium_h) or None
        if curva_reconectador_ref is not None:
            rep.curva_reconectador_referencia = curva_a_lista(curva_reconectador_ref)
        if horas_solenium_h and rep.fp is None:
            rep.fp = fp
            rep.fp_calculada = fp_calc
        if rep.medidor_usado == "revisar":
            rep.medidor_usado = "relleno_horario"
    # revisar_manualmente NO se fuerza acá -- ese forzado tenía sentido
    # mientras el relleno era automático y silencioso (nadie lo notaba sin
    # la bandera); ahora que es una acción manual y consciente (la persona
    # ve las fuentes disponibles y decide hacer clic), queda igual que
    # editar_curva(): pendiente de un "Validar Frontera" explícito, sin que
    # el botón se lo imponga.
    # Evita que una re-ejecución del clasificador para este mismo día pise
    # este relleno manual (mismo guard que ya protege 'Reportar con otra
    # fuente', ver editar_curva() arriba).
    rep.editado_manualmente = True
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.post("/fronteras/{frontera_id}/deshacer-relleno", response_model=DetalleFronteraReporte)
def deshacer_relleno(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Revierte lo que puso 'Rellenar horas' -- vuelve a NaN exactamente las
    horas que quedaron marcadas en horas_rellenadas_* (medidor_cruzado/
    reconectador/solenium/historico), sin tocar ninguna otra hora de la
    curva. Si medidor_usado había pasado a 'relleno_horario' (venía de
    'revisar'), se restaura a 'revisar' -- en cualquier otro caso
    medidor_usado no lo había tocado el relleno, así que tampoco se toca acá.
    reconectador/Solenium son campos exclusivos de Generación (Consumo no
    tiene esas columnas) -- guardado con es_generacion, igual que el resto
    de este archivo.
    """
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    es_generacion = Modelo is ReporteEnergiaGeneracion

    horas_reconectador = (rep.horas_rellenadas_reconectador or []) if es_generacion else []
    horas_solenium = (rep.horas_rellenadas_solenium or []) if es_generacion else []
    horas_a_revertir = set(
        (rep.horas_rellenadas_medidor_cruzado or [])
        + horas_reconectador
        + horas_solenium
        + (rep.horas_rellenadas_historico or [])
    )
    if not horas_a_revertir:
        raise HTTPException(400, "Esta frontera no tiene un relleno horario para deshacer")

    curva = lista_a_curva(rep.curva_final)
    for h in horas_a_revertir:
        curva[h] = None
    rep.curva_final = curva_a_lista(curva)
    rep.energia_final_kwh = float(curva.fillna(0).sum())
    rep.horas_rellenadas_medidor_cruzado = None
    rep.horas_rellenadas_historico = None
    if es_generacion:
        rep.horas_rellenadas_reconectador = None
        rep.horas_rellenadas_solenium = None
        # Curva de referencia que "Rellenar horas" guarda solo para mostrar
        # en el gráfico (ReporteEnergiaCurvaChart.vue) -- si se deshace el
        # relleno, ya no debe seguir apareciendo esa capa en la gráfica.
        rep.curva_reconectador_referencia = None
    if rep.medidor_usado == "relleno_horario":
        rep.medidor_usado = "revisar"
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.post("/fronteras/{frontera_id}/recuperar-medidor", response_model=DetalleFronteraReporte)
def recuperar_medidor(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Dispara a demanda la misma recuperación activa (interrogar el medidor
    por WebSocket, hasta 90s) que la corrida diaria dispara sola bajo
    ciertas condiciones (curvas.curvas_de_frontera, TOLERANCIA_VALOR_
    SOSPECHOSO) -- pero para AMBOS medidores y sin ese filtro: acá es una
    decisión explícita de la persona, no necesita el gate de "incompleto o
    sospechoso".

    Solo pide la recuperación y registra el resultado en
    recuperacion_datos -- no relee la curva a mano: _construir_detalle()
    ya hace su propia lectura en vivo cada vez que se llama, así que el
    dato recuperado se refleja solo al volver a leer el detalle (este
    mismo return).

    No toca curva_final/medidor_usado/caso/editado_manualmente -- por eso
    no necesita ningún guard de "no pisar lo ya editado/validado": solo
    refresca datos de referencia (alternativa más chica que reclasificar
    la frontera completa, decidido 2026-08-20).
    """
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    fecha_str = str(fecha)

    gaia = GaiaClient()
    try:
        borders = curvas.construir_mapa_borders(gaia)
    except Exception as e:
        raise HTTPException(502, f"No se pudo consultar Quoia: {e}")

    meta = borders.get((front.codigo_frontera or "").strip().lower())
    main_meter_id = meta.get("main_meter") if meta else None
    backup_meter_id = meta.get("backup_meter") if meta else None
    if not main_meter_id and not backup_meter_id:
        raise HTTPException(400, "Esta frontera no tiene medidor principal ni respaldo configurado en Quoia")

    def _recuperar(meter_id: int, etiqueta: str) -> str:
        resultado = recuperacion.recuperar_datos_medidor(int(meter_id), fecha_str, fecha_str)
        return f"{etiqueta}: {'éxito' if recuperacion.fue_exitosa(resultado) else 'falló'}"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futuros = []
        if main_meter_id:
            futuros.append(executor.submit(_recuperar, main_meter_id, "principal"))
        if backup_meter_id:
            futuros.append(executor.submit(_recuperar, backup_meter_id, "respaldo"))
        intentos = [f.result() for f in futuros]

    rep.recuperacion_datos = ", ".join(intentos) or None
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.post("/fronteras/{frontera_id}/cargar-excel-terceros", response_model=CargaExcelTercerosResponse)
async def cargar_excel_terceros(
    frontera_id: int, archivo: UploadFile = File(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Sube el Excel que envía la empresa tercera que hace el CGM de esta
    frontera (FRONTERAS_TERCEROS, ej. Cedillanos) -- reemplaza la
    transcripción manual que hoy se hace directamente en Quoia. Reporta
    'Primary' como curva_final y 'Backup' (si viene) como
    curva_respaldo_terceros, para que /enviar use ese respaldo real en vez
    de la fórmula ±1%."""
    if frontera_id not in FRONTERAS_TERCEROS:
        raise HTTPException(400, "Esta frontera no está configurada como frontera de terceros")
    front = db.get(Frontera, frontera_id)
    if front is None:
        raise HTTPException(404, "Frontera no encontrada")

    contenido = await archivo.read()
    try:
        fechas_cargadas = excel_terceros.aplicar_excel_terceros(db, frontera_id, contenido)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if not fechas_cargadas:
        raise HTTPException(400, "No encontré ninguna fila 'Primary' con ENERGY TYPE = ENERGIA EXPORTADA ACTIVA")

    db.commit()
    return CargaExcelTercerosResponse(frontera_id=frontera_id, fechas_cargadas=sorted(fechas_cargadas))


@router.delete("/fronteras/{frontera_id}/cargar-excel-terceros", response_model=DetalleFronteraReporte)
def eliminar_excel_terceros(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Quita la carga de Excel de terceros de un día puntual y vuelve a
    dejar la frontera en 'Esperando Excel de terceros' -- para cuando se
    subió el archivo equivocado y no basta con re-cargar el correcto (ej. la
    fecha no debía tener ningún dato). Mismos valores que pone el
    clasificador cuando nunca se ha subido nada para ese día (ver
    FRONTERAS_TERCEROS en clasificador.py)."""
    if frontera_id not in FRONTERAS_TERCEROS:
        raise HTTPException(400, "Esta frontera no está configurada como frontera de terceros")
    rep = db.execute(
        select(ReporteEnergiaGeneracion).where(
            ReporteEnergiaGeneracion.frontera_id == frontera_id,
            ReporteEnergiaGeneracion.fecha == fecha,
        )
    ).scalar_one_or_none()
    if rep is None:
        raise HTTPException(404, "No hay carga para eliminar en esa fecha")

    rep.caso = 0
    rep.medidor_usado = "externo"
    rep.curva_final = None
    rep.energia_final_kwh = None
    rep.curva_respaldo_terceros = None
    rep.revisar_manualmente = True
    rep.editado_manualmente = False
    db.commit()
    return _construir_detalle(db, frontera_id, fecha)


@router.get("/fronteras/{frontera_id}/curva-tipica", response_model=CurvaTipicaResponse)
def curva_tipica(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Mediana x forma horaria de los últimos días confiables -- mismo
    mecanismo que ya alimenta el relleno histórico automático (ver
    historial.py), expuesto para el botón "Curva Típica" en Corrección
    manual. No guarda nada -- solo devuelve la curva para que el usuario
    la revise/ajuste antes de "Guardar corrección"."""
    front = db.get(Frontera, frontera_id)
    if front is None:
        raise HTTPException(404, "Frontera no encontrada")

    es_generacion = front.tipo_frontera == TipoFronteraEnum.generacion
    if es_generacion:
        mediana, dias_usados = historial.get_mediana_generacion(db, frontera_id, fecha)
        forma, _ = historial.get_forma_generacion(db, frontera_id, fecha)
    else:
        mediana, dias_usados = historial.get_mediana_consumo(db, frontera_id, fecha)
        forma, _ = historial.get_forma_consumo(db, frontera_id, fecha)

    if mediana is None or forma is None:
        raise HTTPException(404, "No hay suficiente histórico confiable todavía para esta frontera")

    curva = escalar_curva(forma, mediana)
    return CurvaTipicaResponse(
        curva=curva_a_lista(curva), energia_total_kwh=float(mediana), dias_usados=dias_usados,
    )


@router.get("/fronteras/{frontera_id}/ediciones", response_model=list[EdicionAuditoria])
def ediciones_frontera(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Historial de correcciones manuales (audit_log) para esta fila
    puntual -- quién la editó, cuándo, y el diff de qué campos cambiaron.
    Más reciente primero.

    usuario_id IS NOT NULL filtra las corridas automáticas del clasificador
    (ejecutar_dia_background corre en un hilo de fondo sin usuario
    autenticado, así que su UPDATE también queda en audit_log pero con
    usuario_id/usuario_nombre en NULL) -- sin este filtro, cada re-corrida
    del clasificador aparecía en este historial como si fuera una edición
    manual de alguien."""
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    filas = db.execute(
        text(
            "SELECT usuario_nombre, created_at, cambios FROM audit_log "
            "WHERE tabla = :tabla AND registro_id = :registro_id AND accion = 'UPDATE' "
            "AND usuario_id IS NOT NULL "
            "ORDER BY created_at DESC"
        ),
        {"tabla": Modelo.__tablename__, "registro_id": rep.id},
    ).fetchall()
    return [
        EdicionAuditoria(
            usuario_nombre=f.usuario_nombre,
            created_at=f.created_at,
            cambios=json.loads(f.cambios) if isinstance(f.cambios, str) else f.cambios,
        )
        for f in filas
    ]


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


def _exclusion_out(db: Session, excl: ReporteEnergiaExclusion) -> ExclusionOut:
    front = db.get(Frontera, excl.frontera_id)
    return ExclusionOut(
        id=excl.id, frontera_id=excl.frontera_id,
        nombre_frontera=_nombre_frontera(front) if front else None,
        motivo=excl.motivo, fecha_inicio=excl.fecha_inicio,
        fecha_fin_estimada=excl.fecha_fin_estimada,
        creado_por=excl.creado_por.nombre if excl.creado_por else None,
        resuelta_en=excl.resuelta_en, created_at=excl.created_at,
    )


@router.get("/fronteras/{frontera_id}/exclusiones", response_model=list[ExclusionOut])
def listar_exclusiones(
    frontera_id: int, db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Historial de exclusiones temporales de esta frontera -- activas y
    resueltas, más recientes primero."""
    filas = db.execute(
        select(ReporteEnergiaExclusion)
        .where(ReporteEnergiaExclusion.frontera_id == frontera_id)
        .order_by(ReporteEnergiaExclusion.created_at.desc())
    ).scalars().all()
    return [_exclusion_out(db, f) for f in filas]


@router.post("/fronteras/{frontera_id}/exclusiones", response_model=ExclusionOut)
def crear_exclusion(
    frontera_id: int, body: CrearExclusionRequest,
    db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user),
):
    """Marca una frontera para NO clasificarse en cierto rango de fechas --
    ver ReporteEnergiaExclusion. No depende de Fallas (requiere monitoreo/
    representación, que no todas las fronteras tienen)."""
    if body.frontera_id != frontera_id:
        raise HTTPException(422, "frontera_id del body no coincide con la URL")
    excl = ReporteEnergiaExclusion(
        frontera_id=frontera_id, motivo=body.motivo,
        fecha_inicio=body.fecha_inicio, fecha_fin_estimada=body.fecha_fin_estimada,
        creado_por_id=usuario.id,
    )
    db.add(excl)
    db.commit()
    db.refresh(excl)
    return _exclusion_out(db, excl)


@router.patch("/exclusiones/{exclusion_id}", response_model=ExclusionOut)
def editar_exclusion(
    exclusion_id: int, body: EditarExclusionRequest,
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    excl = db.get(ReporteEnergiaExclusion, exclusion_id)
    if excl is None:
        raise HTTPException(404, "Exclusión no encontrada")
    excl.motivo = body.motivo
    excl.fecha_fin_estimada = body.fecha_fin_estimada
    db.commit()
    db.refresh(excl)
    return _exclusion_out(db, excl)


@router.post("/exclusiones/{exclusion_id}/resolver", response_model=ExclusionOut)
def resolver_exclusion(
    exclusion_id: int, db: Session = Depends(get_db), _=Depends(get_current_user),
):
    excl = db.get(ReporteEnergiaExclusion, exclusion_id)
    if excl is None:
        raise HTTPException(404, "Exclusión no encontrada")
    excl.resuelta_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(excl)
    return _exclusion_out(db, excl)


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
def ejecutar(fecha: date = Query(...), _=Depends(get_current_user)):
    """Dispara (o re-dispara) la clasificación de un día en un hilo aparte y
    responde de inmediato -- con ~50 fronteras (más recuperación activa de
    medidor cuando aplica) una corrida completa tarda varios minutos, más
    que el timeout fijo del proxy externo que usa el frontend. Filas ya
    editadas a mano no se pisan (ver orquestador._upsert_*)."""
    import threading

    threading.Thread(target=orquestador.ejecutar_dia_background, args=(fecha,), daemon=True).start()
    return EjecutarDiaResponse(fecha=fecha, status="iniciado")


@router.get("/ejecutar/estado", response_model=EstadoCorridaResponse)
def estado_ejecutar(fecha: date = Query(...), _=Depends(get_current_user)):
    """Resultado de la última corrida de /ejecutar para esta fecha -- el
    frontend lo consulta cuando el sondeo de filas se estabiliza, para avisar
    si la corrida terminó con fronteras fallidas (ver sondearResultado())."""
    resultado = orquestador.ultima_corrida(fecha)
    if resultado is None:
        return EstadoCorridaResponse(fecha=fecha)
    return EstadoCorridaResponse(fecha=fecha, **resultado)


@router.post("/ejecutar/cancelar", response_model=CancelarCorridaResponse)
def cancelar_ejecutar(fecha: date = Query(...), _=Depends(get_current_user)):
    """Pide detener una corrida en curso -- cooperativo, no inmediato: el
    loop de ejecutar_dia() revisa esta bandera entre frontera y frontera,
    nunca corta a media frontera."""
    orquestador.cancelar_corrida(fecha)
    return CancelarCorridaResponse(fecha=fecha, solicitado=True)


def _reporte_ya_valido(rep, es_generacion: bool) -> bool:
    """Mismo criterio que excel.py: si Quoia ya reportó bien por su cuenta,
    no hace falta corregirlo -- enviar de más sobreescribiría un reporte
    oficial que ya estaba bien.

    'excluida' también se salta acá -- curva_final es None mientras dura la
    exclusión (ver orquestador._exclusion_activa), así que sin este chequeo
    /enviar mandaría una curva de 0 kWh fabricada a Quoia para una frontera
    que justamente no debe reportar nada mientras se resuelve lo que la
    excluyó."""
    if rep.medidor_usado == "excluida":
        return True
    return rep.medidor_usado == "cgm" if es_generacion else str(rep.caso) == "CGM"


def _enviar_a_quoia(rep, front, es_generacion: bool, gaia: GaiaClient, borders: dict) -> tuple[bool | None, str | None]:
    """Envía UNA fila a Quoia (gaia.post_report) -- factorizado para
    reusarse tanto en /enviar (todas las fronteras del día) como en
    /fronteras/{id}/enviar (una sola, envío controlado de prueba antes de
    confiar en el envío masivo -- ver ADVERTENCIA en gaia_client.post_report).

    Retorna (resultado, motivo):
    - (None, None): no hacía falta enviar, Quoia ya tenía el dato correcto
      (_reporte_ya_valido) -- no se llama a Quoia para nada.
    - (True, None): envío intentado y exitoso.
    - (False, motivo): envío intentado y falló (sin border_id, Quoia
      rechazó, o excepción de red)."""
    if _reporte_ya_valido(rep, es_generacion):
        return None, None

    frt_code = (front.codigo_frontera or "").strip().lower()
    meta = borders.get(frt_code)
    border_id = meta.get("id") if meta else None
    rep.enviado_quoia_en = datetime.now(timezone.utc)

    if not border_id:
        rep.enviado_quoia_ok = False
        rep.enviado_quoia_error = "Sin border_id en Quoia"
        return False, "sin border_id en Quoia"

    curva = rep.curva_final or [0.0] * 24
    main_readings = [float(v) if v is not None else 0.0 for v in curva]
    respaldo_terceros = getattr(rep, "curva_respaldo_terceros", None)
    if respaldo_terceros:
        # Frontera de terceros (FRONTERAS_TERCEROS) con fila 'Backup' real
        # en el Excel subido -- se usa tal cual, no la fórmula ±1%.
        backup_readings = [float(v) if v is not None else 0.0 for v in respaldo_terceros]
    else:
        # Mismo ±1% que ya usa el Excel manual (excel.py) para "Respaldo" --
        # ahí es una fórmula de Excel (RAND() por celda); acá se calcula una
        # vez por hora al momento de enviar, porque la API espera números fijos.
        backup_readings = [round(v * (1 + random.uniform(-0.01, 0.01)), 4) for v in main_readings]

    try:
        ok = gaia.post_report(border_id, main_readings, backup_readings)
        motivo = None if ok else "Quoia rechazó el envío"
    except Exception as exc:
        ok = False
        motivo = str(exc)

    rep.enviado_quoia_ok = ok
    rep.enviado_quoia_error = motivo
    return ok, motivo


@router.post("/fronteras/{frontera_id}/enviar", response_model=EnviarReporteEnergiaResponse)
def enviar_frontera(
    frontera_id: int, fecha: date = Query(...),
    db: Session = Depends(get_db), _=Depends(get_current_user),
):
    """Envío controlado de UNA sola frontera a Quoia -- pensado para probar
    gaia.post_report() contra Quoia real (nunca se ha hecho, ver ADVERTENCIA
    en gaia_client.py) antes de confiar en el envío masivo (POST /enviar),
    que manda TODAS las fronteras del día de una sola vez. Misma lógica de
    bloqueo y de "ya válido en Quoia" que el envío masivo, escopada a esta
    fila -- así la prueba de mañana refleja fielmente lo que haría el botón
    real.
    """
    front, rep, Modelo = _fila_por_id(db, frontera_id, fecha)
    es_generacion = Modelo is ReporteEnergiaGeneracion

    if rep.revisar_manualmente:
        return EnviarReporteEnergiaResponse(
            fecha=fecha, enviados=0, fallidos=[], bloqueado=True,
            motivo_bloqueo="Esta frontera tiene Revisar Manualmente pendiente.",
        )

    gaia = GaiaClient()
    borders = resolver_borders(gaia, {front.codigo_frontera}) if front.codigo_frontera else {}
    resultado, motivo = _enviar_a_quoia(rep, front, es_generacion, gaia, borders)
    db.commit()

    if resultado is None:
        return EnviarReporteEnergiaResponse(
            fecha=fecha, enviados=0, fallidos=[], bloqueado=False,
            motivo_bloqueo="Quoia ya tenía el dato correcto (CGM válido) -- no hacía falta enviar nada.",
        )
    if resultado is False:
        return EnviarReporteEnergiaResponse(
            fecha=fecha, enviados=0, fallidos=[f"{_nombre_frontera(front)} — {motivo}"], bloqueado=False,
        )
    return EnviarReporteEnergiaResponse(fecha=fecha, enviados=1, fallidos=[], bloqueado=False)


@router.post("/enviar", response_model=EnviarReporteEnergiaResponse)
def enviar(fecha: date = Query(...), db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Envía el reporte del día a Quoia -- bloqueado si queda alguna
    frontera con 'Revisar Manualmente' pendiente (huecos sin fuente).

    Solo se envían las fronteras donde tuvimos que sustituir el dato de
    Quoia (medidor_usado != 'cgm' / caso != 'CGM') -- si el CGM de Quoia ya
    reportó válido por su cuenta, no se toca.
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

    gen_filas = db.execute(
        select(ReporteEnergiaGeneracion, Frontera)
        .join(Frontera, Frontera.id == ReporteEnergiaGeneracion.frontera_id)
        .where(ReporteEnergiaGeneracion.fecha == fecha)
    ).all()
    con_filas = db.execute(
        select(ReporteEnergiaConsumo, Frontera)
        .join(Frontera, Frontera.id == ReporteEnergiaConsumo.frontera_id)
        .where(ReporteEnergiaConsumo.fecha == fecha)
    ).all()

    frt_codes = {f.codigo_frontera for _, f in gen_filas + con_filas if f.codigo_frontera}
    gaia = GaiaClient()
    borders = resolver_borders(gaia, frt_codes) if frt_codes else {}

    enviados = 0
    fallidos: list[str] = []

    def _procesar(rep, front, es_generacion: bool) -> None:
        nonlocal enviados
        resultado, motivo = _enviar_a_quoia(rep, front, es_generacion, gaia, borders)
        if resultado is True:
            enviados += 1
        elif resultado is False:
            fallidos.append(f"{_nombre_frontera(front)} — {motivo}")
        # resultado is None: ya era válido en Quoia, no hacía falta nada

    for rep, front in gen_filas:
        _procesar(rep, front, es_generacion=True)
    for rep, front in con_filas:
        _procesar(rep, front, es_generacion=False)

    db.commit()
    return EnviarReporteEnergiaResponse(fecha=fecha, enviados=enviados, fallidos=fallidos, bloqueado=False)
