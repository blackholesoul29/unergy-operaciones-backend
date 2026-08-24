"""Motor de la garantía que XM precobra sobre compras/ventas en bolsa.

garantía = (ventas − compras) × precio_bolsa_7d + costo_regulatorio_mes_anterior
  ventas − compras = venta_bolsa − compra_bolsa_directa (UNGG); compras = solo duplicados.
  neto en MWh, precio en COP/kWh → ×1000.

Funciones puras (`calcular_garantia`, `neto_de_balance`) separadas de la orquestación
(`proyecciones`), que recibe sus dependencias inyectadas para testear sin BD ni red.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# Colombia = UTC-5 sin horario de verano. El contenedor corre en UTC, así que
# date.today() se adelanta un día entre las 19:00 y medianoche de Bogotá — y ahora
# hoy.day maneja los días restantes de la ventana, así que importa.
_COL_TZ = timezone(timedelta(hours=-5))


def _hoy_col() -> date:
    return datetime.now(_COL_TZ).date()

MWH_A_KWH = 1000.0
KWH_PLANTA_NUEVA_DEFAULT = 180.0


def calcular_garantia(neto_mwh: float, precio_cop_kwh: float, costo_regulatorio: float,
                      plantas_nuevas: int = 0,
                      kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """(ventas−compras)×precio + regulatorio, con override aditivo de plantas nuevas.
    Devuelve el total y sus componentes (para el snapshot/desglose)."""
    energia_neta_kwh = neto_mwh * MWH_A_KWH
    valor_energia = energia_neta_kwh * precio_cop_kwh
    valor_plantas_nuevas = plantas_nuevas * kwh_planta_nueva * precio_cop_kwh
    return {
        "energia_neta_kwh": energia_neta_kwh,
        "valor_energia": valor_energia,
        "valor_plantas_nuevas": valor_plantas_nuevas,
        "costo_regulatorio": costo_regulatorio,
        "garantia_total": valor_energia + valor_plantas_nuevas + costo_regulatorio,
    }


def neto_de_balance(balance: dict, campo: str) -> float:
    """venta_bolsa − compra_bolsa_directa (UNGG) del campo dado ('proyectado' | 'total').
    'compras' = SOLO duplicados (compra_bolsa_directa), no el compra_bolsa_total."""
    ungg = balance["ungg"]
    venta = ungg["venta_bolsa"].get(campo, 0.0)
    compra_directa = ungg["compra_bolsa_directa"].get(campo, 0.0)
    return venta - compra_directa


def _mes_anterior(anio: int, mes: int) -> tuple[int, int]:
    return (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    return (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def proyecciones(hoy: date, *, calcular_balance_fn, precio_fn, regulatorio_fn,
                 plantas_nuevas: int = 0,
                 kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Las dos estimaciones al corte `hoy`. Cada ventana pide su balance a SU mes:
    resto del mes actual = campo 'proyectado' del mes actual; mes siguiente = campo
    'total' del balance (proyectado) del mes siguiente. Deps inyectadas."""
    anio_act, mes_act = hoy.year, hoy.month
    precio = precio_fn()
    a_prev, m_prev = _mes_anterior(anio_act, mes_act)
    a_sig, m_sig = _mes_siguiente(anio_act, mes_act)

    bal_actual = calcular_balance_fn(anio_act, mes_act)["balance"]
    bal_sig = calcular_balance_fn(a_sig, m_sig)["balance"]
    reg_actual = regulatorio_fn(a_prev, m_prev)
    reg_siguiente = regulatorio_fn(anio_act, mes_act)

    def ventana(clave, anio, mes, balance, campo, reg):
        neto = neto_de_balance(balance, campo)
        calc = calcular_garantia(neto, precio, (reg or {}).get("valor") or 0.0,
                                 plantas_nuevas, kwh_planta_nueva)
        return {"clave": clave, "anio": anio, "mes": mes, "neto_mwh": neto,
                "regulatorio_periodo": {"anio": (reg or {}).get("anio"),
                                        "mes": (reg or {}).get("mes"),
                                        "fallback": (reg or {}).get("fallback")},
                **calc}

    return {
        "fecha_corte": hoy.isoformat(),
        "precio_bolsa_cop_kwh": precio,
        "plantas_nuevas": plantas_nuevas,
        "kwh_planta_nueva": kwh_planta_nueva,
        "ventanas": [
            ventana("resto_mes_actual", anio_act, mes_act, bal_actual, "proyectado", reg_actual),
            ventana("mes_siguiente", a_sig, m_sig, bal_sig, "total", reg_siguiente),
        ],
    }


