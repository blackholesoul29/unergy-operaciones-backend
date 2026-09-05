"""Reglas de negocio de las pólizas.

Cálculo puro, sin ORM y sin HTTP: lo llama la API al guardar, y podría
llamarlo igual una task o un comando. Es la razón por la que no vive en la
vista.
"""

from decimal import Decimal

COMPONENTES_VALOR = ("mano_obra", "estructura", "paneles", "inversores", "otros")


def calcular_derivados(
    mano_obra=None, estructura=None, paneles=None, inversores=None, otros=None,
    ipp_base=None, ipp_provisional=None, tarifa_base=None,
    generacion_anual_p90_kwh=None,
) -> tuple[float | None, float | None]:
    """Recalcula `valor_total_proyecto` y `valor_lucro_cesante` desde sus insumos.

    Se llama SIEMPRE al guardar una póliza, para que los dos campos queden
    persistidos pero nunca desincronizados de los valores que los producen.
    """
    componentes = [c for c in (mano_obra, estructura, paneles, inversores, otros)
                   if c is not None]
    valor_total_proyecto = sum(float(c) for c in componentes) if componentes else None

    valor_lucro_cesante = None
    if (
        ipp_base is not None and float(ipp_base) != 0
        and ipp_provisional is not None
        and tarifa_base is not None
        and generacion_anual_p90_kwh is not None
    ):
        # La tarifa se indexa por la variación del IPP entre la fecha base y la
        # provisional; el lucro cesante es esa tarifa por la generación P90.
        tarifa_indexada = float(tarifa_base) * float(ipp_provisional) / float(ipp_base)
        valor_lucro_cesante = tarifa_indexada * float(generacion_anual_p90_kwh)

    return valor_total_proyecto, valor_lucro_cesante


def demo() -> None:
    """Comprobación mínima del cálculo (`python -m apps.contratos.services.polizas`)."""
    total, lucro = calcular_derivados(
        mano_obra=Decimal("100"), estructura=Decimal("50"), paneles=None,
        ipp_base=Decimal("100"), ipp_provisional=Decimal("110"),
        tarifa_base=Decimal("2"), generacion_anual_p90_kwh=Decimal("1000"),
    )
    assert total == 150.0, total
    assert lucro == 2200.0, lucro                      # 2 * 110/100 * 1000

    # Sin ningún componente el total es None, no 0: "no informado" y "cero" son
    # cosas distintas para quien revisa una póliza.
    assert calcular_derivados() == (None, None)

    # ipp_base en cero anularía la indexación con una división por cero.
    assert calcular_derivados(ipp_base=0, ipp_provisional=1, tarifa_base=1,
                              generacion_anual_p90_kwh=1)[1] is None
    print("ok")


if __name__ == "__main__":
    demo()
