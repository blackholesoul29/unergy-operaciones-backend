from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.api.v1.auth import get_current_user
from app.models import Cliente
from app.models.fronteras import Frontera, TipoFronteraEnum
from app.models.operadores_red import OperadorRed
from app.models.proyectos import ProyectoInfoTecnica
from app.schemas.reporte_cgm import (
    EnviarReporteCGMRequest, EnviarReporteCGMResponse, EnvioResultado,
)
from app.services import email_service
from app.services import reporte_cgm as svc
from app.services.contactos import get_contactos, get_proyecto_ids_por_contacto_cliente
from app.services.mgs.gaia_client import GaiaClient
from app.services.reporte_energia import curvas as curvas_energia

router = APIRouter(prefix="/reporte-cgm", tags=["Reporte CGM"])

_TIPOS_CONSUMO = {TipoFronteraEnum.consumo, TipoFronteraEnum.consumo_auxiliar, TipoFronteraEnum.consumo_propio}

# cliente_id -- pedido puntual: un Excel de Cliente (3 hojas) POR PROYECTO en
# vez de uno combinado, todos adjuntos al mismo correo. 75 = CGM Ingeniería
# (proyectos: GD San Pelayo, GD La Hormiguita). No requiere cambios en el
# front -- se decide acá por el id del cliente.
CLIENTES_EXCEL_POR_PROYECTO: set[int] = {75}


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


def _datos_proyectos_para_resumen(
    db: Session, gaia: GaiaClient, fronteras: list[Frontera],
) -> dict[int, dict]:
    """Arma el dict proyecto_id -> {...} que necesita
    svc.calcular_resumen_mensual() (Hoja 2 de Clientes) -- agrupa las
    fronteras de ESTE destinatario por proyecto, separando cuál es la de
    Generación (para medidor/capacidad_efectiva) y cuál la de Consumo."""
    proyecto_ids = {f.proyecto_id for f in fronteras if f.proyecto_id}
    if not proyecto_ids:
        return {}

    capacidad_dc: dict[int, float | None] = dict(db.query(
        ProyectoInfoTecnica.proyecto_id, ProyectoInfoTecnica.capacidad_instalada_kwp,
    ).filter(ProyectoInfoTecnica.proyecto_id.in_(proyecto_ids)).all())

    mapa_borders = curvas_energia.construir_mapa_borders(gaia)

    proyectos: dict[int, dict] = {}
    for f in fronteras:
        if not f.proyecto_id or not f.proyecto:
            continue
        datos = proyectos.setdefault(f.proyecto_id, {
            "nombre": f.proyecto.nombre_comercial,
            "frt_gen": None, "frt_con": None,
            "capacidad_dc_kwp": capacidad_dc.get(f.proyecto_id),
            "capacidad_efectiva_mw": None,
            "main_meter_gen": None, "backup_meter_gen": None,
            "main_meter_con": None, "backup_meter_con": None,
        })
        meta = mapa_borders.get(f.codigo_frontera.strip().lower()) if f.codigo_frontera else None
        if f.tipo_frontera == TipoFronteraEnum.generacion and f.codigo_frontera:
            datos["frt_gen"] = f.codigo_frontera
            datos["capacidad_efectiva_mw"] = f.capacidad_efectiva_mw
            if meta:
                datos["main_meter_gen"] = meta.get("main_meter")
                datos["backup_meter_gen"] = meta.get("backup_meter")
        elif f.tipo_frontera in _TIPOS_CONSUMO and f.codigo_frontera:
            # consumo_auxiliar/consumo_propio son el autoconsumo de la misma
            # planta de generación (ej. Sol&Cielo 7 Los Bongos) -- cuentan
            # igual como "Total Consumo" para este resumen, no solo 'consumo'.
            datos["frt_con"] = f.codigo_frontera
            if meta:
                datos["main_meter_con"] = meta.get("main_meter")
                datos["backup_meter_con"] = meta.get("backup_meter")
    return proyectos


