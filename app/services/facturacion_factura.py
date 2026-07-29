"""Lógica pura de la emisión de facturas de energía.

Dos piezas, ambas sin dependencias de FastAPI ni de la sesión de BD:

- `contribuciones`: cómo se reparte un contrato entre facturas cuando tiene una
  agrupación parcial por porcentaje (hoy solo Uruaco → Terpel 1).
- `construir_mensaje`: el texto que se pega en la factura. Su formato está fijado
  con un test de string exacto porque se copia tal cual.
"""
from __future__ import annotations

from calendar import monthrange

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def contribuciones(agrup, ppa_nombre: str) -> list[tuple[str, float, float | None]]:
    """Cómo se reparte un contrato entre facturas: [(nombre, fracción, porcentaje)].

    `agrup` es la agrupación manual del contrato: `(nombre, porcentaje)` o None.
    - None (o nombre vacío) → todo a la factura del PPA.
    - porcentaje None/0/100 → el contrato entero se mueve a la factura nombrada.
    - 0 < porcentaje < 100 → se parte: el % a la factura nombrada y el resto al PPA.
      Es el caso de Uruaco (22.8066% a "Terpel 1 Suno", 77.1934% en Terpel 1). La
      tarifa NO cambia: solo se reparte el kWh y el valor.

    Acepta un string como `agrup` por robustez: la carga se hacía como
    {codigo: nombre} y el consumidor esperaba tuplas, lo que reventaba al comparar
    `0 < a[1] < 100` contra la segunda letra del nombre.
    """
    if not agrup:
        return [(ppa_nombre, 1.0, None)]
    if isinstance(agrup, str):
        nombre, pct = agrup, None
    else:
        nombre, pct = agrup[0], agrup[1]
    if not nombre:
        return [(ppa_nombre, 1.0, None)]
    if pct is None or not 0 < float(pct) < 100:
        return [(nombre, 1.0, None)]
    pct = float(pct)
    fr = pct / 100.0
    return [(nombre, fr, pct), (ppa_nombre, 1 - fr, round(100 - pct, 6))]


def _mes_anio(periodo) -> tuple[int, int] | None:
    """(año, mes) de un período. Devuelve None si no se puede leer.

    El campo `periodo_indexacion_base` de los PPAs deberia ser "YYYY-MM", pero en
    la BD hay "202606" (sin guion) y "2025-6" (mes sin cero). Reventar aqui tumba
    el endpoint de facturacion completo, no solo un mensaje, asi que se toleran
    los tres formatos y cualquier otra cosa se reporta como desconocida.
    """
    s = str(periodo or "").strip()
    if not s:
        return None
    partes = s.split("-")
    try:
        if len(partes) >= 2:
            año, mes = int(partes[0]), int(partes[1])
        elif len(s) == 6 and s.isdigit():
            año, mes = int(s[:4]), int(s[4:])
        else:
            return None
    except ValueError:
        return None
    return (año, mes) if 1 <= mes <= 12 else None


def _plata(v: float | None) -> str:
    """"$ 325" y "$ 322.9": sin decimales si es entero, sin ceros de relleno."""
    if v is None:
        return "—"
    v = float(v)
    return f"$ {v:.0f}" if v == int(v) else f"$ {v:g}"


def construir_mensaje(
    numeros_contrato: list[str],
    periodo: str,
    kwh: float,
    contratos_sic: list[str],
    tarifa_base: float | None,
    ipp_base: float | None,
    periodo_ipp_base: str | None,
    ipp_mes: float | None,
) -> str:
    """Mensaje para copiar en la factura. Ver el test para el formato exacto."""
    p = _mes_anio(periodo)
    if p is None:
        raise ValueError(f"periodo ilegible: {periodo!r}")
    año, mes = p
    ultimo = monthrange(año, mes)[1]

    if ipp_base and ipp_mes:
        indexacion = f"{ipp_mes / ipp_base:.3f}"
        # Se indexa con el factor SIN redondear y se redondea al final, igual que
        # el resto del pipeline (si no, no cuadra con el Excel).
        actualizada = _plata(round((tarifa_base or 0) * ipp_mes / ipp_base, 2))
    else:
        indexacion = "—"
        actualizada = "—"

    base = _mes_anio(periodo_ipp_base)
    etiqueta_base = f"{_MESES[base[1] - 1]} {base[0]}" if base else "—"

    return "\n".join([
        ", ".join(numeros_contrato) or "—",
        f"Periodo: 01/{mes}/{año} a {ultimo}/{mes}/{año}",
        f"Energía suministrada: {kwh:,.2f} kWh",
        "",
        "",
        "La información utilizada para la facturación de la energía fue extraída "
        "de los archivos TXF.",
        f"Contrato: {', '.join(contratos_sic)}",
        "",
        f"Tarifa Base: {_plata(tarifa_base)}",
        f"IPP Base {etiqueta_base} Provisional: {_plata(ipp_base)}",
        f"IPP {_MESES[mes - 1]} {año}- Provisional: {_plata(ipp_mes)}",
        f"Indexación: {indexacion}",
        f"Tarifa Actualizada: {actualizada}",
    ])
