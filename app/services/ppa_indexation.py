"""Motor de indexación de tarifas PPA.

Calcula y persiste las tarifas mensuales de un contrato PPA aplicando sus reglas
de indexación (índice + periodicidad + periodo/valor base), reemplazando la
captura manual por un servicio determinista.

- IPC: usa el historial real de `om_ipc_tasas` (mismo factor compuesto que O&M,
  vía `om_calculator.factor_acumulado`).
- USD/DIPREM/IPP: series valor/periodo (ratio valor/valor_base). Hasta tener su
  fuente histórica quedan como placeholder (factor 1.0 + nota), sin romper.
- FIJO: no indexa.

La función `calcular_tarifas` es pura (sin DB ni FastAPI) y es la unidad testeada.
`PPAIndexationService` envuelve el acceso a datos y la persistencia idempotente.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session

from app.models import PPAContrato, PPATarifa
from app.models.om import IPCTasa
from app.services.om_calculator import factor_acumulado
from app.schemas.ppa_indexation import (
    Frequency,
    IndexationRule,
    IndexationSummary,
    IndexType,
    TariffCalculationResult,
    normalize_frequency,
    normalize_index_type,
)

logger = logging.getLogger(__name__)

# Índices que se modelan como serie valor/periodo (ratio respecto al valor base).
_SERIE_TYPES = {IndexType.USD, IndexType.DIPREM, IndexType.IPP}


def _q(value: float | Decimal, places: str = "0.0001") -> float:
    """Cuantiza a la precisión de `PPATarifa.tarifa` (Numeric(12, 4))."""
    return float(Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _periodo_str(año: int, mes: int) -> str:
    return f"{año:04d}-{mes:02d}"


# ── Cálculo puro ───────────────────────────────────────────────────────────────

def calcular_tarifas(
    *,
    index_type: IndexType,
    base_rate: float | None,
    base_period: str | None,
    base_index_value: float | None,
    frequency: Frequency,
    periodos: list[tuple[int, int]],
    index_history: dict,
    currency: str = "COP",
) -> list[TariffCalculationResult]:
    """Calcula la tarifa de cada periodo aplicando la fórmula de indexación.

    Args:
        index_type: tipo de índice ya normalizado.
        base_rate: tarifa base del contrato.
        base_period: periodo base "YYYY-MM" (define el año/valor de referencia).
        base_index_value: valor del índice en el periodo base (series USD/DIPREM).
        frequency: periodicidad (informativa; IPC compone por año).
        periodos: lista de (año, mes) a calcular, en orden.
        index_history: IPC → {año: tasa_dic}; series → {"YYYY-MM": valor}.
        currency: COP o USD (metadato de la respuesta).

    Returns:
        Lista de `TariffCalculationResult`, una por periodo.
    """
    base_rate = float(base_rate) if base_rate is not None else 0.0
    año_base = int(base_period[:4]) if base_period else (min(p[0] for p in periodos) if periodos else date.today().year)

    results: list[TariffCalculationResult] = []
    for año, mes in periodos:
        applied_index: float | None
        nota: str | None = None

        if index_type == IndexType.IPC:
            factor = factor_acumulado(año_base, año, index_history)
            applied_index = round(factor, 6)
            final = base_rate * factor

        elif index_type in _SERIE_TYPES:
            valor = index_history.get(_periodo_str(año, mes)) if index_history else None
            if valor is not None and base_index_value:
                factor = float(valor) / float(base_index_value)
                applied_index = float(valor)
                final = base_rate * factor
            else:
                # Sin serie histórica configurada todavía → placeholder honesto.
                applied_index = None
                final = base_rate
                nota = f"Índice {index_type.value} sin serie histórica: se mantiene tarifa base"

        else:  # FIJO
            applied_index = 1.0
            final = base_rate

        results.append(TariffCalculationResult(
            año=año,
            mes=mes,
            base_rate=_q(base_rate),
            applied_index=applied_index,
            final_rate=_q(final),
            currency=currency,
            nota=nota,
        ))
    return results


# ── Servicio (DB) ──────────────────────────────────────────────────────────────

class PPAIndexationService:
    """Orquesta lectura de reglas, historial de índices, cálculo y persistencia."""

    def __init__(self, db: Session):
        self.db = db

    def fetch_contract_rules(self, contrato_id: int) -> IndexationRule:
        """Construye las reglas de indexación a partir del `PPAContrato`."""
        c = (
            self.db.query(PPAContrato)
            .filter(PPAContrato.id == contrato_id, PPAContrato.deleted_at.is_(None))
            .first()
        )
        if not c:
            raise ValueError(f"Contrato PPA {contrato_id} no encontrado")

        index_type = normalize_index_type(c.indice_indexacion)
        currency = "USD" if index_type == IndexType.USD else "COP"
        return IndexationRule(
            contrato_id=c.id,
            base_rate=float(c.tarifa_base) if c.tarifa_base is not None else None,
            index_type=index_type,
            frequency=normalize_frequency(c.periodicidad_indexacion),
            base_period=c.periodo_indexacion_base,
            base_index_value=float(c.valor_indexacion_base) if c.valor_indexacion_base is not None else None,
            currency=currency,
            fecha_inicio=c.fecha_inicio,
            fecha_fin=c.fecha_fin,
        )

    def get_index_history(self, rule: IndexationRule) -> dict:
        """Obtiene el historial del índice.

        IPC → {año: tasa} desde `om_ipc_tasas`. Otros índices aún no tienen
        fuente histórica integrada (placeholder): se devuelve {} y el cálculo
        mantiene la tarifa base con una nota.
        """
        if rule.index_type == IndexType.IPC:
            tasas = self.db.query(IPCTasa).all()
            return {t.año: float(t.tasa) for t in tasas if t.tasa is not None}
        if rule.index_type in _SERIE_TYPES:
            # TODO: integrar fuente histórica (API DIPREM / TRM USD).
            logger.info(
                "Sin historial integrado para índice %s (contrato %s) — placeholder",
                rule.index_type.value, rule.contrato_id,
            )
            return {}
        return {}

    def calculate_tariffs(
        self,
        contrato_id: int,
        desde: str | None = None,
        hasta: str | None = None,
    ) -> IndexationSummary:
        """Calcula (sin persistir) las tarifas del contrato en el rango pedido."""
        rule = self.fetch_contract_rules(contrato_id)
        history = self.get_index_history(rule)
        periodos = _build_periodos(rule, desde, hasta)
        tarifas = calcular_tarifas(
            index_type=rule.index_type,
            base_rate=rule.base_rate,
            base_period=rule.base_period,
            base_index_value=rule.base_index_value,
            frequency=rule.frequency,
            periodos=periodos,
            index_history=history,
            currency=rule.currency,
        )
        return IndexationSummary(
            contrato_id=contrato_id,
            index_type=rule.index_type,
            frequency=rule.frequency,
            currency=rule.currency,
            base_rate=rule.base_rate,
            base_period=rule.base_period,
            periodo_desde=_periodo_str(*periodos[0]) if periodos else None,
            periodo_hasta=_periodo_str(*periodos[-1]) if periodos else None,
            total=len(tarifas),
            tarifas=tarifas,
        )

    def calculate_and_persist(
        self,
        contrato_id: int,
        desde: str | None = None,
        hasta: str | None = None,
    ) -> IndexationSummary:
        """Calcula y persiste (upsert idempotente) las tarifas del contrato."""
        summary = self.calculate_tariffs(contrato_id, desde, hasta)
        stats = PPATarifa.create_bulk_from_contract(self.db, contrato_id, summary.tarifas)
        self.db.commit()
        summary.persisted = True
        summary.created = stats["created"]
        summary.updated = stats["updated"]
        return summary


def _build_periodos(
    rule: IndexationRule,
    desde: str | None,
    hasta: str | None,
) -> list[tuple[int, int]]:
    """Determina los (año, mes) a calcular.

    Por defecto va desde `fecha_inicio` (o el periodo base) hasta `fecha_fin`
    (o el fin del año en curso). `desde`/`hasta` (YYYY-MM) acotan el rango.
    """
    today = date.today()

    def _parse(p: str | None) -> tuple[int, int] | None:
        if not p:
            return None
        return int(p[:4]), int(p[5:7])

    start = _parse(desde)
    if start is None:
        fi: date | None = rule.fecha_inicio  # type: ignore[assignment]
        if fi:
            start = (fi.year, fi.month)
        elif rule.base_period:
            start = _parse(rule.base_period)
        else:
            start = (today.year, 1)

    end = _parse(hasta)
    if end is None:
        ff: date | None = rule.fecha_fin  # type: ignore[assignment]
        if ff:
            end = (ff.year, ff.month)
        else:
            end = (today.year, 12)

    # Tope de seguridad para no generar rangos absurdos.
    max_end = (today.year + 5, 12)
    if end > max_end:
        end = max_end

    periodos: list[tuple[int, int]] = []
    año, mes = start
    while (año, mes) <= end:
        periodos.append((año, mes))
        if mes == 12:
            año, mes = año + 1, 1
        else:
            mes += 1
    return periodos


def calculate_and_persist_tariffs(db: Session | None = None) -> dict:
    """Punto de entrada para el scheduler: indexa todos los PPA activos.

    Recorre los contratos PPA vigentes (no borrados, sin fecha_fin pasada) y
    recalcula/persiste sus tarifas. Idempotente: re-ejecutar no duplica filas.
    """
    own_session = db is None
    if own_session:
        from app.core.database import SessionLocal
        db = SessionLocal()

    total_contratos = 0
    total_tarifas = 0
    errores = 0
    try:
        today = date.today()
        contratos = (
            db.query(PPAContrato)
            .filter(PPAContrato.deleted_at.is_(None))
            .all()
        )
        service = PPAIndexationService(db)
        for c in contratos:
            if c.fecha_fin and c.fecha_fin < today:
                continue  # contrato vencido
            try:
                summary = service.calculate_and_persist(c.id)
                total_contratos += 1
                total_tarifas += summary.total
            except Exception:
                errores += 1
                db.rollback()
                logger.exception("Indexación falló para contrato PPA %s", c.id)
        logger.info(
            "Indexación PPA completa: %d contratos, %d tarifas, %d errores",
            total_contratos, total_tarifas, errores,
        )
    finally:
        if own_session:
            db.close()

    return {"contratos": total_contratos, "tarifas": total_tarifas, "errores": errores}
