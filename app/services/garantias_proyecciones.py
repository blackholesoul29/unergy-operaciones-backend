"""Motor de la garantía que XM precobra sobre compras/ventas en bolsa.

garantía = (ventas − compras) × precio_bolsa_7d + costo_regulatorio_mes_anterior
  ventas − compras = venta_bolsa − compra_bolsa_directa (UNGG); compras = solo duplicados.
  neto en MWh, precio en COP/kWh → ×1000.

Funciones puras (`calcular_garantia`, `neto_de_balance`) separadas de la orquestación
(`proyecciones`), que recibe sus dependencias inyectadas para testear sin BD ni red.
"""
from __future__ import annotations

from datetime import date

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
