"""Proxy a la API de Liquidaciones de Unergy.

El frontend no habla directo con api.unergy.io: las credenciales de la cuenta de
servicio viven solo en el servidor. Estos endpoints cruzan los proyectos de esta
base con su configuración de liquidaciones (códigos SIC/FRT, ac_power y flags).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.proyectos import Proyecto
from app.schemas.liquidaciones_api import (
    CatalogosOut,
    ContratoEnergiaIn,
    ContratoEnergiaOut,
    CostosOut,
    DespachosLiquidadosOut,
    DiagnosticoIn,
    FacturasXmOut,
    IppOut,
    PeriodoIn,
    ProyectoLiquidacionesOut,
    ProyectoLiquidacionesUpdate,
    RepartoIn,
    SubidaFacturasXmOut,
    TareaEstadoOut,
    TareaLanzadaOut,
)
from app.services import liquidaciones_api
from app.services.liquidaciones_api import LiquidacionesAPIError, VersionLiquidacion

router = APIRouter(prefix="/liquidaciones-api", tags=["API Liquidaciones"])


def _nombres_por_topico(db: Session) -> dict[str, str]:
    """Nombre comercial de esta base, indexado por el tópico de la API externa.

    La API identifica los proyectos por ``nombre_topico``; en pantalla se muestra
    el nombre con el que el equipo los conoce.
    """
    return {
        topico: nombre
        for topico, nombre in (
            db.query(Proyecto.sub_project, Proyecto.nombre_comercial)
            .filter(Proyecto.sub_project.isnot(None), Proyecto.deleted_at.is_(None))
            .all()
        )
    }


def _por_topico() -> dict[str, dict]:
    """Configuración de la API externa indexada por ``nombre_topico``."""
    return {
        p["nombre_topico"]: p
        for p in liquidaciones_api.listar_proyectos()
        if p.get("nombre_topico")
    }


@router.get("/proyectos", response_model=list[ProyectoLiquidacionesOut])
def listar_proyectos(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Proyectos de esta base con su configuración de liquidaciones."""
    try:
        config = _por_topico()
    except LiquidacionesAPIError as exc:
        raise HTTPException(503, str(exc))

    proyectos = (
        db.query(Proyecto)
        .filter(Proyecto.deleted_at.is_(None))
        .order_by(Proyecto.nombre_comercial)
        .all()
    )

    salida: list[ProyectoLiquidacionesOut] = []
    for proy in proyectos:
        datos = config.get(proy.sub_project or "", {})
        salida.append(
            ProyectoLiquidacionesOut(
                proyecto_id=proy.id,
                nombre_comercial=proy.nombre_comercial,
                tipo_proyecto=proy.tipo_proyecto,
                estado=proy.estado,
                nombre_topico=proy.sub_project,
                en_api=bool(datos),
                **{campo: datos.get(campo) for campo in liquidaciones_api.CAMPOS_PROYECTO},
            )
        )
    return salida


