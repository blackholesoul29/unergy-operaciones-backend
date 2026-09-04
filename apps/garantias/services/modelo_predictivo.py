"""Modelo Predictivo de Garantias: el plan de la semana y el detalle de un vencimiento.

Puerto de `app/services/garantias_modelo/servicio.py`. Solo lectura: arma las
respuestas con la forma exacta del contrato del plan 1, que el frontend ya
consume en produccion — no cambiar nombres de campo sin cambiar la vista.

Mientras solo exista la replica del dia 7, cada fila sale con `estado = "firme"`,
`central = None` y `p90` = el numero firme. Es honesto: sin estimador no hay rango
y poner uno falso seria peor que no tenerlo.

Del paquete original solo se porta este archivo. `motor.py`, `ingesta.py` y
`backtest.py` alimentan la replica desde un job, no desde HTTP: siguen en
SQLAlchemy hasta que se porte el scheduler.
"""

from __future__ import annotations

import datetime

from apps.garantias.models import GarCalculo, GarComponentePred, GarComponenteReal

_EXPOSICION = "exposicion energia en bolsa ($)"
HORIZONTE_FIRME = 7


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _id_calculo(c: GarCalculo) -> str:
    return f"{c.fecha_vencimiento.isoformat()}|{c.periodo_ini.isoformat()}"


def _num(v) -> float | None:
    return float(v) if v is not None else None


def _exposicion_predicha(calculo_ids: list[int]) -> dict[int, float]:
    """La prediccion firme (horizonte 7) de cada calculo, en una sola consulta."""
    filas = GarComponentePred.objects.filter(
        calculo_id__in=calculo_ids,
        componente=_EXPOSICION,
        horizonte_dias=HORIZONTE_FIRME,
    ).values_list("calculo_id", "valor")
    # Puede haber varias filas por calculo (distinto cuantil o version del
    # modelo): gana la primera, igual que el `.scalar()` sin ORDER BY que habia.
    salida: dict[int, float] = {}
    for calculo_id, valor in filas:
        salida.setdefault(calculo_id, float(valor))
    return salida


def construir_plan(*, agente: str, esquema: str, cuantil: float, horizonte: int) -> dict:
    """`horizonte` se ignora si `esquema` es mensual: el frontend lo manda siempre."""
    calculos = list(
        GarCalculo.objects
        .filter(agente=agente, esquema=esquema)
        .order_by("-fecha_vencimiento", "-periodo_ini")
        [: horizonte * 3 if esquema == "semanal" else 6]
    )
    ids = [c.id for c in calculos]
    predicho = _exposicion_predicha(ids)
    real = dict(
        GarComponenteReal.objects
        .filter(calculo_id__in=ids, componente=_EXPOSICION)
        .values_list("calculo_id", "valor")
    )

    semanales: list[dict] = []
    mensuales: list[dict] = []
    for c in calculos:
        base = {
            "id": _id_calculo(c),
            "estado": "firme",
            "central": None,
            "p90": predicho.get(c.id),
            "procedencia_ventana": "observada",
        }
        if c.esquema == "semanal":
            semanales.append({
                **base,
                "vencimiento": _iso(c.fecha_vencimiento),
                "periodo_ini": _iso(c.periodo_ini),
                "periodo_fin": _iso(c.periodo_fin),
                "etiqueta_periodo": c.etiqueta_periodo,
                "real": _num(real.get(c.id)),
                "fecha_calculo_xm": _iso(c.fecha_calculo),
            })
        else:
            # El contrato del mensual pide `mes` y las cuatro fechas del ciclo.
            # Las que todavia no se derivan van en null antes que inventadas: el
            # frontend ya las trata como opcionales.
            mensuales.append({
                **base,
                "mes": c.fecha_vencimiento.strftime("%Y-%m"),
                "ventana_cierra": _iso(c.periodo_fin),
                "objetivo": None,
                "publica_xm": _iso(c.fecha_calculo),
                "dias_ventaja": None,
            })

    p90s = [f["p90"] for f in semanales + mensuales if f["p90"] is not None]
    return {
        "generado_en": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "frescura": None,
        "totales": {
            "central": None,
            "suma_p90": sum(p90s) if p90s else 0.0,
            "p90_total": None,
            "brecha": None,
        },
        "semanales": semanales,
        "mensuales": mensuales,
        "backtest": None,
    }


def construir_detalle(*, id: str) -> dict:
    """Cadena de calculo de un vencimiento. `id` es `vencimiento|periodo_ini`."""
    vacio = {"id": id, "cadena": [], "descomposicion_ancho": [], "insumos": []}
    try:
        vto, ini = id.split("|", 1)
        c = GarCalculo.objects.filter(
            fecha_vencimiento=datetime.date.fromisoformat(vto),
            periodo_ini=datetime.date.fromisoformat(ini),
        ).first()
    except ValueError:
        return vacio
    if c is None:
        return vacio

    reales = {
        r.componente: float(r.valor)
        for r in GarComponenteReal.objects.filter(calculo_id=c.id)
    }
    return {
        "id": id,
        "cadena": [
            {"concepto": "Exposición en bolsa", "origen": "replicada",
             "central": None, "p90": _exposicion_predicha([c.id]).get(c.id)},
            {"concepto": "Exposición publicada por XM", "origen": "real",
             "central": None, "p90": reales.get(_EXPOSICION)},
        ],
        "descomposicion_ancho": [],
        "insumos": [],
    }
