"""Costos que el Panel Contable toma de los MÓDULOS (no del ER).

Piloto: Mantenimiento (módulo O&M) y Arrendamiento (módulo Arriendos). Cuando el
proyecto tiene contrato del servicio, el valor oficial del Panel para ese concepto
sale de aquí —del mismo cálculo que usan las vistas de O&M y Arriendos— y NO del
Estado de Resultados. Si el proyecto NO tiene contrato de ese servicio, el concepto
no se devuelve y el Panel conserva lo que traía el ER (no lo pisamos con un 0).

Los valores se devuelven NEGATIVOS, igual que el resto de los costos del panel.

`aplicar_costos_modulo` es lógica pura (sin BD): mezcla las líneas base del ER con
los valores del módulo y recalcula el IVA derivado. Está separada para poder
testearla con un string de entrada/salida exacto.
"""
from __future__ import annotations

import types

from sqlalchemy.orm import Session

from app.services.om_calculator import calcular_proyecto
from app.services.arr_calculator import calcular_arriendo, calcular_iva

# Conceptos del ER que el módulo controla. Coinciden EXACTO con las etiquetas que
# emite el parser (_COSTO_CONCEPTOS en er_loader): "Mantenimiento", "Arrendamiento".
# `iva` = si el concepto lleva línea de IVA 19% derivada (Mantenimiento sí).
CONCEPTO_OM = "Mantenimiento"
CONCEPTO_ARRIENDO = "Arrendamiento"
CONCEPTO_INTERNET = "Servicio de Internet"


def _valor_om(db: Session, proyecto, periodo: str, ipc_tasas: dict[int, float]) -> float | None:
    """Valor mensual O&M del proyecto (lo que facturaría el módulo). None si el
    proyecto no tiene contrato de mantenimiento."""
    from app.models.contratos import ContratoServicio
    from app.models.om import OMSeleccion

    c = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "mantenimiento",
                ContratoServicio.proyecto_id == proyecto.id)
        .order_by(ContratoServicio.id)
        .first()
    )
    if c is None:
        return None
    if c.estado != "vigente":         # el módulo solo factura contratos vigentes
        return 0.0
    sel = (
        db.query(OMSeleccion)
        .filter(OMSeleccion.contrato_id == c.id, OMSeleccion.periodo == periodo)
        .first()
    )
    fila = calcular_proyecto(
        contrato_id=c.id,
        nombre_proyecto=proyecto.nombre_comercial or "",
        fecha_firma_contrato=c.fecha_firma_contrato,
        fecha_inicio_om=c.fecha_inicio_om or c.fecha_inicio,
        valor_base_anual=float(c.tarifa_base) if c.tarifa_base else None,
        periodo=periodo,
        ipc_tasas=ipc_tasas,
        incluido=(sel.incluido if sel else True),
        facturado=(sel.facturado if sel else False),
        valor_manual=(float(sel.valor_manual) if sel and sel.valor_manual is not None else None),
        valor_congelado=(int(sel.valor_facturado_congelado)
                         if sel and sel.valor_facturado_congelado is not None else None),
        periodicidad=c.periodicidad_pago,
    )
    if not fila.get("habilitado") or not fila.get("incluido"):
        return 0.0
    return float(fila.get("valor_a_facturar") or 0)


def _valor_arriendo(db: Session, proyecto, periodo: str, ipc_tasas: dict[int, float]) -> tuple[float, float] | None:
    """(canon, iva) mensual de arriendo del proyecto, sumando arrendadores. None si
    el proyecto no tiene contrato de arriendo.

    El IVA lo trae el MÓDULO por arrendador (según `responsable_iva`): unos arrendadores
    lo cobran y otros no, así que NO es un 19% plano del Panel. Solo suma el IVA de los
    que efectivamente son responsables."""
    from app.models.contratos import ContratoServicio
    from app.models.arriendos import ArrArrendador, ArrSeleccion

    c = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "arriendo",
                ContratoServicio.proyecto_id == proyecto.id)
        .order_by(ContratoServicio.id)
        .first()
    )
    if c is None:
        return None
    if c.estado != "vigente":
        return 0.0

    arrendadores = (
        db.query(ArrArrendador)
        .filter(ArrArrendador.contrato_id == c.id, ArrArrendador.activo == True)  # noqa: E712
        .order_by(ArrArrendador.id)
        .all()
    )
    if not arrendadores:
        arrendadores = [types.SimpleNamespace(
            id=None, nombre=c.prestador_nombre or "Arrendador",
            valor_base=c.tarifa_base, responsable_iva=c.responsable_iva,
            anticipo_pagado_desde=None, anticipo_pagado_hasta=None,
        )]
    selecciones = {
        s.arr_arrendador_id: s
        for s in db.query(ArrSeleccion).filter(ArrSeleccion.periodo == periodo).all()
    }

    total = 0.0
    total_iva = 0.0
    for a in arrendadores:
        sel = selecciones.get(a.id)
        valor_base = float(a.valor_base) / 12 if a.valor_base is not None else None
        data = calcular_arriendo(
            proyecto_id=a.id,
            nombre=proyecto.nombre_comercial,
            codigo=getattr(proyecto, "codigo_tsf", None),
            fecha_firma_contrato=c.fecha_firma_contrato,
            valor_base=valor_base,
            periodo=periodo,
            ipc_tasas=ipc_tasas,
            incluido=(sel.incluido if sel else True),
            facturado=(sel.facturado if sel else False),
            valor_congelado=(int(sel.valor_facturado_congelado)
                             if sel and sel.valor_facturado_congelado is not None else None),
            periodicidad=c.periodicidad_pago,
            anticipo_pagado_desde=getattr(a, "anticipo_pagado_desde", None),
            anticipo_pagado_hasta=getattr(a, "anticipo_pagado_hasta", None),
        )
        if data.get("habilitado") and data.get("incluido") and data.get("aplica_este_mes"):
            canon = float(data.get("canon_a_facturar") or 0)
            total += canon
            # IVA real del arrendador (0/None si no es responsable de IVA).
            iva = calcular_iva(data.get("canon_a_facturar"), getattr(a, "responsable_iva", False))
            total_iva += float(iva or 0)
    return total, total_iva