@router.get("/proyectos/{proyecto_id}", response_model=ProyectoLiquidacionesOut)
def obtener_proyecto(proyecto_id: int, db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Configuración de liquidaciones de un solo proyecto."""
    proy = (
        db.query(Proyecto)
        .filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None))
        .first()
    )
    if not proy:
        raise HTTPException(404, "Proyecto no encontrado")

    datos: dict = {}
    if proy.sub_project:
        try:
            datos = liquidaciones_api.obtener_proyecto(proy.sub_project)
        except LiquidacionesAPIError:
            # El proyecto puede no existir en la API; se devuelve sin configuración.
            datos = {}

    return ProyectoLiquidacionesOut(
        proyecto_id=proy.id,
        nombre_comercial=proy.nombre_comercial,
        tipo_proyecto=proy.tipo_proyecto,
        estado=proy.estado,
        nombre_topico=proy.sub_project,
        en_api=bool(datos),
        **{campo: datos.get(campo) for campo in liquidaciones_api.CAMPOS_PROYECTO},
    )


@router.patch("/proyectos/{proyecto_id}", response_model=ProyectoLiquidacionesOut)
def actualizar_proyecto(
    proyecto_id: int,
    data: ProyectoLiquidacionesUpdate,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Actualiza en la API externa la configuración de liquidaciones del proyecto."""
    proy = (
        db.query(Proyecto)
        .filter(Proyecto.id == proyecto_id, Proyecto.deleted_at.is_(None))
        .first()
    )
    if not proy:
        raise HTTPException(404, "Proyecto no encontrado")
    if not proy.sub_project:
        raise HTTPException(
            400,
            "El proyecto no tiene código base (API ID Unergy) y no se puede "
            "identificar en la API de Liquidaciones.",
        )

    cambios = data.model_dump(exclude_unset=True)
    if not cambios:
        raise HTTPException(400, "No se enviaron campos para actualizar")

    try:
        datos = liquidaciones_api.actualizar_proyecto(proy.sub_project, cambios)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    return ProyectoLiquidacionesOut(
        proyecto_id=proy.id,
        nombre_comercial=proy.nombre_comercial,
        tipo_proyecto=proy.tipo_proyecto,
        estado=proy.estado,
        nombre_topico=proy.sub_project,
        en_api=bool(datos),
        **{campo: datos.get(campo) for campo in liquidaciones_api.CAMPOS_PROYECTO},
    )


# ── Tareas asíncronas ────────────────────────────────────────────────────────

@router.get("/tareas/{task_id}", response_model=TareaEstadoOut)
def estado_tarea(task_id: str, _=Depends(get_current_user)):
    """Estado de una tarea del ciclo, ya normalizado.

    El frontend hace el sondeo (no el servidor): estas tareas tardan minutos y
    dejar una petición HTTP colgada todo ese rato no sirve para una pantalla.
    Ojo: un ``task_id`` inexistente responde ``en_curso`` para siempre, porque la
    API no distingue "en cola" de "no existe" -- quien sondee necesita su propio
    límite de tiempo.
    """
    try:
        return liquidaciones_api.consultar_tarea(task_id)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


# ── Facturas de XM ───────────────────────────────────────────────────────────

@router.get("/facturas-xm", response_model=FacturasXmOut)
def listar_facturas_xm(
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=2020, le=2100),
    version: VersionLiquidacion | None = None,
    processing_status: str | None = None,
    agente: str | None = None,
    _=Depends(get_current_user),
):
    """Facturas de XM del período, con el bloque de alistamiento traducido."""
    try:
        data = liquidaciones_api.listar_facturas_xm(
            month=month,
            year=year,
            version=version.value if version else None,
            processing_status=processing_status,
            agente=agente,
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    r = data.get("readiness") or {}
    return FacturasXmOut(
        count=data.get("count") or 0,
        readiness={
            "lista_para_repartir": bool(r.get("ready_for_distribution")),
            "total": r.get("total") or 0,
            "completadas": r.get("completed") or 0,
            "tiene_factura_generador": bool(r.get("has_generator_invoice")),
            "tiene_factura_comercializador": bool(r.get("has_commercializer_invoice")),
            "bloqueos": r.get("blockers") or [],
            "sin_completar": r.get("not_completed") or [],
            "totales_invalidos": r.get("invalid_totals") or [],
        },
        results=[
            {
                "id": f.get("id"),
                "codigo": f.get("codigo"),
                "nombre": f.get("nombre"),
                "agente": f.get("agente"),
                "mes": f.get("month"),
                "mes_nombre": f.get("month_display"),
                "anio": f.get("year"),
                "version": f.get("version"),
                "periodo_inicio": f.get("periodo_inicio"),
                "periodo_fin": f.get("periodo_fin"),
                "vencimiento": f.get("vencimiento"),
                "procesada_el": f.get("processed_at"),
                "estado_procesamiento": f.get("processing_status"),
                "error": f.get("error_message"),
                "valor_total": f.get("valor_total"),
                "total_declarado": f.get("total_amount"),
                "total_valido": f.get("is_total_valid"),
                "campos_extraidos": f.get("fields_count"),
            }
            for f in (data.get("results") or [])
        ],
    )


@router.post("/facturas-xm", response_model=SubidaFacturasXmOut, status_code=201)
async def subir_facturas_xm(
    files: list[UploadFile] = File(...),
    version: VersionLiquidacion = Form(VersionLiquidacion.TXF),
    _=Depends(get_current_user),
):
    """Sube facturas de XM en PDF. El mes y el año los extrae la IA del PDF.

    El lote se procesa en una tarea asíncrona: el ``task_id`` que se devuelve se
    sondea con ``GET /liquidaciones-api/tareas/{task_id}``.
    """
    if len(files) > liquidaciones_api.MAX_FACTURAS_POR_LOTE:
        raise HTTPException(
            400,
            f"Máximo {liquidaciones_api.MAX_FACTURAS_POR_LOTE} facturas por lote.",
        )

    archivos: list[tuple[str, bytes, str]] = []
    for archivo in files:
        contenido = await archivo.read()
        if len(contenido) > liquidaciones_api.MAX_BYTES_POR_FACTURA:
            raise HTTPException(
                400,
                f"«{archivo.filename}» pesa más de "
                f"{liquidaciones_api.MAX_BYTES_POR_FACTURA // (1024 * 1024)} MB.",
            )
        if not (archivo.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"«{archivo.filename}» no es un PDF.")
        archivos.append((archivo.filename, contenido, archivo.content_type or "application/pdf"))

    try:
        return liquidaciones_api.subir_facturas_xm(archivos, version.value)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


# ── Acciones del ciclo mensual ───────────────────────────────────────────────
# El orden importa: liquidar va ANTES de repartir, y la cadena secuencial es
# liquidar → repartir → estado de resultados → cruce. IPP, FTP y facturas son
# independientes entre sí.

@router.post("/ciclo/ipp", response_model=IppOut)
def consultar_ipp(data: PeriodoIn, _=Depends(get_current_user)):
    """IPP del mes, del DANE. Síncrono: devuelve el valor, no una tarea."""
    try:
        ipp = liquidaciones_api.obtener_ipp(data.month, data.year)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))
    return IppOut(month=data.month, year=data.year, ipp=ipp)


