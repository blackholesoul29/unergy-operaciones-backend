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


def _dia_mes(iso: str | None) -> tuple[int, int, int] | None:
    """(día, mes, año) de un ISO 'YYYY-MM-DD'. None si no se puede leer."""
    s = str(iso or "").strip()
    if len(s) < 10:
        return None
    try:
        return (int(s[8:10]), int(s[5:7]), int(s[0:4]))
    except ValueError:
        return None


def construir_mensaje(
    numeros_contrato: list[str],
    periodo: str,
    kwh: float,
    contratos_sic: list[str],
    tarifa_base: float | None,
    ipp_base: float | None,
    periodo_ipp_base: str | None,
    ipp_mes: float | None,
    dias: int | None = None,
    fecha_min: str | None = None,
    fecha_max: str | None = None,
    contratos_detalle: list[dict] | None = None,
) -> str:
    """Mensaje para copiar en la factura. Ver el test para el formato exacto.

    `dias`/`fecha_min`/`fecha_max` (del despacho) son opcionales: si vienen, el
    período usa el rango real y se agrega "Días facturados: N" (mes parcial). Si no
    vienen, se asume el mes completo (comportamiento original)."""
    p = _mes_anio(periodo)
    if p is None:
        raise ValueError(f"periodo ilegible: {periodo!r}")
    año, mes = p
    ultimo = monthrange(año, mes)[1]
    # Rango del período: real (del despacho) si viene, si no el mes completo.
    fmin, fmax = _dia_mes(fecha_min), _dia_mes(fecha_max)
    if fmin and fmax:
        periodo_txt = f"Periodo: {fmin[0]:02d}/{fmin[1]}/{fmin[2]} a {fmax[0]:02d}/{fmax[1]}/{fmax[2]}"
    else:
        periodo_txt = f"Periodo: 01/{mes}/{año} a {ultimo}/{mes}/{año}"

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

    lineas_periodo = [periodo_txt]
    if dias is not None:
        lineas_periodo.append(f"Días facturados: {dias}")

    # Línea de contratos: con energía por contrato si viene el detalle, si no solo
    # los códigos (comportamiento original / test).
    if contratos_detalle:
        partes = [f"{d['contrato']} ({d.get('kwh', 0):,.2f} kWh)" for d in contratos_detalle]
        contrato_line = f"Contrato: {', '.join(partes)}"
    else:
        contrato_line = f"Contrato: {', '.join(contratos_sic)}"

    return "\n".join([
        ", ".join(numeros_contrato) or "—",
        *lineas_periodo,
        f"Energía suministrada: {kwh:,.2f} kWh",
        "",
        "",
        "La información utilizada para la facturación de la energía fue extraída "
        "de los archivos TXF.",
        contrato_line,
        "",
        f"Tarifa Base: {_plata(tarifa_base)}",
        f"IPP Base {etiqueta_base} Provisional: {_plata(ipp_base)}",
        f"IPP {_MESES[mes - 1]} {año}- Provisional: {_plata(ipp_mes)}",
        f"Indexación: {indexacion}",
        f"Tarifa Actualizada: {actualizada}",
    ])