def _valor_internet(db: Session, proyecto, periodo: str) -> float | None:
    """Tarifa mensual de internet (indexada) del proyecto. None si no tiene contrato
    de internet o si el contrato no tiene tarifa/indexación para calcular (se conserva
    el ER); 0 si el contrato no está vigente."""
    from app.models.contratos import ContratoServicio

    c = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "internet",
                ContratoServicio.proyecto_id == proyecto.id)
        .order_by(ContratoServicio.id)
        .first()
    )
    if c is None:
        return None
    if c.estado != "vigente":
        return 0.0
    idx = c.indexacion_anual or c.indexacion_mensual or []
    t = _tarifa_indexada_periodo(idx, c.tarifa_mensual, c.fecha_firma_contrato, periodo)
    return float(t) if t is not None else None


def valores_modulo_costos(db: Session, proyecto_id: int, periodo: str) -> dict[str, dict]:
    """{concepto: {"valor": <neg>, "fuente": str, "iva": bool}} para los conceptos
    que el módulo controla. Solo incluye un concepto si el proyecto tiene contrato
    de ese servicio (si no, el Panel conserva el valor del ER)."""
    from app.models.proyectos import Proyecto
    from app.models.om import IPCTasa
    from app.models.arriendos import ArrIPCTasa

    proyecto = db.get(Proyecto, proyecto_id)
    if proyecto is None:
        return {}

    out: dict[str, dict] = {}

    ipc_om = {r.año: float(r.tasa) for r in db.query(IPCTasa).all()}
    v = _valor_om(db, proyecto, periodo, ipc_om)
    if v is not None:
        # Mantenimiento siempre lleva IVA 19% (como el ER): flag `iva` → lo recalcula el merge.
        out[CONCEPTO_OM] = {"valor": -abs(v), "fuente": "om", "iva": True}

    ipc_arr = {r.año: float(r.tasa) for r in db.query(ArrIPCTasa).all()}
    r = _valor_arriendo(db, proyecto, periodo, ipc_arr)
    if r is not None:
        canon, iva = r
        # El IVA de arriendo lo trae el módulo por arrendador (no un 19% plano):
        # solo hay línea de IVA si algún arrendador es responsable de IVA.
        out[CONCEPTO_ARRIENDO] = {
            "valor": -abs(canon), "fuente": "arriendos",
            "iva_valor": (-abs(iva) if iva else None),
        }

    # Internet: tarifa mensual fija (indexada) del contrato. IVA 19% como el ER.
    v = _valor_internet(db, proyecto, periodo)
    if v is not None:
        out[CONCEPTO_INTERNET] = {"valor": -abs(v), "fuente": "internet", "iva": True}

    return out


def _tarifa_indexada_periodo(indexacion, tarifa_base, fecha_firma, periodo: str) -> float | None:
    """Tarifa ($/kWh) vigente en `periodo` según la indexación por aniversario.

    `indexacion` es la lista JSONB del contrato: [{"año","valor","esBase"?}, ...],
    un valor por aniversario de firma (IPC anual encadenado, ya pre-calculado). Se
    elige el aniversario más reciente que ya ocurrió al `periodo` (mes/día de firma).
    Si el período es anterior a todo aniversario o no hay lista, cae a la base."""
    try:
        py, pm = (int(x) for x in str(periodo).split("-")[:2])
    except Exception:
        return float(tarifa_base) if tarifa_base is not None else None
    mes_firma = fecha_firma.month if fecha_firma else 1
    mejor_val, mejor_key = None, None
    for e in (indexacion or []):
        val = e.get("valor")
        anio = e.get("año", e.get("anio", e.get("anno")))
        if val is None or anio is None:
            continue
        key = (int(anio), mes_firma)          # aniversario (año, mes de firma)
        if key <= (py, pm) and (mejor_key is None or key > mejor_key):
            mejor_key, mejor_val = key, float(val)
    if mejor_val is not None:
        return mejor_val
    # 'esBase' (repr/CGM) o 'es_base' (internet/O&M): distinto esquema de JSONB.
    base = next((e.get("valor") for e in (indexacion or [])
                 if e.get("esBase") or e.get("es_base")), None)
    if base is not None:
        return float(base)
    return float(tarifa_base) if tarifa_base is not None else None


