"""Cálculo de cobertura de garantías.

Estima la exposición de riesgo de un proyecto (con base en generación y precio
de bolsa) y la compara contra el valor actual de la garantía para producir un
porcentaje de cobertura y un nivel de alerta (VERDE / AMARILLO / ROJO).

El grueso de la lógica vive en funciones PURAS (sin DB) para poder probarla en
CI sin base de datos, siguiendo el patrón de `calcular_alerta` en
`app/services/comercial.py`. La función `async calcular_cobertura_garantia`
solo orquesta: trae los datos de la DB y delega en las funciones puras.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.garantias import Garantia, GarantiaMovimiento

# Tipos de cálculo soportados. Por ahora solo uno; el resto cae al placeholder.
TIPO_XM_DESVIACION_GENERACION = "XM_DESVIACION_GENERACION"

# Factor placeholder de la fórmula de exposición (ver calcular_valor_requerido).
FACTOR_EXPOSICION_DEFAULT = 0.1

# Ventana de generación considerada para la exposición.
VENTANA_GENERACION_DIAS = 30

NIVEL_VERDE = "VERDE"
NIVEL_AMARILLO = "AMARILLO"
NIVEL_ROJO = "ROJO"


# ── Funciones puras (unit-testables sin DB) ──────────────────────────────────
def calcular_valor_requerido(
    generacion_kwh_30d: float,
    precio_promedio_cop_kwh: float,
    factor: float = FACTOR_EXPOSICION_DEFAULT,
) -> float:
    """Valor de garantía requerido para cubrir la exposición del proyecto.

    Placeholder: `generacion_kwh_30d * precio_promedio_cop_kwh * factor`.
    Representa la fracción del valor comercializado en 30 días que la garantía
    debe respaldar. Se reemplazará por la fórmula contractual real.
    """
    return max(0.0, generacion_kwh_30d) * max(0.0, precio_promedio_cop_kwh) * factor


def calcular_cobertura_porcentaje(valor_actual: float, valor_requerido: float) -> Optional[float]:
    """cobertura = valor_actual / valor_requerido.

    Sin requerimiento (valor_requerido <= 0) la cobertura es indefinida: no hay
    exposición que cubrir, así que devolvemos None (el clasificador lo trata
    como VERDE).
    """
    if valor_requerido is None or valor_requerido <= 0:
        return None
    return valor_actual / valor_requerido


def clasificar_nivel_alerta(
    cobertura_porcentaje: Optional[float],
    umbral_amarilla: float,
    umbral_roja: float,
) -> str:
    """Nivel de alerta según la cobertura.

    Los umbrales son pisos de cobertura: por debajo de ellos hay sub-cobertura.
    La línea ROJA es siempre el piso MÁS estricto (menor) y la AMARILLA el menos
    estricto (mayor); tomamos min()/max() para que la clasificación quede bien
    ordenada sin importar cómo se hayan configurado los dos umbrales.

    Con los defaults (amarilla=0.90, roja=0.95): cobertura < 0.90 → ROJO,
    < 0.95 → AMARILLO, ≥ 0.95 → VERDE. Cobertura None (sin exposición) → VERDE.
    """
    if cobertura_porcentaje is None:
        return NIVEL_VERDE
    linea_roja = min(umbral_amarilla, umbral_roja)
    linea_amarilla = max(umbral_amarilla, umbral_roja)
    if cobertura_porcentaje < linea_roja:
        return NIVEL_ROJO
    if cobertura_porcentaje < linea_amarilla:
        return NIVEL_AMARILLO
    return NIVEL_VERDE


def evaluar_cobertura(
    valor_actual: float,
    generacion_kwh_30d: float,
    precio_promedio_cop_kwh: float,
    umbral_amarilla: float,
    umbral_roja: float,
    factor: float = FACTOR_EXPOSICION_DEFAULT,
) -> dict:
    """Cálculo completo (puro): valor requerido, cobertura y nivel de alerta."""
    valor_requerido = calcular_valor_requerido(generacion_kwh_30d, precio_promedio_cop_kwh, factor)
    cobertura = calcular_cobertura_porcentaje(valor_actual, valor_requerido)
    nivel = clasificar_nivel_alerta(cobertura, umbral_amarilla, umbral_roja)
    return {
        "valor_requerido": round(valor_requerido, 2),
        "valor_actual_garantia": round(valor_actual, 2),
        "cobertura_porcentaje": round(cobertura, 4) if cobertura is not None else None,
        "nivel_alerta": nivel,
        "detalles_calculo": {
            "generacion_kwh_30d": round(generacion_kwh_30d, 3),
            "precio_promedio_cop_kwh": round(precio_promedio_cop_kwh, 4),
            "factor_exposicion": factor,
            "umbral_amarilla": umbral_amarilla,
            "umbral_roja": umbral_roja,
            "ventana_dias": VENTANA_GENERACION_DIAS,
        },
    }


# ── Acceso a datos ───────────────────────────────────────────────────────────
def _saldo_actual_garantia(db: Session, garantia: Garantia) -> float:
    """Valor actual de la garantía = saldo del último movimiento, o valor_cop."""
    ultimo = (
        db.query(GarantiaMovimiento)
        .filter(GarantiaMovimiento.garantia_id == garantia.id)
        .order_by(GarantiaMovimiento.fecha.desc(), GarantiaMovimiento.id.desc())
        .first()
    )
    if ultimo is not None and ultimo.saldo_posterior_cop is not None:
        return float(ultimo.saldo_posterior_cop)
    return float(garantia.valor_cop or 0)


def _generacion_kwh_ultimos_dias(db: Session, proyecto_id: int, dias: int, hoy: date) -> float:
    """Suma de kwh_real generados por el proyecto en la ventana [hoy-dias, hoy]."""
    if not proyecto_id:
        return 0.0
    desde = hoy - timedelta(days=dias)
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(kwh_real), 0) FROM generacion_diaria "
            "WHERE proyecto_id = :pid AND fecha >= :desde AND fecha <= :hoy"
        ),
        {"pid": proyecto_id, "desde": desde, "hoy": hoy},
    ).scalar()
    return float(row or 0)


def _precio_promedio_bolsa(db: Session, dias: int, hoy: date) -> float:
    """Precio de bolsa promedio (COP/kWh) en la ventana; 0 si no hay datos."""
    desde = hoy - timedelta(days=dias)
    row = db.execute(
        text(
            "SELECT AVG(precio_promedio) FROM precios_bolsa_diario "
            "WHERE fecha >= :desde AND fecha <= :hoy"
        ),
        {"desde": desde, "hoy": hoy},
    ).scalar()
    if row is not None:
        return float(row)
    # Fallback: último precio disponible.
    row = db.execute(
        text("SELECT precio_promedio FROM precios_bolsa_diario ORDER BY fecha DESC LIMIT 1")
    ).scalar()
    return float(row or 0)


async def calcular_cobertura_garantia(db: Session, garantia: Garantia) -> dict:
    """Orquesta el cálculo de cobertura para una garantía.

    Trae generación (últimos 30 días) y precio de bolsa del proyecto asociado,
    aplica la fórmula placeholder y devuelve el dict con valor_requerido,
    valor_actual_garantia, cobertura_porcentaje, nivel_alerta y detalles_calculo.
    """
    hoy = date.today()

    umbral_amarilla = float(garantia.umbral_alerta_amarilla if garantia.umbral_alerta_amarilla is not None else 0.90)
    umbral_roja = float(garantia.umbral_alerta_roja if garantia.umbral_alerta_roja is not None else 0.95)

    valor_actual = _saldo_actual_garantia(db, garantia)

    tipo = garantia.tipo_calculo_cobertura or TIPO_XM_DESVIACION_GENERACION
    generacion = _generacion_kwh_ultimos_dias(db, garantia.proyecto_id, VENTANA_GENERACION_DIAS, hoy)
    precio = _precio_promedio_bolsa(db, VENTANA_GENERACION_DIAS, hoy)

    resultado = evaluar_cobertura(
        valor_actual=valor_actual,
        generacion_kwh_30d=generacion,
        precio_promedio_cop_kwh=precio,
        umbral_amarilla=umbral_amarilla,
        umbral_roja=umbral_roja,
    )
    resultado["detalles_calculo"]["tipo_calculo"] = tipo
    return resultado
