from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente
from app.models.fronteras import Frontera
from app.models.operadores_red import OperadorRed
from app.schemas.reporte_cgm import (
    EnviarReporteCGMRequest, EnviarReporteCGMResponse, EnvioResultado,
)
from app.services import email_service
from app.services import reporte_cgm as svc
from app.services.contactos import get_contactos, get_proyecto_ids_por_contacto_cliente
from app.services.mgs.gaia_client import GaiaClient

router = APIRouter(prefix="/reporte-cgm", tags=["Reporte CGM"])


def _fronteras_de_operador(db: Session, operador_id: int) -> list[Frontera]:
    return (
        db.query(Frontera)
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.operador_red_id == operador_id, Frontera.deleted_at.is_(None))
        .all()
    )


def _fronteras_de_cliente(db: Session, cliente_id: int) -> list[Frontera]:
    """Fronteras de los proyectos donde este cliente es la fuente del contacto
    CGM (por puntero de área, o por ser inversionista vigente) -- no depende
    de quién sea el titular del proyecto."""
    proyecto_ids = get_proyecto_ids_por_contacto_cliente(db, "cgm", cliente_id)
    if not proyecto_ids:
        return []
    return (
        db.query(Frontera)
        .options(joinedload(Frontera.proyecto))
        .filter(Frontera.proyecto_id.in_(proyecto_ids), Frontera.deleted_at.is_(None))
        .all()
    )


def _nombres_proyectos(fronteras: list[Frontera]) -> list[str]:
    """Nombres únicos de proyecto entre estas fronteras (una misma planta
    suele tener frontera de Generación y de Consumo por separado)."""
    vistos: dict[int, str] = {}
    for f in fronteras:
        if f.proyecto and f.proyecto_id not in vistos:
            vistos[f.proyecto_id] = f.proyecto.nombre_comercial
    return sorted(vistos.values())


