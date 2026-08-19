"""Cliente de la API de Liquidaciones de Unergy (api.unergy.io).

Los datos maestros que usa el ciclo de liquidaciones -- códigos SIC/FRT,
``ac_power`` y los flags de generador/comercializador -- viven en esa API y no
en esta base de datos. Este módulo es el único punto que habla HTTP con ella.

Particularidades de la API, verificadas contra producción:

* La autenticación es ``POST /api/accounts/<account_id>/`` con login+password y
  devuelve un JWT de acceso. Un 401 posterior significa token vencido: hay que
  renovarlo y reintentar, no es "sin datos".
* Rechaza clientes sin un ``User-Agent`` conocido, así que se envía uno fijo.
* ``/api/admin/*`` exige ``is_staff`` y ``/api/liquidaciones/*`` pertenecer al
  grupo ``admin``; la cuenta de servicio debe cumplir ambos.
"""
import logging
import threading
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("liquidaciones_api")

# Rutas de la API externa (sin hardcodearlas en los endpoints que las consumen).
PATH_LOGIN = "/api/accounts/{account_id}/"
PATH_PROYECTOS = "/api/admin/project/"
PATH_PROYECTO = "/api/admin/project/{topico}/"
PATH_TAREA = "/api/liquidaciones/task_status/{task_id}/"
PATH_FACTURAS_XM = "/api/liquidaciones/xm-invoices/"

# Datos maestros (3 de la guia).
PATH_CONTRATOS = "/api/liquidaciones/contract_energies/"
PATH_CONTRATO_PROYECTOS = "/api/liquidaciones/contract_energy_projects/"
PATH_CANTIDADES = "/api/liquidaciones/energy_contract_quantities/"
PATH_COSTOS = "/api/liquidaciones/revenue_and_costs/"
PATH_COSTOS_XLSX = "/api/liquidaciones/create_revenue_and_cost_xlsx/"

# Catalogos, solo lectura (3.7).
PATH_TIPOS_COSTO = "/api/liquidaciones/revenue_and_cost_types/"
PATH_EMPRESAS = "/api/liquidaciones/companies/"
PATH_PRECIOS_ENERGIA = "/api/liquidaciones/energy_prices/"

# Ciclo mensual (4). OJO: los tres sin slash final dan 404 si se les agrega.
PATH_IPP = "/api/liquidaciones/fetch_monthly_ipp"
PATH_FTP = "/api/liquidaciones/fetch_data_from_xm"
PATH_REPARTIR = "/api/liquidaciones/set_xm_variables_from_processed_invoices"
PATH_LIQUIDAR = "/api/liquidaciones/calculate_project_market_settlement/"
PATH_ESTADO_RESULTADOS_JSON = "/api/liquidaciones/income_statement_data/"
PATH_ESTADO_RESULTADOS_XLSX = "/api/liquidaciones/get_income_statement/"
PATH_CRUCE_FACTURAS = "/api/liquidaciones/cross_invoice_report/"
PATH_DIAGNOSTICO = "/api/liquidaciones/check_income_statement/"


class VersionLiquidacion(str, Enum):
    """Versión del ciclo: ``txf`` es la liquidación inicial, ``tx3``..``tx8`` las
    reliquidaciones que publica XM."""

    TXF = "txf"
    TX3 = "tx3"
    TX4 = "tx4"
    TX5 = "tx5"
    TX6 = "tx6"
    TX7 = "tx7"
    TX8 = "tx8"


class EstadoTarea(str, Enum):
    """Estado normalizado de una tarea asíncrona.

    La API cruda tiene seis estados de Celery y, además, tareas que atrapan sus
    errores y responden ``SUCCESS`` con ``result.success = False``. Aquí se
    colapsa todo a tres, para que quien consuma no tenga que recordar esa trampa.
    """

    EN_CURSO = "en_curso"
    EXITO = "exito"
    FALLO = "fallo"


# Estados de Celery que ya no van a cambiar.
_ESTADOS_TERMINALES = {"SUCCESS", "FAILURE", "REVOKED"}