def _excels_cliente_por_proyecto(
    db: Session, gaia: GaiaClient, fronteras: list[Frontera], filas_por_frt: dict[str, list[dict]],
    dias: list[str], dias_mes: list[str], es_ultimo_dia_mes: bool, fecha_inicio, fecha_archivo: str,
) -> list[tuple[bytes, str]]:
    """Igual que la rama normal de Cliente (3 hojas: Reporte Acumulado +
    Resumen Diario + Resumen Mensual si aplica), pero un Excel POR proyecto
    en vez de uno combinado -- agrupa `fronteras` (ya filtradas a este
    destinatario) por proyecto_id. Ver CLIENTES_EXCEL_POR_PROYECTO."""
    por_proyecto: dict[int, list[Frontera]] = {}
    for f in fronteras:
        if f.proyecto_id:
            por_proyecto.setdefault(f.proyecto_id, []).append(f)

    adjuntos: list[tuple[bytes, str]] = []
    for fronteras_proyecto in por_proyecto.values():
        proyectos = _datos_proyectos_para_resumen(db, gaia, fronteras_proyecto)
        filas_todas_proyecto = [
            fila for f in fronteras_proyecto if f.codigo_frontera for fila in filas_por_frt.get(f.codigo_frontera, [])
        ]
        filas_resumen_diario = svc.calcular_resumen_diario(gaia, proyectos, filas_por_frt, dias[0])
        filas_resumen_mensual = None
        if es_ultimo_dia_mes:
            mes_titulo = f"{svc.nombre_mes(fecha_inicio).capitalize()} {fecha_inicio.year}"
            filas_resumen_mensual = svc.calcular_resumen_mensual(gaia, proyectos, filas_por_frt, dias_mes, mes_titulo)
        excel_bytes = svc.generar_excel_cliente(filas_todas_proyecto, filas_resumen_diario, filas_resumen_mensual)

        nombre_proyecto = fronteras_proyecto[0].proyecto.nombre_comercial
        slug_proyecto = "".join(c if c.isalnum() else "_" for c in nombre_proyecto.lower()).strip("_")
        adjuntos.append((excel_bytes, f"cgm-report-{fecha_archivo}-{slug_proyecto}.xlsx"))
    return adjuntos


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

    # Envío de un solo día -- dispara cosas distintas, cada una acotada a su
    # tipo de destinatario:
    #  - Operador de Red: SOLO si además ese día es el último del mes, se
    #    adjunta ADEMÁS (no en vez de) un segundo Excel con todo el mes.
    #  - Cliente: el reporte diario mismo pasa a tener tres hojas -- 'Diario
    #    acumulado' (desde el día 1 del mes hasta hoy) y 'Resumen Diario'
    #    (mismas variables del resumen, solo de hoy) TODOS los días; 'Resumen
    #    Mensual' (las mismas variables pero acumuladas del mes completo)
    #    únicamente el último día del mes.
    # dias_mes ya incluye dias[0], así que en ambos casos se pide a Quoia una
    # sola vez (superset) en vez de dos.
    es_dia_unico = len(dias) == 1
    dias_mes = svc.dias_del_mes(body.fecha_inicio) if es_dia_unico else []
    es_ultimo_dia_mes = es_dia_unico and svc.es_ultimo_dia_del_mes(body.fecha_inicio)
    dias_fetch = dias_mes if es_dia_unico else dias

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

    gaia = GaiaClient()
    filas_por_frt: dict[str, list[dict]] = {}
    if frt_codes:
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
        # filas_todas trae todo el mes cuando es_dia_unico (dias_fetch =
        # dias_mes) -- filas_dia se queda solo con el día pedido, que es lo
        # que usa Operador de Red siempre y Cliente solo si pidió un rango
        # explícito (no un solo día, ver más abajo).
        dias_set = set(dias)
        filas_dia = [f for f in filas_todas if f["report date"] in dias_set] if es_dia_unico else filas_todas

        try:
            slug = "".join(c if c.isalnum() else "_" for c in nombre.lower()).strip("_")
            excel_mensual_bytes = filename_mensual = mes_str = None
            adjuntos_extra: list[tuple[bytes, str]] = []
            filename_principal = f"cgm-report-{fecha_archivo}-{slug}.xlsx"
            fecha_str_envio = fecha_display

            if dest.tipo == "cliente" and es_dia_unico and dest.id in CLIENTES_EXCEL_POR_PROYECTO:
                # Pedido puntual (ver CLIENTES_EXCEL_POR_PROYECTO): un Excel
                # por proyecto en vez de uno combinado, todos en el mismo
                # correo -- el primero se manda como adjunto principal, el
                # resto como adjuntos_extra.
                adjuntos = _excels_cliente_por_proyecto(
                    db, gaia, fronteras, filas_por_frt, dias, dias_mes, es_ultimo_dia_mes,
                    body.fecha_inicio, fecha_archivo,
                )
                excel_bytes, filename_principal = adjuntos[0]
                adjuntos_extra = adjuntos[1:]
                fecha_str_envio = f"{dias_mes[0]} a {dias_mes[-1]}"
            elif dest.tipo == "cliente" and es_dia_unico:
                # Cliente: 'Reporte Acumulado' (mes completo hasta hoy) +
                # 'Resumen Diario' (mismas variables, solo hoy) siempre;
                # 'Resumen Mensual' (acumulado del mes) solo el último día.
                proyectos = _datos_proyectos_para_resumen(db, gaia, fronteras)
                filas_resumen_diario = svc.calcular_resumen_diario(
                    gaia, proyectos, filas_por_frt, dias[0],
                )
                filas_resumen_mensual = None
                if es_ultimo_dia_mes:
                    mes_titulo = f"{svc.nombre_mes(body.fecha_inicio).capitalize()} {body.fecha_inicio.year}"
                    filas_resumen_mensual = svc.calcular_resumen_mensual(
                        gaia, proyectos, filas_por_frt, dias_mes, mes_titulo,
                    )
                excel_bytes = svc.generar_excel_cliente(filas_todas, filas_resumen_diario, filas_resumen_mensual)
                fecha_str_envio = f"{dias_mes[0]} a {dias_mes[-1]}"
            else:
                excel_bytes = svc.generar_excel(filas_dia)
                if es_ultimo_dia_mes and dest.tipo == "operador":
                    excel_mensual_bytes = svc.generar_excel(
                        filas_todas, titulo_hoja=svc.titulo_hoja_mensual(body.fecha_inicio),
                    )
                    filename_mensual = f"cgm-report-consolidado-{body.fecha_inicio.strftime('%Y-%m')}-{slug}.xlsx"
                    mes_str = svc.nombre_mes(body.fecha_inicio)

            email_service.send_reporte_cgm_email(
                to_emails=correos,
                excel_bytes=excel_bytes,
                filename=filename_principal,
                fecha_str=fecha_str_envio,
                destinatario_nombre=nombre,
                proyectos=_nombres_proyectos(fronteras),
                proyectos_total=proyectos_total,
                excel_mensual_bytes=excel_mensual_bytes,
                filename_mensual=filename_mensual,
                mes_str=mes_str,
                adjuntos_extra=adjuntos_extra,
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