def aplicar_pagado(resultado: dict, pagado_por_periodo: dict) -> dict:
    """Anexa `pagado` y `saldo` (pagado − garantia_total) a cada ventana. `pagado` es
    None si no hay dato para ese (anio, mes) → `saldo` None. Muta y devuelve el resultado."""
    for v in resultado.get("ventanas", []):
        pagado = pagado_por_periodo.get((v["anio"], v["mes"]))
        v["pagado"] = pagado
        v["saldo"] = None if pagado is None else pagado - (v.get("garantia_total") or 0.0)
    return resultado


def filas_snapshot(resultado: dict) -> list:
    """Convierte la salida de `proyecciones` en filas GarantiaSnapshot (sin commitear)."""
    from app.models.garantias_proyecciones import GarantiaSnapshot
    corte = date.fromisoformat(resultado["fecha_corte"])
    precio = resultado.get("precio_bolsa_cop_kwh")
    filas = []
    for v in resultado["ventanas"]:
        reg = v.get("regulatorio_periodo") or {}
        filas.append(GarantiaSnapshot(
            fecha_corte=corte, clave=v["clave"], anio=v["anio"], mes=v["mes"],
            neto_mwh=v.get("neto_mwh"), precio_bolsa=precio,
            valor_energia=v.get("valor_energia"),
            valor_plantas_nuevas=v.get("valor_plantas_nuevas"),
            costo_regulatorio=v.get("costo_regulatorio"),
            garantia_total=v.get("garantia_total"),
            plantas_nuevas=resultado.get("plantas_nuevas", 0),
            kwh_planta_nueva=resultado.get("kwh_planta_nueva"),
            regulatorio_anio=reg.get("anio"), regulatorio_mes=reg.get("mes"),
            regulatorio_fallback=bool(reg.get("fallback")),
        ))
    return filas


def _balance_fn(db, anio: int, mes: int) -> dict:
    from datetime import date as _d
    from app.services.balance_energia import calcular_balance, calcular_balance_proyectado
    hoy = _d.today()
    if (anio, mes) > (hoy.year, hoy.month):
        return calcular_balance_proyectado(db, anio, mes)
    return calcular_balance(db, anio, mes)


def _precio_fn() -> float | None:
    from datetime import date as _d
    from app.services.simem_bolsa import precio_bolsa_prom_7d
    hoy = _d.today()
    inicio = hoy - timedelta(days=25)
    return precio_bolsa_prom_7d(inicio.isoformat(), hoy.isoformat())


def _regulatorio_fn(anio: int, mes: int) -> dict:
    from app.services.costo_regulatorio_drive import costo_regulatorio_del_mes
    return costo_regulatorio_del_mes(anio, mes)


def guardar_balcttos_neto(db, anio: int, mes: int, *, dia_corte: int, neto_mwh: float):
    """Upsert del neto real del BalCttos para un período."""
    from app.models.garantias_proyecciones import BalCttosNeto
    fila = db.query(BalCttosNeto).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        fila = BalCttosNeto(anio=anio, mes=mes, dia_corte=dia_corte, neto_mwh=neto_mwh)
        db.add(fila)
    else:
        fila.dia_corte = dia_corte
        fila.neto_mwh = neto_mwh
    db.commit()
    return fila


def balcttos_neto_de_periodo(db, anio: int, mes: int) -> dict | None:
    """{'dia_corte', 'neto_mwh'} del BalCttos guardado, o None si no hay."""
    from app.models.garantias_proyecciones import BalCttosNeto
    fila = db.query(BalCttosNeto).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        return None
    return {"dia_corte": fila.dia_corte, "neto_mwh": float(fila.neto_mwh)}