# Campos de configuración del proyecto que expone esta integración (§3.1 de la
# guía). Se listan explícitamente porque el recurso trae ~65 campos y solo estos
# intervienen en el ciclo de liquidaciones.
CAMPOS_PROYECTO = (
    "sic_gen",
    "sic_con",
    "frt_gen",
    "frt_con",
    "ac_power",
    "from_generator",
    "from_commercializer",
)

_TIMEOUT = httpx.Timeout(15.0, read=60.0)
_USER_AGENT = "PostmanRuntime/7.50.0"

_token: str | None = None
_token_lock = threading.Lock()


class LiquidacionesAPIError(RuntimeError):
    """Falla al comunicarse con la API de Liquidaciones."""


def _credenciales() -> tuple[str, str]:
    """Credenciales de la cuenta de servicio, con respaldo en las de UNERGY_*."""
    login = settings.LIQUIDACIONES_LOGIN or settings.UNERGY_LOGIN
    password = settings.LIQUIDACIONES_PASSWORD or settings.UNERGY_PASSWORD
    if not (login and password and settings.UNERGY_ACCOUNT_ID):
        raise LiquidacionesAPIError(
            "Faltan credenciales: configura LIQUIDACIONES_LOGIN, "
            "LIQUIDACIONES_PASSWORD y UNERGY_ACCOUNT_ID."
        )
    return login, password


def _url(path: str) -> str:
    return f"{settings.UNERGY_API_URL.rstrip('/')}{path}"


