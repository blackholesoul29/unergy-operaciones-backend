"""Lógica pura del CRM comercial (testeable sin BD)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# Pipeline de la oferta, en orden. 'declinado' queda fuera del orden porque no
# es un avance sino una salida.
ETAPAS = ("oportunidad", "oferta", "contrato", "firmado", "operando", "terminado")
ETAPA_ORDEN = {e: i for i, e in enumerate(ETAPAS)}

# Etapas donde aplica la alerta de días sin respuesta. Las de cierre y la
# negativa quedan por fuera a propósito: no requieren seguimiento comercial.
ESTADOS_CON_ALERTA = frozenset({"oportunidad", "oferta", "contrato"})

# `resultado` (pendiente/aceptado/declinado) dejó de ser un campo editable el
# 2026-08-02: se deriva de la etapa. Existían dos verdades para lo mismo y podían
# contradecirse (una oferta 'aceptada' colgando de un cliente 'declinado').
_RESULTADO_POR_ETAPA = {
    "oportunidad": "pendiente",
    "oferta": "pendiente",
    "contrato": "pendiente",
    "firmado": "aceptado",
    "operando": "aceptado",
    # Terminado sigue siendo un negocio ganado: corrió y se venció.
    "terminado": "aceptado",
    "declinado": "declinado",
}


def estado_a_resultado(estado: str) -> str:
    """Resultado que corresponde a una etapa del pipeline."""
    return _RESULTADO_POR_ETAPA.get(estado, "pendiente")


def cerrar_contratos_vencidos(db, hoy=None) -> list[dict]:
    """Pasa a 'terminado' las ofertas cuyo contrato ya llegó a su fecha_fin.

    Se hace por job y no a mano porque nadie va a entrar al CRM el 1-ene-2033 a
    cerrar Pelletco. La fecha_fin del PPA es el dato duro; la etapa lo sigue.
    Solo toca ofertas en 'operando' con contrato vencido: una firmada que aún no
    arranca, o una sin contrato, se quedan donde están.

    Devuelve las transiciones aplicadas (vacío si no hubo).
    """
    from datetime import date as _date
    from app.models.comercial import OportunidadEstadoHistorial, OportunidadOferta
    from app.models.contratos import PPAContrato

    hoy = hoy or _date.today()
    filas = (
        db.query(OportunidadOferta, PPAContrato.fecha_fin)
        .join(PPAContrato, PPAContrato.id == OportunidadOferta.ppa_contrato_id)
        .filter(OportunidadOferta.estado == "operando",
                PPAContrato.fecha_fin.isnot(None),
                PPAContrato.fecha_fin < hoy,
                PPAContrato.deleted_at.is_(None))
        .all()
    )
    ahora = col_now()
    cerradas = []
    for oferta, fecha_fin in filas:
        db.add(OportunidadEstadoHistorial(
            oportunidad_id=oferta.oportunidad_id, oferta_id=oferta.id,
            estado_anterior="operando", estado_nuevo="terminado"))
        oferta.estado = "terminado"
        oferta.estado_desde = ahora
        oferta.resultado = estado_a_resultado("terminado")
        cerradas.append({"oferta_id": oferta.id, "codigo": oferta.numero_oferta,
                         "fecha_fin": str(fecha_fin)})
    if cerradas:
        db.commit()
    return cerradas


def resumen_etapas(estados) -> dict:
    """Cuántas ofertas del cliente hay en cada etapa, p.ej. {'firmado': 1, 'oferta': 2}.

    Un CLIENTE no tiene etapa: el negocio es la oferta (Juan, 2026-08-02). Lo que
    diferencia a las ofertas de un mismo cliente son las plantas. Por eso su
    ficha resume las etapas de sus ofertas en vez de inventar una sola —
    colapsarlas escondería justo lo que hay que ver: Tecni-plast tiene una
    firmada y otra abierta, y ninguna de las dos define "el estado del cliente".
    """
    out: dict = {}
    for e in estados:
        out[e] = out.get(e, 0) + 1
    return out


def col_now() -> datetime:
    """Ahora en hora Colombia (UTC-5, sin DST) — patrón del repo."""
    return datetime.now(timezone.utc) - timedelta(hours=5)


def calcular_alerta(
    estado: str,
    estado_desde: datetime,
    ultima_gestion: datetime | None,
    umbral_dias: int,
    ahora: datetime,
) -> tuple[int, bool]:
    """Devuelve (dias_sin_respuesta, alerta).

    La referencia es lo MÁS RECIENTE entre la entrada al estado actual y la
    última gestión de bitácora. Alerta solo con MÁS de `umbral_dias` días
    (5 días exactos NO alertan) y solo en ESTADOS_CON_ALERTA.
    """
    # Defensivo: si algún datetime viene naive (p.ej. roundtrip por un backend
    # sin timezone), se alinea al tz de `ahora` para no romper la resta.
    def _com(dt):
        if dt is not None and dt.tzinfo is None and ahora.tzinfo is not None:
            return dt.replace(tzinfo=ahora.tzinfo)
        return dt

    estado_desde = _com(estado_desde)
    ultima_gestion = _com(ultima_gestion)
    referencia = estado_desde
    if ultima_gestion is not None and ultima_gestion > referencia:
        referencia = ultima_gestion
    dias = (ahora - referencia).days
    if dias < 0:
        dias = 0
    alerta = estado in ESTADOS_CON_ALERTA and dias > umbral_dias
    return dias, alerta


def meses_de_contrato(inicio, fin) -> int | None:
    """Meses calendario que cubre el suministro, contando el primero y el último.

    Se cuenta por mes y no por días porque el PPA se factura por mes: es
    exactamente el número de filas de `ppa_tarifas` que genera /firmar al
    expandir el periodo. 12-feb-2026 → 31-dic-2032 son 83 meses de suministro,
    no "6 años y pico".
    """
    if inicio is None or fin is None or fin < inicio:
        return None
    return (fin.year - inicio.year) * 12 + (fin.month - inicio.month) + 1


def ficha_operativa(oferta, proyecto=None, ppa=None, generacion=None,
                    operador_oferta=None) -> dict:
    """Los 6 parámetros que el equipo consume por API, resueltos por cascada.

    La cascada es POR CAMPO: lo que diga el Proyecto manda, si no hay Proyecto o
    el dato está vacío vale lo declarado en la oferta, si no null. Por campo y no
    por entidad porque un Proyecto a medio diligenciar no debe borrar lo que la
    oferta sí sabe.

    Devuelve valores PLANOS más un mapa `fuentes` aparte, en vez de envolver cada
    campo en {valor, fuente}: quien consume la API lee `ficha.municipio` directo,
    y quien necesita auditar de dónde salió el dato mira `fuentes`. Sin ese mapa,
    un null y un "todavía no lo sabemos" se ven igual.

    No toca la BD. `generacion` —("2026-07", kwh) del último mes cerrado— y
    `operador_oferta` —nombre legal del catálogo para oferta.operador_red_id—
    los precarga contexto_ficha() por lotes.
    """
    fuentes: dict[str, str | None] = {}

    def _elegir(campo, del_proyecto, de_la_oferta):
        if del_proyecto not in (None, ""):
            fuentes[campo] = "proyecto"
            return del_proyecto
        if de_la_oferta not in (None, ""):
            fuentes[campo] = "oferta"
            return de_la_oferta
        fuentes[campo] = None
        return None

    proyecto_nombre = _elegir(
        "proyecto_nombre",
        proyecto.nombre_comercial if proyecto else None,
        oferta.planta_nombre)
    municipio = _elegir("municipio",
                        proyecto.municipio if proyecto else None,
                        oferta.municipio)
    departamento = _elegir("departamento",
                           proyecto.departamento if proyecto else None,
                           oferta.departamento)

    # Operador de red: la cascada operador propio → primera frontera que lo tenga
    # ya vive en Proyecto.operador_red_legal; aquí solo se le agrega el escalón
    # de lo declarado en la oferta.
    operador_red = _elegir("operador_red",
                           proyecto.operador_red_legal if proyecto else None,
                           operador_oferta)
    if fuentes["operador_red"] == "proyecto":
        # Puede quedar None si el nombre salió de una frontera y no del proyecto:
        # el nombre es el dato, el id es la conveniencia.
        operador_red_id = proyecto.operador_red_id
    elif fuentes["operador_red"] == "oferta":
        operador_red_id = oferta.operador_red_id
    else:
        operador_red_id = None

    # Energía promedio = generación mensual ESTIMADA (decisión de Juan). El
    # proyecto habla en MWh/mes; el CRM en kWh/mes, como cantidad_minima_kwh_mes.
    promedio_proyecto = None
    if proyecto is not None:
        if proyecto.mwh_mes_estimado is not None:
            promedio_proyecto = float(proyecto.mwh_mes_estimado) * 1000
        elif proyecto.p50_mensual_kwh:
            vals = [float(v) for v in proyecto.p50_mensual_kwh if v is not None]
            if vals:
                promedio_proyecto = sum(vals) / len(vals)
    energia_promedio = _elegir(
        "energia_promedio_kwh_mes", promedio_proyecto,
        float(oferta.energia_promedio_kwh_mes)
        if oferta.energia_promedio_kwh_mes is not None else None)

    # Energía real: la del último mes CERRADO, con su periodo al lado para que
    # nadie compare contra un mes a medias.
    energia_real, energia_real_periodo = None, None
    if generacion:
        energia_real_periodo, kwh = generacion
        energia_real = float(kwh) if kwh is not None else None
    fuentes["energia_real_kwh_mes"] = "generacion" if energia_real is not None else None

    # Fecha de inicio de operación = inicio de suministro del PPA (decisión de
    # Juan). Sin contrato firmado sirve la tentativa, pero marcada como estimada.
    contrato_inicio = ppa.fecha_inicio if ppa else None
    contrato_fin = ppa.fecha_fin if ppa else None
    if contrato_inicio is not None:
        fecha_inicio_operacion = contrato_inicio
        fuentes["fecha_inicio_operacion"] = "contrato"
    elif oferta.fecha_tentativa_inicio is not None:
        fecha_inicio_operacion = oferta.fecha_tentativa_inicio
        fuentes["fecha_inicio_operacion"] = "estimada"
    else:
        fecha_inicio_operacion = None
        fuentes["fecha_inicio_operacion"] = None

    meses = meses_de_contrato(contrato_inicio, contrato_fin)
    anios = None
    if meses is not None:
        anios = float((Decimal(meses) / Decimal(12)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP))
    fuentes["contrato_compra_meses"] = "contrato" if meses is not None else None

    return {
        "proyecto_nombre": proyecto_nombre,
        "municipio": municipio,
        "departamento": departamento,
        "operador_red": operador_red,
        "operador_red_id": operador_red_id,
        "energia_promedio_kwh_mes": energia_promedio,
        "energia_real_kwh_mes": energia_real,
        "energia_real_periodo": energia_real_periodo,
        "fecha_inicio_operacion": fecha_inicio_operacion,
        "contrato_compra_meses": meses,
        "contrato_compra_anios": anios,
        "contrato_fecha_inicio": contrato_inicio,
        "contrato_fecha_fin": contrato_fin,
        "fuentes": fuentes,
    }