@router.post("/ciclo/ftp", response_model=TareaLanzadaOut)
def descargar_archivos_xm(data: PeriodoIn, _=Depends(get_current_user)):
    """Descarga los ocho archivos del FTP de XM. Requiere los SIC/FRT del proyecto."""
    try:
        return TareaLanzadaOut(
            task_id=liquidaciones_api.descargar_archivos_xm(data.month, data.year, data.version)
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.post("/ciclo/liquidar", response_model=TareaLanzadaOut)
def liquidar(data: PeriodoIn, _=Depends(get_current_user)):
    """Liquida los contratos del período. Requiere el FTP ya descargado."""
    try:
        return TareaLanzadaOut(
            task_id=liquidaciones_api.liquidar_contratos(data.month, data.year, data.version)
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.post("/ciclo/repartir", response_model=TareaLanzadaOut)
def repartir(data: RepartoIn, _=Depends(get_current_user)):
    """Reparte las facturas de XM entre los proyectos, a prorrata del AC Power."""
    try:
        return TareaLanzadaOut(
            task_id=liquidaciones_api.repartir_facturas_xm(
                data.month, data.year, data.total_ac_power,
                data.override, data.version, data.last_version,
            )
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.post("/ciclo/estado-resultados", response_model=TareaLanzadaOut)
def generar_estado_resultados(data: PeriodoIn, _=Depends(get_current_user)):
    """Genera el .xlsx del estado de resultados; queda en la carpeta de Drive."""
    try:
        return TareaLanzadaOut(
            task_id=liquidaciones_api.generar_estado_resultados(data.month, data.year, data.version)
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.post("/ciclo/cruce-facturas", response_model=TareaLanzadaOut)
def generar_cruce_facturas(data: PeriodoIn, _=Depends(get_current_user)):
    """Genera el Excel que verifica que lo repartido cuadre con la factura de XM."""
    try:
        return TareaLanzadaOut(
            task_id=liquidaciones_api.generar_cruce_facturas(data.month, data.year, data.version)
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.post("/ciclo/diagnostico")
def diagnosticar(data: DiagnosticoIn, _=Depends(get_current_user)):
    """Por qué un proyecto no sale en el estado de resultados."""
    try:
        return liquidaciones_api.diagnosticar_proyecto(
            data.project, data.month, data.year, data.version
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


# ── Despachos liquidados ─────────────────────────────────────────────────────

@router.get("/despachos", response_model=DespachosLiquidadosOut)
def listar_despachos(
    month: int = Query(..., ge=1, le=12),
    year: int = Query(..., ge=2020, le=2100),
    version: VersionLiquidacion = VersionLiquidacion.TXF,
    _=Depends(get_current_user),
):
    """Líneas de ingreso ya liquidadas del período.

    La API no expone un listado crudo de MarketSettlement, así que la tabla se
    arma con el detalle de ingresos del estado de resultados: es el mismo dato
    liquidado, agregado por proyecto y concepto.
    """
    try:
        data = liquidaciones_api.estado_resultados_json(month, year, version.value)
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    proyectos = data.get("results") or []
    filas = [
        {
            "proyecto": p.get("project"),
            "proyecto_nombre": p.get("project_name"),
            "concepto": d.get("concepto"),
            "tipo_dato": d.get("data_type"),
            "energia_kwh": d.get("energia_kwh"),
            "valor": d.get("valor"),
            "version": p.get("version"),
        }
        for p in proyectos
        for d in (p.get("ingresos_detalle") or [])
    ]
    avisos = [
        {"proyecto": p.get("project_name") or p.get("project"), "avisos": p["warnings"]}
        for p in proyectos
        if p.get("warnings")
    ]
    return DespachosLiquidadosOut(count=len(filas), results=filas, avisos=avisos)


# ── Costos e ingresos fijos ──────────────────────────────────────────────────

@router.get("/costos", response_model=CostosOut)
def listar_costos(
    project: str | None = None,
    payment_type: str | None = None,
    version: VersionLiquidacion | None = None,
    grupo: liquidaciones_api.GrupoCosto | None = None,
    mes: int | None = Query(None, ge=1, le=12),
    anio: int | None = Query(None, ge=2020, le=2100),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=5000),
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    """Costos e ingresos fijos por proyecto, paginados.

    La API externa devuelve la tabla completa (más de 10.000 filas) sin paginar,
    así que el corte se hace aquí para no mandarle eso al navegador. Por lo mismo
    el filtro por ``grupo`` se aplica antes de paginar: si no, ``total`` contaría
    filas que la página no muestra.
    """
    try:
        # `payment_type` NO se le manda a la API externa: filtrarlo allá devuelve
        # 500 (bug de ellos, la guía lo documenta como soportado). Se aplica aquí,
        # que además sale gratis porque el listado ya viene cacheado.
        filas = liquidaciones_api.listar_costos(
            project=project,
            version=version.value if version else None,
        )
        tipos = {t["name"]: t for t in liquidaciones_api.listar_catalogos()["tipos_costo"]}
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    if payment_type:
        filas = [c for c in filas if c.get("payment_type") == payment_type]

    if grupo is not None:
        filas = [
            c for c in filas
            if (tipos.get(c.get("payment_type") or "") or {}).get("group") == grupo.value
        ]

    # Período: se queda el costo cuya vigencia se cruza con el mes/año pedido.
    # Un costo anual cubre doce meses, así que basta con que haya traslape.
    if anio is not None:
        desde = f"{anio}-{mes:02d}-01" if mes else f"{anio}-01-01"
        hasta = f"{anio}-{mes:02d}-31" if mes else f"{anio}-12-31"
        filas = [
            c for c in filas
            if (c.get("from_date") or "0000-01-01") <= hasta
            and (c.get("to_date") or "9999-12-31") >= desde
        ]

    # Lo más reciente primero: es lo que se está liquidando.
    filas.sort(key=lambda c: (c.get("from_date") or ""), reverse=True)

    nombres = _nombres_por_topico(db)
    inicio = (page - 1) * size
    return CostosOut(
        total=len(filas),
        page=page,
        size=size,
        results=[
            {
                "id": c.get("id"),
                # Nombre de esta base; si el tópico no cruza, se deja el tópico.
                "proyecto": nombres.get(c.get("project") or "") or c.get("project"),
                "tipo_pago": c.get("payment_type"),
                "tipo_pago_nombre": (tipos.get(c.get("payment_type") or "") or {}).get("long_name"),
                "grupo": (tipos.get(c.get("payment_type") or "") or {}).get("group"),
                "valor": float(c["value"]) if c.get("value") is not None else None,
                "fecha_desde": c.get("from_date"),
                "fecha_hasta": c.get("to_date"),
                "frecuencia_pago": c.get("payment_frecuency"),
                "version": c.get("version"),
            }
            for c in filas[inicio:inicio + size]
        ],
    )


# ── Contratos de energía ─────────────────────────────────────────────────────

@router.get("/catalogos", response_model=CatalogosOut)
def listar_catalogos(_=Depends(get_current_user)):
    """Empresas, precios de energía y tipos de costo. Son datos fijos."""
    try:
        return liquidaciones_api.listar_catalogos()
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))


@router.get("/contratos-energia", response_model=list[ContratoEnergiaOut])
def listar_contratos_energia(db: Session = Depends(get_db), _=Depends(get_current_user)):
    """Contratos de energía con sus proyectos vinculados.

    Se marca por proyecto si ya tiene piso y techo: un contrato PLC sin los dos
    hace fallar la liquidación, y hoy no hay dónde verlo.
    """
    try:
        contratos = liquidaciones_api.listar_contratos()
        vinculos = liquidaciones_api.listar_contrato_proyectos()
        cantidades = liquidaciones_api.listar_cantidades()
        catalogos = liquidaciones_api.listar_catalogos()
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    nombres = _nombres_por_topico(db)
    empresas = {e["id"]: e.get("nombre_empresa") for e in catalogos["empresas"]}
    precios = {p["id"]: p.get("name") for p in catalogos["precios_energia"]}

    conceptos: dict[int, set[str]] = {}
    for c in cantidades:
        conceptos.setdefault(c.get("contract_energy_project"), set()).add(c.get("concept_type"))

    por_contrato: dict[int, list[dict]] = {}
    for v in vinculos:
        tipos = conceptos.get(v.get("id"), set())
        por_contrato.setdefault(v.get("contract_energy"), []).append({
            "id": v.get("id"),
            # Nombre de esta base; si el tópico no cruza, se deja el tópico.
            "proyecto": nombres.get(v.get("project") or "") or v.get("project"),
            "precio_energia_id": v.get("energy_price"),
            "precio_energia": precios.get(v.get("energy_price")),
            "tiene_piso": "floor" in tipos,
            "tiene_techo": "roof" in tipos,
        })

    return [
        ContratoEnergiaOut(
            id=c["id"],
            fecha_desde=c.get("date_from"),
            fecha_hasta=c.get("date_to"),
            codigo=c.get("code"),
            tipo_contrato=c.get("contract_type"),
            tipo_tarifa=c.get("tariff_price_type"),
            porcentaje=c.get("percentage"),
            empresa_id=c.get("company"),
            empresa=empresas.get(c.get("company")),
            proyectos=por_contrato.get(c["id"], []),
        )
        for c in contratos
    ]


@router.post("/contratos-energia", response_model=ContratoEnergiaOut, status_code=201)
def crear_contrato_energia(data: ContratoEnergiaIn, _=Depends(get_current_user)):
    """Crea el contrato, lo vincula a sus proyectos y carga sus pisos y techos.

    Va en ese orden porque cada paso necesita el id que devuelve el anterior. La
    API externa no ofrece transacción: si un vínculo falla se informa qué alcanzó
    a crearse, en vez de dejar un contrato huérfano en silencio.
    """
    try:
        contrato = liquidaciones_api.crear_contrato(
            data.model_dump(exclude={"proyectos"}, exclude_none=True)
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))

    creados: list[dict] = []
    for proy in data.proyectos:
        try:
            vinculo = liquidaciones_api.vincular_contrato_proyecto({
                "contract_energy": contrato["id"],
                "project": proy.project,
                **({"energy_price": proy.energy_price} if proy.energy_price is not None else {}),
            })
            for concepto, horas in (("floor", proy.floor), ("roof", proy.roof)):
                if horas:
                    liquidaciones_api.crear_cantidades({
                        "contract_energy_project": vinculo["id"],
                        "concept_type": concepto,
                        "hours": horas,
                    })
        except LiquidacionesAPIError as exc:
            raise HTTPException(
                502,
                f"El contrato {contrato['id']} se creó, pero falló al vincular "
                f"«{proy.project}»: {exc}. Alcanzaron a vincularse {len(creados)}.",
            )
        creados.append({
            "id": vinculo["id"],
            "proyecto": proy.project,
            "precio_energia_id": proy.energy_price,
            "tiene_piso": bool(proy.floor),
            "tiene_techo": bool(proy.roof),
        })

    return ContratoEnergiaOut(
        id=contrato["id"],
        fecha_desde=contrato.get("date_from"),
        fecha_hasta=contrato.get("date_to"),
        codigo=contrato.get("code"),
        tipo_contrato=contrato.get("contract_type"),
        tipo_tarifa=contrato.get("tariff_price_type"),
        porcentaje=contrato.get("percentage"),
        empresa_id=contrato.get("company"),
        empresa=None,
        proyectos=creados,
    )


@router.post("/costos/excel")
async def subir_excel_costos(
    file: UploadFile = File(...),
    _=Depends(get_current_user),
):
    """Carga masiva de costos e ingresos fijos desde un Excel."""
    if not (file.filename or "").lower().endswith((".xlsx", ".xls")):
        raise HTTPException(400, f"«{file.filename}» no es un Excel.")
    contenido = await file.read()
    try:
        return liquidaciones_api.subir_excel_costos(
            file.filename,
            contenido,
            file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except LiquidacionesAPIError as exc:
        raise HTTPException(502, str(exc))
