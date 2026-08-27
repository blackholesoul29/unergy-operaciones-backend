"""Arma las respuestas de los endpoints, con la forma exacta del contrato del plan 1.

Mientras solo exista la réplica del día 7, cada fila sale con `estado = "firme"`,
`central = None` y `p90` = el número firme. Es honesto: sin estimador no hay rango, y
poner un rango falso sería peor que no tenerlo.
"""
from __future__ import annotations

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.garantias_modelo import (
    GarCalculo, GarComponentePred, GarComponenteReal,
)

_EXPOSICION = "exposicion energia en bolsa ($)"
HORIZONTE_FIRME = 7


def _iso(d: datetime.date | None) -> str | None:
    return d.isoformat() if d else None


def _id_calculo(c: GarCalculo) -> str:
    return f"{c.fecha_vencimiento.isoformat()}|{c.periodo_ini.isoformat()}"


def _mes(c: GarCalculo) -> str:
    return c.fecha_vencimiento.strftime("%Y-%m")


def construir_plan(db: Session, *, agente: str, esquema: str,
                   cuantil: float, horizonte: int) -> dict:
    """`horizonte` se ignora si `esquema` es mensual: el frontend lo manda siempre."""
    q = (
        select(GarCalculo)
        .where(GarCalculo.agente == agente, GarCalculo.esquema == esquema)
        .order_by(GarCalculo.fecha_vencimiento.desc(), GarCalculo.periodo_ini.desc())
        .limit(horizonte * 3 if esquema == "semanal" else 6)
    )
    calculos = list(db.execute(q).scalars())

    semanales: list[dict] = []
    mensuales: list[dict] = []
    for c in calculos:
        real = db.execute(
            select(GarComponenteReal.valor).where(
                GarComponenteReal.calculo_id == c.id,
                GarComponenteReal.componente == _EXPOSICION)
        ).scalar()
        pred = db.execute(
            select(GarComponentePred.valor).where(
                GarComponentePred.calculo_id == c.id,
                GarComponentePred.componente == _EXPOSICION,
                GarComponentePred.horizonte_dias == HORIZONTE_FIRME)
        ).scalar()
        procedencia = (c.procedencia or {}).get("ventana", "observada")
        base = {
            "id": _id_calculo(c),
            "estado": "firme",
            "central": None,
            "p90": float(pred) if pred is not None else None,
            "procedencia_ventana": procedencia,
        }
        if c.esquema == "semanal":
            semanales.append({
                **base,
                "vencimiento": _iso(c.fecha_vencimiento),
                "periodo_ini": _iso(c.periodo_ini),
                "periodo_fin": _iso(c.periodo_fin),
                "etiqueta_periodo": c.etiqueta_periodo,
                "real": float(real) if real is not None else None,
                "fecha_calculo_xm": _iso(c.fecha_calculo),
            })
        else:
            # El contrato del mensual pide `mes` y las cuatro fechas del ciclo. Las que
            # todavía no se derivan van en null antes que inventadas: el frontend ya
            # las trata como opcionales.
            mensuales.append({
                **base,
                "mes": _mes(c),
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


def construir_detalle(db: Session, *, id: str) -> dict:
    """Cadena de cálculo de un vencimiento. `id` es `vencimiento|periodo_ini`."""
    c = None
    try:
        vto, ini = id.split("|", 1)
        c = db.execute(
            select(GarCalculo).where(
                GarCalculo.fecha_vencimiento == datetime.date.fromisoformat(vto),
                GarCalculo.periodo_ini == datetime.date.fromisoformat(ini))
        ).scalars().first()
    except ValueError:
        c = None
    if c is None:
        return {"id": id, "cadena": [], "descomposicion_ancho": [], "insumos": []}

    reales = {r.componente: float(r.valor) for r in db.execute(
        select(GarComponenteReal).where(GarComponenteReal.calculo_id == c.id)
    ).scalars()}
    pred = db.execute(
        select(GarComponentePred.valor).where(
            GarComponentePred.calculo_id == c.id,
            GarComponentePred.componente == _EXPOSICION,
            GarComponentePred.horizonte_dias == HORIZONTE_FIRME)
    ).scalar()

    return {
        "id": id,
        "cadena": [
            {"concepto": "Exposición en bolsa", "origen": "replicada",
             "central": None, "p90": float(pred) if pred is not None else None},
            {"concepto": "Exposición publicada por XM", "origen": "real",
             "central": None, "p90": reales.get(_EXPOSICION)},
        ],
        "descomposicion_ancho": [],
        "insumos": [],
    }
