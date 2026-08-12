def calcular_derivados(
    mano_obra: float | None,
    estructura: float | None,
    paneles: float | None,
    inversores: float | None,
    otros: float | None,
    ipp_base: float | None,
    ipp_provisional: float | None,
    tarifa_base: float | None,
    generacion_anual_p90_kwh: float | None,
) -> tuple[float | None, float | None]:
    """Recalcula valor_total_proyecto y valor_lucro_cesante a partir de sus
    insumos. Se llama siempre al guardar una póliza (PUT /polizas/{id}) para
    que ambos campos queden persistidos pero nunca desincronizados de sus
    insumos -- ver docs/superpowers/specs/2026-08-11-vista-polizas-design.md."""
    componentes = [c for c in (mano_obra, estructura, paneles, inversores, otros) if c is not None]
    valor_total_proyecto = sum(float(c) for c in componentes) if componentes else None

    valor_lucro_cesante = None
    if (
        ipp_base is not None and float(ipp_base) != 0
        and ipp_provisional is not None
        and tarifa_base is not None
        and generacion_anual_p90_kwh is not None
    ):
        tarifa_indexada = float(tarifa_base) * float(ipp_provisional) / float(ipp_base)
        valor_lucro_cesante = tarifa_indexada * float(generacion_anual_p90_kwh)

    return valor_total_proyecto, valor_lucro_cesante