def _login() -> str:
    """Pide un token nuevo y lo deja cacheado en el módulo."""
    global _token
    login, password = _credenciales()
    url = _url(PATH_LOGIN.format(account_id=settings.UNERGY_ACCOUNT_ID))
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                url,
                json={"login": login, "password": password},
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            token = resp.json()["access"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.exception("No se pudo autenticar contra la API de Liquidaciones")
        raise LiquidacionesAPIError("No se pudo autenticar contra la API de Liquidaciones") from exc

    _token = token
    return token


def _request(method: str, path: str, **kwargs: Any) -> Any:
    """Ejecuta la llamada renovando el token una sola vez si expiró (401)."""
    global _token

    with _token_lock:
        token = _token or _login()

    def _enviar(bearer: str) -> httpx.Response:
        with httpx.Client(timeout=_TIMEOUT) as client:
            return client.request(
                method,
                _url(path),
                headers={"Authorization": f"Bearer {bearer}", "User-Agent": _USER_AGENT},
                **kwargs,
            )

    try:
        resp = _enviar(token)
        if resp.status_code == 401:
            with _token_lock:
                token = _login()
            resp = _enviar(token)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "API de Liquidaciones respondió %s en %s", exc.response.status_code, path
        )
        raise LiquidacionesAPIError(
            f"La API de Liquidaciones respondió {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        logger.exception("Error de red hablando con la API de Liquidaciones")
        raise LiquidacionesAPIError("No se pudo contactar la API de Liquidaciones") from exc

    if not resp.content:
        return None
    try:
        return resp.json()
    except ValueError as exc:
        raise LiquidacionesAPIError("La API de Liquidaciones devolvió una respuesta no JSON") from exc


def _proyectar(proyecto: dict[str, Any]) -> dict[str, Any]:
    """Deja solo el identificador y los campos del ciclo de liquidaciones."""
    datos = {campo: proyecto.get(campo) for campo in CAMPOS_PROYECTO}
    datos["nombre_topico"] = proyecto.get("nombre_topico")
    datos["nombre_proyecto"] = proyecto.get("nombre_proyecto")
    return datos


def listar_proyectos() -> list[dict[str, Any]]:
    """Configuración de liquidaciones de todos los proyectos, en una sola llamada."""
    data = _request("GET", PATH_PROYECTOS)
    if not isinstance(data, list):
        raise LiquidacionesAPIError("Se esperaba una lista de proyectos")
    return [_proyectar(p) for p in data]


def obtener_proyecto(topico: str) -> dict[str, Any]:
    """Configuración de liquidaciones de un solo proyecto, por su tópico."""
    data = _request("GET", PATH_PROYECTO.format(topico=topico))
    return _proyectar(data) if isinstance(data, dict) else {}


def actualizar_proyecto(topico: str, cambios: dict[str, Any]) -> dict[str, Any]:
    """Actualiza los campos de §3.1 de un proyecto, identificado por su tópico."""
    permitidos = {k: v for k, v in cambios.items() if k in CAMPOS_PROYECTO}
    if not permitidos:
        raise LiquidacionesAPIError("No hay campos válidos para actualizar")
    data = _request("PATCH", PATH_PROYECTO.format(topico=topico), json=permitidos)
    return _proyectar(data) if isinstance(data, dict) else {}


# ── Tareas asíncronas ────────────────────────────────────────────────────────
# Varios endpoints del ciclo (FTP de XM, liquidar, repartir, ER, cruce) devuelven
# un ``task_id`` en vez del resultado. Consultarlas tiene dos trampas y las dos
# se resuelven aquí, en un solo lugar:
#
#   1. ``status: "SUCCESS"`` NO significa que salió bien. Varias tareas atrapan
#      sus errores y devuelven ``result.success = False`` con estado SUCCESS.
#   2. Un ``task_id`` inexistente responde ``PENDING``, no 404. No hay forma de
#      distinguir "en cola" de "no existe", así que quien espere una tarea tiene
#      que ponerle su propio límite de tiempo.

def _mensaje_de_tarea(resultado: Any, estado: EstadoTarea, estado_crudo: str) -> str:
    """Frase corta para mostrarle al usuario, sin filtrar el error crudo del proveedor."""
    if isinstance(resultado, dict):
        mensaje = resultado.get("message") or resultado.get("error")
        if not mensaje and resultado.get("errors"):
            mensaje = str(resultado["errors"])
        if mensaje:
            return str(mensaje)
    if estado is EstadoTarea.EXITO:
        return "La tarea terminó correctamente."
    if estado is EstadoTarea.FALLO:
        return f"La tarea terminó en estado {estado_crudo}."
    return "La tarea sigue en proceso."


def consultar_tarea(task_id: str) -> dict[str, Any]:
    """Estado normalizado de una tarea asíncrona.

    Devuelve ``estado`` (ver :class:`EstadoTarea`), ``terminada`` y el ``resultado``
    crudo por si el consumidor necesita algo puntual de adentro (una ``drive_url``,
    por ejemplo).
    """
    data = _request("GET", PATH_TAREA.format(task_id=task_id))
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API de Liquidaciones devolvió un estado de tarea inesperado")

    estado_crudo = str(data.get("status") or "")
    resultado = data.get("result")

    if estado_crudo not in _ESTADOS_TERMINALES:
        estado = EstadoTarea.EN_CURSO
    elif estado_crudo != "SUCCESS":
        estado = EstadoTarea.FALLO
    # SUCCESS no implica que salió bien: manda `result.success`.
    elif isinstance(resultado, dict) and resultado.get("success") is False:
        estado = EstadoTarea.FALLO
    else:
        estado = EstadoTarea.EXITO

    return {
        "task_id": task_id,
        # .value explícito: `str(EstadoTarea.EXITO)` da "EstadoTarea.EXITO", no "exito".
        "estado": estado.value,
        "estado_crudo": estado_crudo,
        "terminada": estado is not EstadoTarea.EN_CURSO,
        "mensaje": _mensaje_de_tarea(resultado, estado, estado_crudo),
        "resultado": resultado if isinstance(resultado, dict) else None,
    }


# ── Facturas de XM ───────────────────────────────────────────────────────────
# Límites que impone la API al subir (§4.3 de la guía).
MAX_FACTURAS_POR_LOTE = 20
MAX_BYTES_POR_FACTURA = 10 * 1024 * 1024


def listar_facturas_xm(**filtros: Any) -> dict[str, Any]:
    """Facturas de XM de un período con su bloque ``readiness``.

    ``readiness.ready_for_distribution`` es la precondición de repartir (§4.6):
    si viene en ``false``, ``blockers`` dice exactamente qué falta.
    """
    params = {k: v for k, v in filtros.items() if v not in (None, "")}
    data = _request("GET", PATH_FACTURAS_XM, params=params)
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("Se esperaba el listado de facturas de XM")
    return data


def subir_facturas_xm(
    archivos: list[tuple[str, bytes, str]],
    version: str,
) -> dict[str, Any]:
    """Sube un lote de facturas en PDF. El mes y el año los extrae la IA del PDF.

    ``archivos`` son tuplas ``(nombre, contenido, content_type)``.
    """
    if not archivos:
        raise LiquidacionesAPIError("No se enviaron archivos")
    if len(archivos) > MAX_FACTURAS_POR_LOTE:
        raise LiquidacionesAPIError(
            f"La API acepta máximo {MAX_FACTURAS_POR_LOTE} facturas por lote"
        )

    data = _request(
        "POST",
        PATH_FACTURAS_XM,
        files=[("files", (nombre, contenido, tipo)) for nombre, contenido, tipo in archivos],
        data={"version": version},
    )
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API de Liquidaciones no confirmó la subida")
    return data


# ── Datos maestros y catálogos ───────────────────────────────────────────────

def _listar(path: str, **filtros: Any) -> list[dict[str, Any]]:
    """GET de un listado, quitando los filtros vacíos."""
    params = {k: v for k, v in filtros.items() if v not in (None, "")}
    data = _request("GET", path, params=params)
    if not isinstance(data, list):
        raise LiquidacionesAPIError(f"Se esperaba una lista en {path}")
    return data


def listar_contratos() -> list[dict[str, Any]]:
    """Contratos de energía (§3.3)."""
    return _listar(PATH_CONTRATOS)


def listar_contrato_proyectos(**filtros: Any) -> list[dict[str, Any]]:
    """Vínculos contrato ↔ proyecto (§3.4)."""
    return _listar(PATH_CONTRATO_PROYECTOS, **filtros)


def listar_cantidades(**filtros: Any) -> list[dict[str, Any]]:
    """Pisos y techos de los contratos PLC (§3.5)."""
    return _listar(PATH_CANTIDADES, **filtros)


def listar_costos(**filtros: Any) -> list[dict[str, Any]]:
    """Costos e ingresos fijos por proyecto (§3.6)."""
    return _listar(PATH_COSTOS, **filtros)


def listar_catalogos() -> dict[str, list[dict[str, Any]]]:
    """Empresas, precios de energía y tipos de costo, para resolver los selects.

    Son datos fijos: se consultan, nunca se crean.
    """
    return {
        "empresas": _listar(PATH_EMPRESAS),
        "precios_energia": _listar(PATH_PRECIOS_ENERGIA),
        "tipos_costo": _listar(PATH_TIPOS_COSTO),
    }


def crear_contrato(datos: dict[str, Any]) -> dict[str, Any]:
    """Crea un contrato de energía (§3.3)."""
    data = _request("POST", PATH_CONTRATOS, json=datos)
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API no devolvió el contrato creado")
    return data


def vincular_contrato_proyecto(datos: dict[str, Any]) -> dict[str, Any]:
    """Vincula un contrato a un proyecto (§3.4).

    ``energy_price`` es obligatorio si la tarifa es ``ppa``, prohibido si es
    ``market`` y opcional en ``market_plus_benefits``.
    """
    data = _request("POST", PATH_CONTRATO_PROYECTOS, json=datos)
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API no devolvió el vínculo creado")
    return data


def crear_cantidades(datos: dict[str, Any]) -> dict[str, Any]:
    """Crea un piso o un techo de un contrato PLC (§3.5): 24 valores horarios."""
    data = _request("POST", PATH_CANTIDADES, json=datos)
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API no devolvió las cantidades creadas")
    return data


# ── Ciclo mensual ────────────────────────────────────────────────────────────

def obtener_ipp(month: int, year: int) -> float:
    """IPP del mes, del DANE (§4.1). Síncrono; no se puede enviar uno propio."""
    data = _request("GET", PATH_IPP, params={"month": month, "year": year})
    if not isinstance(data, dict) or data.get("ipp") is None:
        raise LiquidacionesAPIError("La API no devolvió el IPP del período")
    return float(data["ipp"])


def _lanzar(metodo: str, path: str, **kwargs: Any) -> str:
    """Dispara una tarea asíncrona y devuelve su ``task_id``."""
    data = _request(metodo, path, **kwargs)
    if not isinstance(data, dict) or not data.get("task_id"):
        raise LiquidacionesAPIError("La API no devolvió un identificador de tarea")
    return str(data["task_id"])


def descargar_archivos_xm(month: int, year: int, version: str) -> str:
    """Descarga los ocho archivos del FTP de XM (§4.2). Requiere SIC/FRT y contratos."""
    return _lanzar("POST", PATH_FTP, json={"month": month, "year": year, "version": version})


def liquidar_contratos(month: int, year: int, version: str) -> str:
    """Liquida los contratos del período (§4.5). Va ANTES de repartir."""
    return _lanzar("POST", PATH_LIQUIDAR, json={"month": month, "year": year, "version": version})


def repartir_facturas_xm(
    month: int,
    year: int,
    total_ac_power: float,
    override: bool,
    new_version: str,
    last_version: str | None = None,
) -> str:
    """Reparte las facturas de XM entre los proyectos (§4.6).

    ``override`` debe ir en ``True`` la primera vez que se corre un período: con
    ``False`` y sin un reparto previo, la API borra los costos XM del período y
    no crea nada, sin reportar error.
    """
    cuerpo: dict[str, Any] = {
        "month": month,
        "year": year,
        "total_ac_power": total_ac_power,
        "override": override,
        "new_version": new_version,
    }
    if last_version:
        cuerpo["last_version"] = last_version
    return _lanzar("POST", PATH_REPARTIR, json=cuerpo)


def generar_estado_resultados(month: int, year: int, version: str) -> str:
    """Genera el ``.xlsx`` del estado de resultados. Queda en Drive."""
    return _lanzar(
        "GET", PATH_ESTADO_RESULTADOS_XLSX,
        params={"month": month, "year": year, "version": version},
    )


def generar_cruce_facturas(month: int, year: int, version: str) -> str:
    """Genera el Excel que verifica que lo repartido cuadre con la factura de XM (§4.8)."""
    return _lanzar(
        "GET", PATH_CRUCE_FACTURAS,
        params={"month": month, "year": year, "version": version},
    )


def estado_resultados_json(
    month: int, year: int, version: str, project: str | None = None
) -> dict[str, Any]:
    """Estado de resultados en JSON (§4.7). Síncrono, sin sondeo.

    Ojo con ``warnings``: si un proyecto trae alguno, sus cifras están
    incompletas. Hoy casi todos traen el fallo conocido de FAZNI y cargo por
    confiabilidad, que subestima los costos e infla la utilidad.
    """
    params: dict[str, Any] = {"month": month, "year": year, "version": version}
    if project:
        params["project"] = project
    data = _request("GET", PATH_ESTADO_RESULTADOS_JSON, params=params)
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("Se esperaba el estado de resultados")
    return data


def diagnosticar_proyecto(project: str, month: int, year: int, version: str) -> dict[str, Any]:
    """Responde «por qué este proyecto no sale en el estado de resultados» (§5.2)."""
    data = _request(
        "POST", PATH_DIAGNOSTICO,
        json={"project": project, "month": month, "year": year, "version": version},
    )
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("Se esperaba el diagnóstico del proyecto")
    return data


def subir_excel_costos(nombre: str, contenido: bytes, tipo: str) -> dict[str, Any]:
    """Carga masiva de costos e ingresos fijos por Excel (§3.6).

    El campo del formulario se llama ``file``, en singular: un solo archivo por
    llamada. La plantilla que debería bajarse por GET de esta misma ruta hoy
    responde 400 por un fallo del lado de la API.
    """
    data = _request("POST", PATH_COSTOS_XLSX, files={"file": (nombre, contenido, tipo)})
    if not isinstance(data, dict):
        raise LiquidacionesAPIError("La API no confirmó la carga del Excel de costos")
    return data