def valores_facturas_modulo(db: Session, proyecto_id: int, periodo: str, kwh: float | None) -> dict[str, dict]:
    """Representación y CGM del grupo 'facturas' = tarifa indexada de la app × la
    energía (kWh) del proyecto en el mes. La energía la pasa el caller (viene del ER,
    por decisión de negocio: debe cuadrar con la generación del ER).

    Repr y CGM viven en un mismo contrato `servicio_aplica='representacion'`. Solo se
    devuelve un concepto si el contrato tiene esa tarifa. Valores negativos. Los
    impuestos NO se calculan aquí: el Panel los deriva por cliente al leer."""
    from app.models.proyectos import Proyecto
    from app.models.contratos import ContratoServicio

    if not kwh:
        return {}
    proyecto = db.get(Proyecto, proyecto_id)
    if proyecto is None:
        return {}
    c = (
        db.query(ContratoServicio)
        .filter(ContratoServicio.servicio_aplica == "representacion",
                ContratoServicio.proyecto_id == proyecto_id)
        .order_by(ContratoServicio.id)
        .first()
    )
    if c is None:
        return {}

    out: dict[str, dict] = {}
    t_rep = _tarifa_indexada_periodo(c.indexacion_representacion, c.tarifa_representacion,
                                     c.fecha_firma_contrato, periodo)
    if t_rep:
        out["Representación"] = {"grupo": "facturas", "valor": -abs(round(t_rep * kwh, 2)),
                                 "fuente": "servicios"}
    t_cgm = _tarifa_indexada_periodo(c.indexacion_cgm, c.tarifa_cgm,
                                     c.fecha_firma_contrato, periodo)
    if t_cgm:
        out["CGM"] = {"grupo": "facturas", "valor": -abs(round(t_cgm * kwh, 2)),
                      "fuente": "servicios"}
    return out


def aplicar_costos_modulo(base: list[dict], mods: dict[str, dict], iva: float = 0.19) -> list[dict]:
    """Mezcla las líneas base del ER con los valores del módulo (lógica pura).

    Para cada concepto en `mods`:
    - Si existe una línea de costos con ese concepto, reemplaza su valor y marca
      `fuente` (y borra hoja/celda: ya no viene del ER).
    - Si no existe, la agrega.
    - IVA de la línea "IVA <concepto>":
        · `iva_valor` (monto con signo) ⇒ se usa tal cual; None ⇒ sin línea de IVA
          (y si existía una del ER, se elimina). Caso Arriendos: el IVA lo trae el
          módulo por arrendador.
        · en su defecto, `iva`=True ⇒ 19% plano sobre el valor. Caso Mantenimiento.

    No muta la lista de entrada; devuelve una nueva.
    """
    out = [dict(l) for l in base]

    def _find(grupo: str, concepto: str) -> int | None:
        for i, l in enumerate(out):
            if l.get("grupo") == grupo and l.get("concepto") == concepto:
                return i
        return None

    for concepto, info in mods.items():
        valor = info["valor"]
        fuente = info.get("fuente")
        grupo = info.get("grupo", "costos")     # 'costos' (O&M/arriendo) | 'facturas' (repr/CGM)
        idx = _find(grupo, concepto)
        linea = {"grupo": grupo, "concepto": concepto, "valor": valor,
                 "hoja": None, "celda": None, "fuente": fuente}
        if idx is None:
            out.append(linea)
            idx = len(out) - 1
        else:
            out[idx].update(linea)

        # Monto de IVA guardado como línea derivada: explícito (`iva_valor`, caso
        # Arriendos) o 19% plano por flag `iva` (Mantenimiento). Los servicios del
        # grupo 'facturas' (Repr/CGM) NO guardan IVA aquí: el Panel deriva sus
        # impuestos por cliente en tiempo de lectura, así que nunca traen iva/iva_valor.
        if "iva_valor" in info:
            iva_monto = info["iva_valor"]
        elif info.get("iva"):
            iva_monto = round(valor * iva, 2)
        else:
            iva_monto = None

        iva_concepto = f"IVA {concepto}"
        j = _find(grupo, iva_concepto)
        if iva_monto is None:
            if j is not None:      # el ER traía IVA pero el módulo dice que no lleva
                out.pop(j)
            continue
        iva_linea = {"grupo": grupo, "concepto": iva_concepto, "valor": iva_monto,
                     "hoja": None, "celda": None, "fuente": fuente}
        if j is None:
            out.insert(idx + 1, iva_linea)   # justo después del concepto, como el ER
        else:
            out[j].update(iva_linea)

    return out
