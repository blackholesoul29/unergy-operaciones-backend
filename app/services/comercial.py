"""Lógica pura del CRM comercial (testeable sin BD)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from app.utils.series_mensuales import serie_mensual_kwh

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
    """Ahora en hora Colombia (UTC-5, sin DST) — patrón del repo.

    OJO: la hora es la correcta pero el tzinfo queda en UTC, así que serializado
    dice "+00:00" sobre una hora que es -05:00. Para uso interno da igual (todas
    las cuentas se hacen entre valores de esta misma función), pero **no lo
    devuelvas en una respuesta de API**: quien la parsee se corre cinco horas.
    Para eso está `ahora_colombia()`.
    """
    return datetime.now(timezone.utc) - timedelta(hours=5)


COLOMBIA = timezone(timedelta(hours=-5))


def ahora_colombia() -> datetime:
    """Ahora en Colombia, con el offset bien puesto (-05:00).

    La versión honesta de col_now(), para lo que sale hacia afuera.
    """
    return datetime.now(COLOMBIA)


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
        else:
            # Ojo: el p50 llega como lista o como texto JSON según la antigüedad
            # de la fila (ver serie_mensual_kwh). Leerlo crudo tumbaba la lista
            # entera de /comercial/ofertas con un 500.
            vals = serie_mensual_kwh(proyecto.p50_mensual_kwh)
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


# ── Proyectos en operación (consumo externo) ─────────────────────────────────
# Superficie de solo lectura para integrar la plataforma con otra: "dame las
# plantas que hoy están operando y sus seis datos". Vive acá y no en
# proyectos.py porque quién está operando lo define el pipeline comercial
# (`oportunidad_ofertas.estado`), que es lo que se ve en /comercial.
#
# La diferencia con ficha_operativa(): esta habla de PROYECTOS (una fila por
# planta, aunque tenga dos ofertas), usa la generación promedio MEDIDA
# (`proyectos.gen_mensual_promedio_mwh`) en vez de la estimada, y trae la fecha
# de inicio de COMERCIALIZACIÓN, que no es la de inicio del contrato.

ESTADO_OPERANDO = "operando"

# De dónde salió la generación promedio. Se nombra por su naturaleza y no por la
# columna: quien integra necesita saber si el número está medido o estimado, no
# en qué tabla vive.
GEN_MEDIDO = "medido"        # ventana móvil de 30 días de generación real
GEN_MANUAL = "manual"        # lo cargó una persona (planta sin histórico)
GEN_ESTIMADO = "estimado"    # proyección del proyecto (mwh_mes_estimado / p50)
GEN_DECLARADO = "declarado"  # lo declaró la oferta comercial (planta sin Proyecto)


def duracion_contrato(inicio, fin, hoy=None) -> dict:
    """Cuánto dura el contrato de energía y cuánto le queda.

    `meses` son meses calendario (ver meses_de_contrato) porque el PPA se factura
    por mes. `texto` es la forma en que lo dice la gente ("6 años y 11 meses") y
    existe para que quien integre no tenga que rearmarla en su front.

    `meses_restantes` se cuenta desde hoy, sin incluir el mes en curso completo:
    un contrato que vence este mes tiene 1 mes restante, uno vencido tiene 0.
    """
    meses = meses_de_contrato(inicio, fin)
    anios = None
    texto = None
    if meses is not None:
        anios = float((Decimal(meses) / Decimal(12)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP))
        a, m = divmod(meses, 12)
        partes = []
        if a:
            partes.append(f"{a} año" if a == 1 else f"{a} años")
        if m or not a:
            partes.append(f"{m} mes" if m == 1 else f"{m} meses")
        texto = " y ".join(partes)

    hoy = hoy or col_now().date()
    restantes = None
    if fin is not None:
        restantes = meses_de_contrato(hoy, fin) or 0
    vigente = None
    if inicio is not None or fin is not None:
        vigente = ((inicio is None or inicio <= hoy)
                   and (fin is None or fin >= hoy))

    return {
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "duracion_meses": meses,
        "duracion_anios": anios,
        "duracion_texto": texto,
        "meses_restantes": restantes,
        "vigente": vigente,
    }


def _gen_promedio(proyecto, ofertas) -> tuple[float | None, str | None, dict]:
    """Generación mensual promedio en MWh, su origen y el detalle de la medición.

    La cascada va de lo más duro a lo más blando y el origen viaja siempre al
    lado del número: un promedio medido sobre 30 días de lecturas y una
    proyección de ingeniería no son el mismo dato aunque ocupen la misma casilla.

        medido/manual (proyectos.gen_mensual_promedio_mwh)
          → estimado (mwh_mes_estimado, si no el promedio de la curva p50)
          → declarado en la oferta (planta que todavía no existe como Proyecto)
    """
    detalle: dict = {"dias_con_datos": None, "ventana_desde": None,
                     "ventana_hasta": None, "actualizado_en": None}

    if proyecto is not None and proyecto.gen_mensual_promedio_mwh is not None:
        origen = (GEN_MANUAL if proyecto.gen_promedio_origen == "manual"
                  else GEN_MEDIDO)
        detalle = {
            "dias_con_datos": proyecto.gen_promedio_dias,
            "ventana_desde": proyecto.gen_promedio_desde,
            "ventana_hasta": proyecto.gen_promedio_hasta,
            "actualizado_en": proyecto.gen_promedio_actualizado_en,
        }
        return float(proyecto.gen_mensual_promedio_mwh), origen, detalle

    if proyecto is not None:
        if proyecto.mwh_mes_estimado is not None:
            return float(proyecto.mwh_mes_estimado), GEN_ESTIMADO, detalle
        # El p50 llega como lista o como texto JSON según la antigüedad de la
        # fila; serie_mensual_kwh() absorbe las dos formas.
        vals = serie_mensual_kwh(proyecto.p50_mensual_kwh)
        if vals:
            return round(sum(vals) / len(vals) / 1000.0, 3), GEN_ESTIMADO, detalle

    for o in ofertas:
        if o.energia_promedio_kwh_mes is not None:
            return (round(float(o.energia_promedio_kwh_mes) / 1000.0, 3),
                    GEN_DECLARADO, detalle)

    return None, None, detalle


def fila_operando(ofertas, proyecto=None, ppa=None, operador_oferta=None,
                  cliente=None, hoy=None) -> dict:
    """Una planta operando, con los seis datos que se consumen desde afuera.

    `ofertas` son TODAS las ofertas en 'operando' de esa planta: una misma planta
    puede tener la de compra de energía y la de servicios, y colapsarlas en dos
    filas obligaría a quien integra a deduplicar. Los códigos de seguimiento de
    todas viajan en `ofertas`.

    Como en ficha_operativa(), la cascada Proyecto → oferta es POR CAMPO y
    `fuentes` dice de dónde salió cada valor: sin ese mapa, "no aplica" y
    "todavía no lo sabemos" se ven idénticos. No toca la BD.
    """
    ofertas = list(ofertas)
    principal = ofertas[0]
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

    def _primero(attr):
        """Primer valor no vacío entre las ofertas de la planta."""
        for o in ofertas:
            v = getattr(o, attr, None)
            if v not in (None, ""):
                return v
        return None

    nombre = _elegir("nombre",
                     proyecto.nombre_comercial if proyecto else None,
                     _primero("planta_nombre"))
    municipio = _elegir("municipio",
                        proyecto.municipio if proyecto else None,
                        _primero("municipio"))
    departamento = _elegir("departamento",
                           proyecto.departamento if proyecto else None,
                           _primero("departamento"))

    # Operador de red: el catálogo manda. `operador_red_legal` ya resuelve
    # proyecto → primera frontera con operador; acá solo se le agrega el escalón
    # de lo declarado en la oferta y, al final, el texto libre legacy del
    # proyecto, que existe en filas viejas y es mejor que un null.
    operador = _elegir("operador_red",
                       proyecto.operador_red_legal if proyecto else None,
                       operador_oferta)
    if fuentes["operador_red"] == "proyecto":
        operador_id = proyecto.operador_red_id
    elif fuentes["operador_red"] == "oferta":
        operador_id = next((o.operador_red_id for o in ofertas
                            if o.operador_red_id is not None), None)
    else:
        operador_id = None
        if proyecto is not None and proyecto.operador_red:
            operador = proyecto.operador_red
            fuentes["operador_red"] = "proyecto_legacy"

    gen_mwh, gen_origen, gen_detalle = _gen_promedio(proyecto, ofertas)
    fuentes["gen_promedio_mensual"] = gen_origen

    # Inicio de comercialización = primer día con generación real (lo autoderiva
    # app.services.comercializacion). NO se rellena con la fecha del contrato ni
    # con la entrada en operación: son tres hechos distintos y mezclarlos haría
    # que nadie pueda confiar en el campo. Los otros dos viajan aparte.
    inicio_com = proyecto.fecha_inicio_comercializacion if proyecto else None
    fuentes["fecha_inicio_comercializacion"] = "proyecto" if inicio_com else None

    contrato = duracion_contrato(ppa.fecha_inicio if ppa else None,
                                 ppa.fecha_fin if ppa else None, hoy=hoy)
    if ppa is not None:
        contrato.update({
            "ppa_contrato_id": ppa.id,
            "numero_codigo_contrato": ppa.numero_codigo_contrato,
            "nombre_interno": ppa.nombre_interno,
            "tipo": ppa.tipo_contrato or "venta",
            "comprador": ppa.comprador_nombre,
            "vendedor": ppa.vendedor_nombre,
            "cantidad_minima_kwh_mes": (float(ppa.cantidad_minima_kwh_mes)
                                        if ppa.cantidad_minima_kwh_mes is not None else None),
        })
        fuentes["contrato_energia"] = "contrato"
    else:
        contrato.update({"ppa_contrato_id": None, "numero_codigo_contrato": None,
                         "nombre_interno": None, "tipo": None, "comprador": None,
                         "vendedor": None, "cantidad_minima_kwh_mes": None})
        fuentes["contrato_energia"] = None

    partes_ubicacion = [p for p in (municipio, departamento) if p]

    return {
        "proyecto_id": proyecto.id if proyecto else None,
        "nombre": nombre,
        "ubicacion": {
            "municipio": municipio,
            "departamento": departamento,
            "texto": ", ".join(partes_ubicacion) if partes_ubicacion else None,
            "latitud": float(proyecto.latitud) if proyecto is not None and proyecto.latitud is not None else None,
            "longitud": float(proyecto.longitud) if proyecto is not None and proyecto.longitud is not None else None,
        },
        "operador_red": operador,
        "operador_red_id": operador_id,
        # El promedio va en las dos unidades a propósito: la plataforma habla en
        # MWh y el CRM en kWh, y la conversión hecha en dos integraciones
        # distintas es un factor 1000 esperando pasar.
        "gen_promedio_mensual_mwh": gen_mwh,
        "gen_promedio_mensual_kwh": round(gen_mwh * 1000, 3) if gen_mwh is not None else None,
        "gen_promedio_origen": gen_origen,
        "gen_promedio_detalle": gen_detalle,
        "fecha_inicio_comercializacion": inicio_com,
        # Hechos vecinos, explícitamente separados del inicio de comercialización.
        "fecha_entrada_operacion": proyecto.fecha_entrada_operacion if proyecto else None,
        "contrato_energia": contrato,
        "cliente": cliente,
        "potencia_instalada_kwp": (float(proyecto.potencia_instalada_kwp)
                                   if proyecto is not None and proyecto.potencia_instalada_kwp is not None else None),
        "ofertas": [
            {
                "oferta_id": o.id,
                "codigo_seguimiento": _codigo_seguimiento(o.numero_oferta),
                "tipo": o.tipo if isinstance(o.tipo, str) else o.tipo.value,
                "estado": o.estado if isinstance(o.estado, str) else o.estado.value,
                "oportunidad_id": o.oportunidad_id,
            }
            for o in ofertas
        ],
        "fuentes": fuentes,
        # Guardado para ordenar y depurar; no forma parte del contrato público.
        "_principal": principal.id,
    }


def _codigo_seguimiento(numero: str | None) -> str | None:
    """Prefijo estandarizado OF→OP del código de seguimiento. Idempotente.

    Duplica a propósito `app/api/v1/comercial.py::_norm_codigo`: importarlo desde
    la API metería la capa de rutas dentro de la de servicios.
    """
    if numero and numero[:2].upper() == "OF":
        return "OP" + numero[2:]
    return numero


def proyectos_operando(db, q=None, hoy=None) -> list[dict]:
    """Las plantas que hoy están en la etapa 'operando' del pipeline comercial.

    Una fila por PLANTA, no por oferta. Todo se precarga por lotes: un número
    fijo de consultas sin importar cuántas plantas haya, porque quien integra va
    a llamar esto en cada refresco de su tablero.
    """
    from sqlalchemy.orm import selectinload
    from app.models.clientes import Cliente
    from app.models.comercial import Oportunidad, OportunidadOferta
    from app.models.contratos import PPAContrato, ppa_contrato_proyectos_table
    from app.models.fronteras import Frontera
    from app.models.operadores_red import OperadorRed
    from app.models.proyectos import Proyecto

    hoy = hoy or col_now().date()

    filas = (
        db.query(OportunidadOferta, Cliente.razon_social_nombre)
        .join(Oportunidad, Oportunidad.id == OportunidadOferta.oportunidad_id)
        .join(Cliente, Cliente.id == Oportunidad.cliente_id)
        .filter(OportunidadOferta.estado == ESTADO_OPERANDO,
                Oportunidad.deleted_at.is_(None),
                Cliente.deleted_at.is_(None))
        .all()
    )
    if not filas:
        return []

    ofertas = [o for o, _ in filas]
    cliente_por_oferta = {o.id: c for o, c in filas}

    proyecto_ids = {o.proyecto_id for o in ofertas if o.proyecto_id}
    proyectos = {}
    if proyecto_ids:
        # operador y fronteras.operador precargados: operador_red_legal los
        # recorre y sin esto haría dos consultas por planta.
        proyectos = {
            p.id: p for p in db.query(Proyecto)
            .options(selectinload(Proyecto.operador),
                     selectinload(Proyecto.fronteras).selectinload(Frontera.operador))
            .filter(Proyecto.id.in_(proyecto_ids), Proyecto.deleted_at.is_(None)).all()
        }

    ppa_ids = {o.ppa_contrato_id for o in ofertas if o.ppa_contrato_id}
    ppas = {}
    if ppa_ids:
        ppas = {c.id: c for c in db.query(PPAContrato)
                .filter(PPAContrato.id.in_(ppa_ids),
                        PPAContrato.deleted_at.is_(None)).all()}

    operador_ids = {o.operador_red_id for o in ofertas if o.operador_red_id}
    operadores = {}
    if operador_ids:
        operadores = dict(db.query(OperadorRed.id, OperadorRed.nombre_legal)
                          .filter(OperadorRed.id.in_(operador_ids)).all())

    # PPAs del proyecto, para las plantas cuya oferta no quedó enlazada a un
    # contrato: casi todas las que venían de antes del CRM. Sin esto, "tiempo del
    # contrato" saldría null justo en las plantas más antiguas, que son las que
    # sí tienen contrato.
    ppas_por_proyecto: dict[int, list] = {}
    if proyecto_ids:
        for pid, contrato in (
            db.query(ppa_contrato_proyectos_table.c.proyecto_id, PPAContrato)
            .join(PPAContrato, PPAContrato.id == ppa_contrato_proyectos_table.c.contrato_id)
            .filter(ppa_contrato_proyectos_table.c.proyecto_id.in_(proyecto_ids),
                    PPAContrato.deleted_at.is_(None)).all()
        ):
            ppas_por_proyecto.setdefault(pid, []).append(contrato)

    # Agrupar por planta. Sin proyecto vinculado la oferta es su propio grupo:
    # es una planta real que aparece en /comercial, solo que todavía no existe
    # como Proyecto en la plataforma.
    grupos: dict[tuple, list] = {}
    for o in ofertas:
        clave = ("proyecto", o.proyecto_id) if o.proyecto_id else ("oferta", o.id)
        grupos.setdefault(clave, []).append(o)

    out = []
    for (tipo_clave, valor), grupo in grupos.items():
        proyecto = proyectos.get(valor) if tipo_clave == "proyecto" else None
        if tipo_clave == "proyecto" and proyecto is None:
            # El proyecto está borrado: la oferta sigue viva pero la planta no.
            continue
        # La oferta de compra de energía manda al elegir contrato: es la que
        # define "el contrato de energía" de la planta.
        grupo = sorted(grupo, key=lambda o: (
            0 if _valor_enum(o.tipo) == "compra_energia" else 1, o.id))
        ppa = next((ppas[o.ppa_contrato_id] for o in grupo
                    if o.ppa_contrato_id and o.ppa_contrato_id in ppas), None)
        if ppa is None and proyecto is not None:
            ppa = _mejor_ppa(ppas_por_proyecto.get(proyecto.id, []), hoy)

        fila = fila_operando(
            grupo, proyecto=proyecto, ppa=ppa,
            operador_oferta=next((operadores[o.operador_red_id] for o in grupo
                                  if o.operador_red_id in operadores), None),
            cliente=cliente_por_oferta.get(grupo[0].id), hoy=hoy)
        out.append(fila)

    if q:
        aguja = q.strip().lower()
        out = [f for f in out
               if aguja in (f["nombre"] or "").lower()
               or aguja in (f["cliente"] or "").lower()
               or any(aguja in (of["codigo_seguimiento"] or "").lower()
                      for of in f["ofertas"])]

    out.sort(key=lambda f: ((f["nombre"] or "").lower(), f["_principal"]))
    for f in out:
        f.pop("_principal", None)
    return out


def _valor_enum(v):
    return v if isinstance(v, (str, type(None))) else v.value


def _mejor_ppa(contratos, hoy):
    """El contrato de energía que describe a la planta HOY.

    Prioridad: vigente hoy → de compra (que es el que firma el CRM: Unergy le
    compra la energía al dueño de la planta) → el de inicio más reciente. Un
    contrato vencido de 2021 no puede ganarle al que está corriendo.
    """
    if not contratos:
        return None

    def _clave(c):
        vigente = ((c.fecha_inicio is None or c.fecha_inicio <= hoy)
                   and (c.fecha_fin is None or c.fecha_fin >= hoy))
        return (0 if vigente else 1,
                0 if (c.tipo_contrato or "venta") == "compra" else 1,
                -(c.fecha_inicio.toordinal() if c.fecha_inicio else 0))

    return sorted(contratos, key=_clave)[0]


def contexto_ficha(db, ofertas, hoy=None) -> dict[int, dict]:
    """Precarga lo que ficha_operativa() necesita: {oferta_id: kwargs}.

    Un número FIJO de consultas sin importar cuántas ofertas entren. Resolver
    esto dentro del bucle sería N+1 justo en la vista principal de /comercial,
    que carga todas las ofertas de una.

    Las llaves de cada valor son los nombres de los parámetros de
    ficha_operativa, para poder llamarla como ficha_operativa(o, **ctx[o.id]).
    """
    from sqlalchemy.orm import selectinload
    from app.models.proyectos import Proyecto
    from app.models.fronteras import Frontera
    from app.models.contratos import PPAContrato
    from app.models.operadores_red import OperadorRed

    ofertas = list(ofertas)
    if not ofertas:
        return {}

    proyecto_ids = {o.proyecto_id for o in ofertas if o.proyecto_id}
    ppa_ids = {o.ppa_contrato_id for o in ofertas if o.ppa_contrato_id}
    operador_ids = {o.operador_red_id for o in ofertas if o.operador_red_id}

    proyectos = {}
    if proyecto_ids:
        # operador y fronteras.operador precargados: Proyecto.operador_red_legal
        # los recorre y sin esto haría dos consultas por proyecto.
        proyectos = {
            p.id: p for p in db.query(Proyecto)
            .options(selectinload(Proyecto.operador),
                     selectinload(Proyecto.fronteras).selectinload(Frontera.operador))
            .filter(Proyecto.id.in_(proyecto_ids),
                    Proyecto.deleted_at.is_(None)).all()
        }
    ppas = {}
    if ppa_ids:
        # Un contrato borrado no alimenta la ficha: la oferta conserva el FK pero
        # sus fechas ya no son la verdad de nadie.
        ppas = {c.id: c for c in db.query(PPAContrato)
                .filter(PPAContrato.id.in_(ppa_ids),
                        PPAContrato.deleted_at.is_(None)).all()}
    operadores = {}
    if operador_ids:
        operadores = dict(
            db.query(OperadorRed.id, OperadorRed.nombre_legal)
            .filter(OperadorRed.id.in_(operador_ids)).all())

    generacion = _ultimo_mes_generacion(db, proyecto_ids, hoy=hoy)

    return {
        o.id: {
            "proyecto": proyectos.get(o.proyecto_id),
            "ppa": ppas.get(o.ppa_contrato_id),
            "generacion": generacion.get(o.proyecto_id),
            "operador_oferta": operadores.get(o.operador_red_id),
        }
        for o in ofertas
    }


def _ultimo_mes_generacion(db, proyecto_ids, hoy=None) -> dict[int, tuple[str, float]]:
    """Último mes CERRADO con lecturas por proyecto: {proyecto_id: ('2026-07', kwh)}.

    Dos exclusiones a propósito, las dos por lo mismo — un número parcial
    presentado como energía real del mes es peor que no dar número:
      · el mes en curso no cuenta (tres días de agosto no son un mes);
      · un mes con menos de 28 días de lectura tampoco.
    Una sola consulta agregada para todos los proyectos.
    """
    from sqlalchemy import extract, func as sa_func
    from app.models.generacion import GeneracionDiaria

    if not proyecto_ids:
        return {}
    hoy = hoy or col_now().date()
    primero_del_mes = hoy.replace(day=1)
    anio = extract("year", GeneracionDiaria.fecha)
    mes = extract("month", GeneracionDiaria.fecha)
    filas = (
        db.query(GeneracionDiaria.proyecto_id, anio.label("anio"), mes.label("mes"),
                 sa_func.sum(GeneracionDiaria.kwh_real).label("kwh"))
        .filter(GeneracionDiaria.proyecto_id.in_(proyecto_ids),
                GeneracionDiaria.kwh_real.isnot(None),
                GeneracionDiaria.fecha < primero_del_mes)
        .group_by(GeneracionDiaria.proyecto_id, anio, mes)
        .having(sa_func.count(GeneracionDiaria.id) >= 28)
        .all()
    )
    out: dict[int, tuple[str, float]] = {}
    for proyecto_id, a, m, kwh in filas:
        periodo = f"{int(a):04d}-{int(m):02d}"
        if proyecto_id not in out or periodo > out[proyecto_id][0]:
            out[proyecto_id] = (periodo, float(kwh))
    return out
