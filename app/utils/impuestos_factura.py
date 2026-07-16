"""
Desglose de impuestos de las facturas de servicio (Representación, CGM,
Administración) en tiempo de LECTURA — no se guardan en el panel.

La base (Rep/CGM/Admin) sale del ER y en el panel está con signo NEGATIVO
(reduce el "valor a pagar"). Sobre esa base se generan, por inversionista, las
líneas de impuesto usando las tasas del CLIENTE:

    Iva {Servicio}      = base × iva%          (mismo signo que la base → negativo)
    ReteFuente {Ab} X%  = −base × retencion%   (signo opuesto → positivo, reduce deducción)
    ReteIVA {Ab} X%     = −base × reteiva%      (positivo)
    ReteICA {Ab} X%     = −base × reteica%      (positivo)

Efecto neto en valor a pagar = base + IVA − retenciones (confirmado con la usuaria
2026-07-15). Como valor a pagar = Σ líneas con signo, basta sumar estas líneas.
"""

SERVICIOS_FACTURA = ("Representación", "CGM", "Administración")
_ABBR = {"Representación": "Rep", "CGM": "CGM", "Administración": "Adm"}


def _pct(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def impuestos_de_factura(concepto: str, valor_base, rates: dict | None) -> list[dict]:
    """Líneas de impuesto para una factura de servicio ya dividida por inversionista.

    concepto: "Representación" | "CGM" | "Administración".
    valor_base: valor de la línea base (con signo; negativo en el panel).
    rates: {iva_pct, retencion_pct, reteiva_pct, reteica_pct} del cliente (en %).
    Devuelve [] si no es una factura de servicio o no hay tasas.
    """
    if concepto not in SERVICIOS_FACTURA or not rates:
        return []
    base = float(valor_base or 0.0)
    if base == 0.0:
        return []
    ab = _ABBR.get(concepto, concepto)
    iva = _pct(rates.get("iva_pct"))
    ret = _pct(rates.get("retencion_pct"))
    rei = _pct(rates.get("reteiva_pct"))
    ica = _pct(rates.get("reteica_pct"))
    out: list[dict] = []
    if iva:
        out.append({"concepto": f"Iva {concepto}", "valor": round(base * iva / 100.0, 2)})
    if ret:
        out.append({"concepto": f"ReteFuente {ab} {ret:g}%", "valor": round(-base * ret / 100.0, 2)})
    if rei:
        out.append({"concepto": f"ReteIVA {ab} {rei:g}%", "valor": round(-base * rei / 100.0, 2)})
    if ica:
        out.append({"concepto": f"ReteICA {ab} {ica:g}%", "valor": round(-base * ica / 100.0, 2)})
    return out
