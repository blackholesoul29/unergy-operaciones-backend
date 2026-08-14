"""Motor de la garantía que XM precobra sobre compras/ventas en bolsa.

garantía = (ventas − compras) × precio_bolsa_7d + costo_regulatorio_mes_anterior
  ventas − compras = venta_bolsa − compra_bolsa_directa (UNGG); compras = solo duplicados.
  neto en MWh, precio en COP/kWh → ×1000.

Funciones puras (`calcular_garantia`, `neto_de_balance`) separadas de la orquestación
(`proyecciones`), que recibe sus dependencias inyectadas para testear sin BD ni red.
"""
from __future__ import annotations

from datetime import date, timedelta

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
    """Las dos estimaciones de garantía al corte `hoy`. Todas las dependencias externas
    (balance, precio, regulatorio) se inyectan para poder testear sin BD ni red.

    Ambas ventanas salen del balance del MES ACTUAL (calcular_balance da ceros a futuro):
    resto del mes = campo 'proyectado'; mes siguiente = campo 'total' (proxy).
    """
    anio_act, mes_act = hoy.year, hoy.month
    balance = calcular_balance_fn(anio_act, mes_act)["balance"]
    precio = precio_fn()

    a_prev, m_prev = _mes_anterior(anio_act, mes_act)
    a_sig, m_sig = _mes_siguiente(anio_act, mes_act)
    reg_actual = regulatorio_fn(a_prev, m_prev)
    reg_siguiente = regulatorio_fn(anio_act, mes_act)

    def ventana(clave, anio, mes, campo, reg):
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
            ventana("resto_mes_actual", anio_act, mes_act, "proyectado", reg_actual),
            ventana("mes_siguiente", a_sig, m_sig, "total", reg_siguiente),
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
    from app.services.balance_energia import calcular_balance
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


def construir_proyecciones_live(db, hoy: date | None = None, *, plantas_nuevas: int = 0,
                                kwh_planta_nueva: float = KWH_PLANTA_NUEVA_DEFAULT) -> dict:
    """Calcula las dos ventanas cableando las dependencias reales (balance, precio SIMEM,
    costo regulatorio de Drive). Los `_*_fn` de módulo son mockeables en tests."""
    if hoy is None:
        hoy = date.today()
    resultado = proyecciones(
        hoy,
        calcular_balance_fn=lambda a, m: _balance_fn(db, a, m),
        precio_fn=_precio_fn,
        regulatorio_fn=_regulatorio_fn,
        plantas_nuevas=plantas_nuevas, kwh_planta_nueva=kwh_planta_nueva,
    )
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