@router.post("/enviar", response_model=EnviarReporteCGMResponse)
def enviar_reporte_cgm(
    body: EnviarReporteCGMRequest,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    if body.fecha_fin < body.fecha_inicio:
        body.fecha_inicio, body.fecha_fin = body.fecha_fin, body.fecha_inicio

    dias = [
        (body.fecha_inicio + timedelta(days=i)).isoformat()
        for i in range((body.fecha_fin - body.fecha_inicio).days + 1)
    ]
    fecha_display = dias[0] if len(dias) == 1 else f"{dias[0]} a {dias[-1]}"
    fecha_archivo = dias[0] if len(dias) == 1 else f"{dias[0]}_a_{dias[-1]}"

    # Consolidado mensual: cuando el envío es de un solo día Y ese día es el
    # último del mes, se adjunta ADEMÁS (no en vez de) un segundo Excel con
    # todo el mes -- solo para Operador de Red por ahora. dias_mes ya incluye
    # dias[0], así que se pide a Quoia una sola vez (superset).
    mensual_activo = len(dias) == 1 and svc.es_ultimo_dia_del_mes(body.fecha_inicio)
    dias_fetch = svc.dias_del_mes(body.fecha_inicio) if mensual_activo else dias

    # 1. Resolver, desde la BD, a quién le llega qué (nunca se confía en datos
    #    del frontend más allá de tipo+id).
    items: list[dict] = []
    for dest in body.destinatarios:
        if dest.tipo == "operador":
            operador = db.query(OperadorRed).options(joinedload(OperadorRed.contactos)).filter(
                OperadorRed.id == dest.id
            ).first()
            if not operador:
                items.append({"dest": dest, "nombre": f"Operador #{dest.id}", "correos": [], "fronteras": []})
                continue
            fronteras = _fronteras_de_operador(db, dest.id)
            correos = [c.email for c in operador.contactos]
            nombre = operador.nombre_comercial or operador.nombre_legal
        else:
            cliente = db.query(Cliente).filter(Cliente.id == dest.id).first()
            if not cliente:
                items.append({"dest": dest, "nombre": f"Cliente #{dest.id}", "correos": [], "fronteras": []})
                continue
            fronteras = _fronteras_de_cliente(db, dest.id)
            correos = get_contactos(db, "cgm", cliente_id=dest.id)
            nombre = cliente.razon_social_nombre

        proyectos_total = len(_nombres_proyectos(fronteras))

        # Filtro opcional a proyectos puntuales dentro de este destinatario --
        # el frontend siempre manda la selección explícita (nunca None), pero
        # se respeta None por si algún otro consumidor de la API no lo manda.
        if dest.proyectos is not None:
            proyectos_ids = set(dest.proyectos)
            fronteras = [f for f in fronteras if f.proyecto_id in proyectos_ids]

        items.append({
            "dest": dest, "nombre": nombre, "correos": correos, "fronteras": fronteras,
            "proyectos_total": proyectos_total,
        })

    # 2. Un solo lote de llamadas a Quoia -- solo los frt_codes que realmente
    #    hacen falta para esta request, dedupeados entre todos los destinatarios.
    frt_codes: set[str] = set()
    for item in items:
        for f in item["fronteras"]:
            if f.codigo_frontera:
                frt_codes.add(f.codigo_frontera)

    filas_por_frt: dict[str, list[dict]] = {}
    if frt_codes:
        gaia = GaiaClient()
        borders = svc.resolver_borders(gaia, frt_codes)
        for frt_code in frt_codes:
            meta = borders.get(frt_code.lower())
            if meta is None:
                # No aparece en el listado de Quoia (caso real 2026-07-10:
                # Bayunca/San Onofre registrados ahí bajo otra compañía) --
                # no hay nombre ni dato real que reportar, así que no se
                # incluye ninguna fila para este frt_code. Distinto del caso
                # "sí está en Quoia pero no reportó este día" (eso sí se deja
                # como "Sin reporte" dentro de fetch_filas).
                continue
            filas_por_frt[frt_code] = [
                fila
                for dia in dias_fetch
                for fila in svc.fetch_filas(gaia, frt_code, meta, dia)
            ]

    # 3. Generar y enviar un Excel por destinatario, filtrado a sus fronteras.
    resultados = []
    for item in items:
        dest, nombre, correos, fronteras = item["dest"], item["nombre"], item["correos"], item["fronteras"]
        proyectos_total = item.get("proyectos_total", 0)

        if not fronteras:
            resultados.append(EnvioResultado(
                tipo=dest.tipo, id=dest.id, nombre=nombre, correos=correos, fronteras=0,
                ok=False, error="No hay fronteras vinculadas",
            ))
            continue
        if not correos:
            resultados.append(EnvioResultado(
                tipo=dest.tipo, id=dest.id, nombre=nombre, correos=[], fronteras=len(fronteras),
                ok=False, error="Sin correos configurados",
            ))
            continue

        filas_todas = [
            fila
            for f in fronteras if f.codigo_frontera
            for fila in filas_por_frt.get(f.codigo_frontera, [])
        ]
        # Cuando mensual_activo, filas_todas trae todo el mes (dias_fetch) --
        # el Excel diario de siempre se queda solo con el día pedido.
        dias_set = set(dias)
        filas = [f for f in filas_todas if f["report date"] in dias_set] if mensual_activo else filas_todas

        try:
            excel_bytes = svc.generar_excel(filas)
            slug = "".join(c if c.isalnum() else "_" for c in nombre.lower()).strip("_")

            excel_mensual_bytes = filename_mensual = mes_str = None
            if mensual_activo and dest.tipo == "operador":
                excel_mensual_bytes = svc.generar_excel(
                    filas_todas, titulo_hoja=svc.titulo_hoja_mensual(body.fecha_inicio),
                )
                filename_mensual = f"cgm-report-consolidado-{body.fecha_inicio.strftime('%Y-%m')}-{slug}.xlsx"
                mes_str = svc.nombre_mes(body.fecha_inicio)

            email_service.send_reporte_cgm_email(
                to_emails=correos,
                excel_bytes=excel_bytes,
                filename=f"cgm-report-{fecha_archivo}-{slug}.xlsx",
                fecha_str=fecha_display,
                destinatario_nombre=nombre,
                proyectos=_nombres_proyectos(fronteras),
                proyectos_total=proyectos_total,
                excel_mensual_bytes=excel_mensual_bytes,
                filename_mensual=filename_mensual,
                mes_str=mes_str,
            )
            resultados.append(EnvioResultado(
                tipo=dest.tipo, id=dest.id, nombre=nombre, correos=correos,
                fronteras=len(fronteras), ok=True,
            ))
        except Exception as exc:
            resultados.append(EnvioResultado(
                tipo=dest.tipo, id=dest.id, nombre=nombre, correos=correos,
                fronteras=len(fronteras), ok=False, error=str(exc),
            ))

    return EnviarReporteCGMResponse(resultados=resultados)