def neto_ventana_balcttos(db, anio: int, mes: int, dias_objetivo: int) -> float | None:
    """Neto (MWh) de una ventana proyectando la tasa diaria real del BalCttos del período.
    None si no hay BalCttos guardado para ese (anio, mes)."""
    from app.services.balcttos import proyectar_neto_mwh
    dato = balcttos_neto_de_periodo(db, anio, mes)
    if dato is None or not dato["dia_corte"]:
        return None
    return proyectar_neto_mwh(dato["neto_mwh"], dato["dia_corte"], dias_objetivo)


def construir_proyecciones_live(db, hoy: date | None = None, *, plantas_nuevas: int = 0,
                                kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Calcula las dos ventanas cableando las dependencias reales (balance, precio SIMEM,
    costo regulatorio de Drive). Los `_*_fn` de módulo son mockeables en tests. Si hay
    BalCttos guardado para el período de una ventana, sobrescribe su neto con el real
    proyectado a la tasa diaria (fuente_neto='balcttos'); si no, queda la proyección
    del balance (fuente_neto='proyeccion')."""
    import calendar
    if hoy is None:
        hoy = _hoy_col()
    resultado = proyecciones(
        hoy,
        calcular_balance_fn=lambda a, m: _balance_fn(db, a, m),
        precio_fn=_precio_fn,
        regulatorio_fn=_regulatorio_fn,
        plantas_nuevas=plantas_nuevas, kwh_planta_nueva=kwh_planta_nueva,
    )
    precio = resultado.get("precio_bolsa_cop_kwh")
    for v in resultado["ventanas"]:
        # días de la ventana: resto del mes actual = días que faltan; mes siguiente = mes completo
        if v["clave"] == "resto_mes_actual":
            dias_obj = calendar.monthrange(v["anio"], v["mes"])[1] - hoy.day
        else:
            dias_obj = calendar.monthrange(v["anio"], v["mes"])[1]
        neto_bc = neto_ventana_balcttos(db, v["anio"], v["mes"], dias_obj)
        if neto_bc is None:
            v["fuente_neto"] = "proyeccion"
            continue
        # recomputar la garantía con el neto real del BalCttos (mantiene plantas nuevas y regulatorio)
        recal = calcular_garantia(neto_bc, precio or 0.0, v.get("costo_regulatorio") or 0.0,
                                  plantas_nuevas, kwh_planta_nueva)
        v.update(recal)
        v["neto_mwh"] = neto_bc
        v["fuente_neto"] = "balcttos"
    return aplicar_pagado(resultado, pagado_por_periodo(db))


def pagado_por_periodo(db) -> dict:
    """{(anio, mes): valor} de lo pagado registrado."""
    from app.models.garantias_proyecciones import GarantiaPagado
    return {(p.anio, p.mes): float(p.valor) for p in db.query(GarantiaPagado).all()}


def set_pagado(db, anio: int, mes: int, valor: float):
    """Upsert del pagado de un período."""
    from app.models.garantias_proyecciones import GarantiaPagado
    fila = db.query(GarantiaPagado).filter_by(anio=anio, mes=mes).one_or_none()
    if fila is None:
        fila = GarantiaPagado(anio=anio, mes=mes, valor=valor)
        db.add(fila)
    else:
        fila.valor = valor
    db.commit()
    return fila


def guardar_snapshot(db, resultado: dict) -> list:
    """Persiste las filas del resultado y las devuelve."""
    filas = filas_snapshot(resultado)
    for f in filas:
        db.add(f)
    db.commit()
    return filas


def historial_snapshots(db, limite: int = 200) -> list:
    """Últimos snapshots, más recientes primero."""
    from app.models.garantias_proyecciones import GarantiaSnapshot
    return (db.query(GarantiaSnapshot)
            .order_by(GarantiaSnapshot.fecha_corte.desc(), GarantiaSnapshot.id.desc())
            .limit(limite).all())
