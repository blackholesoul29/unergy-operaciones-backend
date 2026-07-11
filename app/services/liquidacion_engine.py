"""Motor de liquidación automática XM.

Conecta tres fuentes de datos para cada proyecto/período y las liquida:

  1. Generación REAL      → `generacion_diaria.kwh_real` (kWh → MWh).
  2. Compromiso PPA        → `ppa_compromisos_energia.energia_minima` (MWh) de los
                             contratos PPA vinculados al proyecto ese mes.
  3. Precio promedio XM    → AVG(`precios_bolsa_diario.precio_promedio`) del mes
                             (COP/kWh → COP/MWh).

Con esos insumos calcula la diferencia energética (real − compromiso) y su
valoración monetaria (diferencia × precio XM), y persiste el resultado en
`liquidacion_xm_calculos` (upsert por proyecto+período).

El cálculo puro (`calcular_diferencia_y_valor`) está separado del acceso a BD
para poder testearlo aislado, siguiendo el patrón del repo (funciones puras +
tests). Diseño detallado en la migración 049.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.liquidaciones import LiquidacionXMCalculo

logger = logging.getLogger(__name__)


class LiquidacionEngineError(Exception):
    """Error base del motor de liquidación."""


class DatosFaltantesError(LiquidacionEngineError):
    """No hay suficientes datos para liquidar (generación o precio XM ausentes)."""


@dataclass(frozen=True)
class ResultadoLiquidacion:
    """Insumos + resultado del cálculo, independiente de la persistencia."""
    proyecto_id: int
    periodo: date
    generacion_real: float      # MWh
    compromiso_ppa: float       # MWh
    precio_xm_promedio: float   # COP/MWh
    diferencia_mwh: float       # MWh (real − compromiso)
    valor_liquidacion: float    # COP (diferencia × precio)


def calcular_diferencia_y_valor(
    generacion_real: float,
    compromiso_ppa: float,
    precio_xm_promedio: float,
) -> tuple[float, float]:
    """Cálculo puro del motor (sin BD, testeable aislado).

    - `diferencia_mwh` = generación real − compromiso PPA. Positiva = excedente
      (se vendió a bolsa por encima del compromiso); negativa = déficit (hubo
      que comprar en bolsa para cumplir el compromiso).
    - `valor_liquidacion` = diferencia × precio promedio XM (COP/MWh). Conserva
      el signo de la diferencia: excedente = ingreso (+), déficit = costo (−).

    Redondea la diferencia a 4 decimales (MWh) y el valor a 2 (COP), igual que
    las columnas de la tabla, para que el valor persistido y el calculado
    coincidan exactamente.
    """
    diferencia_mwh = round(generacion_real - compromiso_ppa, 4)
    valor_liquidacion = round(diferencia_mwh * precio_xm_promedio, 2)
    return diferencia_mwh, valor_liquidacion


class LiquidacionEngine:
    """Motor de liquidación anclado a una sesión de BD."""

    def __init__(self, db: Session):
        self.db = db

    # ── Insumos ────────────────────────────────────────────────────────────

    def _generacion_real_mwh(self, proyecto_id: int, anio: int, mes: int) -> float | None:
        """MWh reales del mes = SUM(kwh_real) / 1000. None si no hay lecturas."""
        row = self.db.execute(text("""
            SELECT SUM(kwh_real) AS total_kwh
            FROM generacion_diaria
            WHERE proyecto_id = :pid
              AND EXTRACT(YEAR FROM fecha) = :anio
              AND EXTRACT(MONTH FROM fecha) = :mes
              AND kwh_real IS NOT NULL
        """), {"pid": proyecto_id, "anio": anio, "mes": mes}).first()
        if not row or row.total_kwh is None:
            return None
        return round(float(row.total_kwh) / 1000.0, 4)

    def _compromiso_ppa_mwh(self, proyecto_id: int, anio: int, mes: int) -> float:
        """Compromiso PPA (MWh) del proyecto ese mes.

        Suma `energia_minima` de los compromisos de TODOS los contratos PPA de
        venta vigentes vinculados al proyecto (un proyecto puede aportar a más
        de un contrato). Si el proyecto no tiene compromiso PPA ese mes, es 0.0
        (planta a bolsa pura): la liquidación se hace igual contra un compromiso
        cero.
        """
        row = self.db.execute(text("""
            SELECT COALESCE(SUM(ce.energia_minima), 0) AS compromiso
            FROM ppa_compromisos_energia ce
            JOIN ppa_contratos c ON c.id = ce.contrato_id
            JOIN ppa_contrato_proyectos cp ON cp.contrato_id = c.id
            WHERE cp.proyecto_id = :pid
              AND ce.año = :anio
              AND ce.mes = :mes
              AND ce.energia_minima IS NOT NULL
              AND c.deleted_at IS NULL
        """), {"pid": proyecto_id, "anio": anio, "mes": mes}).first()
        return round(float(row.compromiso or 0.0), 4) if row else 0.0

    def _precio_xm_cop_mwh(self, anio: int, mes: int) -> float | None:
        """Precio promedio de bolsa (XM) del mes en COP/MWh.

        `precios_bolsa_diario.precio_promedio` está en COP/kWh; se escala ×1000
        a COP/MWh para cuadrar con la energía en MWh. None si no hay precios.
        """
        row = self.db.execute(text("""
            SELECT AVG(precio_promedio) AS precio_avg
            FROM precios_bolsa_diario
            WHERE EXTRACT(YEAR FROM fecha) = :anio
              AND EXTRACT(MONTH FROM fecha) = :mes
              AND precio_promedio IS NOT NULL
        """), {"anio": anio, "mes": mes}).first()
        if not row or row.precio_avg is None:
            return None
        return round(float(row.precio_avg) * 1000.0, 4)

    # ── Cálculo + persistencia ───────────────────────────────────────────────

    def calcular_liquidacion_proyecto(
        self, proyecto_id: int, mes: int, anio: int
    ) -> LiquidacionXMCalculo:
        """Calcula y persiste (upsert) la liquidación de un proyecto/período.

        Lanza `DatosFaltantesError` si falta la generación real o el precio XM
        del mes (sin esos dos no hay liquidación posible). Un compromiso PPA
        ausente NO es un error: se toma como 0 (planta a bolsa).

        El registro se guarda en estado 'calculado'. Si ya existía un cálculo
        para ese proyecto+período se actualiza en sitio (idempotente), salvo que
        esté 'auditado', en cuyo caso se conserva y se lanza error para no pisar
        una cifra ya validada.
        """
        if not (1 <= mes <= 12):
            raise LiquidacionEngineError(f"Mes inválido: {mes}")

        periodo = date(anio, mes, 1)

        generacion_real = self._generacion_real_mwh(proyecto_id, anio, mes)
        if generacion_real is None:
            raise DatosFaltantesError(
                f"Sin generación real registrada para el proyecto {proyecto_id} "
                f"en {anio}-{mes:02d}"
            )

        precio_xm = self._precio_xm_cop_mwh(anio, mes)
        if precio_xm is None:
            raise DatosFaltantesError(
                f"Sin precios de bolsa (XM) registrados para {anio}-{mes:02d}"
            )

        compromiso_ppa = self._compromiso_ppa_mwh(proyecto_id, anio, mes)

        diferencia_mwh, valor_liquidacion = calcular_diferencia_y_valor(
            generacion_real, compromiso_ppa, precio_xm
        )

        registro = (
            self.db.query(LiquidacionXMCalculo)
            .filter(
                LiquidacionXMCalculo.proyecto_id == proyecto_id,
                LiquidacionXMCalculo.periodo == periodo,
            )
            .first()
        )

        if registro is not None and registro.estado == "auditado":
            raise LiquidacionEngineError(
                f"La liquidación de {proyecto_id} en {anio}-{mes:02d} ya está "
                "auditada; no se recalcula."
            )

        if registro is None:
            registro = LiquidacionXMCalculo(proyecto_id=proyecto_id, periodo=periodo)
            self.db.add(registro)

        registro.generacion_real = generacion_real
        registro.compromiso_ppa = compromiso_ppa
        registro.precio_xm_promedio = precio_xm
        registro.diferencia_mwh = diferencia_mwh
        registro.valor_liquidacion = valor_liquidacion
        registro.estado = "calculado"

        self.db.commit()
        self.db.refresh(registro)
        logger.info(
            "Liquidación XM proyecto=%s periodo=%s: gen=%.4f compromiso=%.4f "
            "dif=%.4f valor=%.2f COP",
            proyecto_id, periodo, generacion_real, compromiso_ppa,
            diferencia_mwh, valor_liquidacion,
        )
        return registro
