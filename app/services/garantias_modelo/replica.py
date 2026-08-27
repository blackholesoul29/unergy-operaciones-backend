"""Réplica determinística de Exposición Energía en Bolsa.

Puro: recibe series horarias y devuelve pesos. No toca la base.

Validada contra los valores publicados por XM sobre 70 períodos: error mediano de
0,0057% (536 COP sobre cifras de decenas de millones), 39/70 dentro de 0,01%.

Dos cosas que no son detalles de estilo:

1. **El signo es `compras − ventas`.** Positivo = comprador neto = se debe dinero = sube
   la garantía. Invertirlo produce ceros donde hay deuda, y el piso en cero lo esconde.
2. **El producto va hora a hora.** Agregar a día y multiplicar por un precio diario da
   otro número siempre que la energía correlacione con el precio — y en solar
   correlaciona fuerte, porque generamos al mediodía.
"""
from __future__ import annotations

import datetime

HORAS = 24


def exposicion_dia(*, compras: list[float], ventas: list[float],
                   precio: list[float]) -> float:
    """Exposición de un día en COP, sumando hora a hora.

    Falla ruidosamente si las series no tienen la misma longitud: una serie corta
    silenciosamente truncada daría un número plausible y equivocado.
    """
    if not (len(compras) == len(ventas) == len(precio)):
        raise ValueError(
            f"series de distinta longitud: compras={len(compras)} "
            f"ventas={len(ventas)} precio={len(precio)}")
    return sum((compras[h] - ventas[h]) * precio[h] for h in range(len(compras)))


def exposicion_periodo(dias: dict[datetime.date, dict[str, list[float]]]) -> float:
    """Suma la exposición de cada día de la ventana. `{}` -> 0.0."""
    return sum(
        exposicion_dia(compras=d["compras"], ventas=d["ventas"], precio=d["precio"])
        for d in dias.values()
    )


def precio_implicito(*, energia: list[float], precio: list[float]) -> float | None:
    """Precio ponderado por energía: `Σ(e·p) / Σe`.

    Sirve de check de reconciliación contra el *Precio de Bolsa Ponderado* que publica
    XM. Si no coincide de forma sistemática, la ventana o los datos están mal — no el
    precio. `None` cuando no hubo energía, que no es lo mismo que un precio de cero.
    """
    total = sum(energia)
    if not total:
        return None
    return sum(energia[i] * precio[i] for i in range(len(energia))) / total
