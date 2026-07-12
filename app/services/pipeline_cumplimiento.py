"""Pipeline mensual de cumplimiento PPA → datos XM de liquidación.

Encadena, para un (anio, mes) dado:

  1. Contratos PPA vigentes y sus plantas asignadas vía GESCON (AsicSolicitud).
  2. Energía real del mes por planta, tomada de las lecturas de frontera
     (``fronteras_lecturas``, fuente preferida) y, si no hay, de la generación
     diaria (``generacion_diaria``).
  3. Cruce con el compromiso mensual (min/max MWh) del contrato → snapshot en
     ``cumplimiento_mensual`` con ``origen='automatico'`` (upsert idempotente).
  4. Valoración de la liquidación (energía a facturar, compras/excedentes en
     bolsa) → filas en ``liquidacion_xm_datos`` enlazadas al snapshot.

Las funciones de cálculo (``agregar_energia_*`` y ``calcular_valores_cumplimiento``)
son puras y no tocan la base de datos, para poder testearlas con datos simulados.

La resolución de vigencias GESCON se reutiliza de ``app.api.v1.cumplimiento``
(importada de forma diferida dentro de ``run_pipeline_mensual`` para evitar el
import circular, ya que ese módulo importa este servicio en el endpoint).
"""
import logging
from datetime import date, datetime, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Cálculo puro (testeable, sin DB) ────────────────────────────────────────

def _en_mes(d, anio: int, mes: int) -> bool:
    """True si ``d`` (date o datetime) cae en (anio, mes). None → False."""
    if d is None:
        return False
    return d.year == anio and d.month == mes


def agregar_energia_lecturas_kwh(
    lecturas: Iterable, anio: int, mes: int,
) -> Optional[float]:
    """Suma la energía activa exportada (kWh) de las lecturas de frontera cuyo
    ``fecha_hora`` cae en (anio, mes).

    Devuelve None si no hay ninguna lectura con valor en el mes (para poder
    distinguir "sin dato" de "0 kWh" y así caer al respaldo de generación
    diaria). Los None individuales se ignoran (una lectura faltante no es 0).
    """
    total = 0.0
    hubo_dato = False
    for l in lecturas:
        if not _en_mes(getattr(l, "fecha_hora", None), anio, mes):
            continue
        val = getattr(l, "energia_activa_export_kwh", None)
        if val is None:
            continue
        total += float(val)
        hubo_dato = True
    if not hubo_dato:
        return None
    return round(total, 3)


def agregar_energia_generacion_kwh(
    generaciones: Iterable, anio: int, mes: int,
) -> Optional[float]:
    """Suma ``kwh_real`` de la generación diaria de un proyecto en (anio, mes).

    Devuelve None si no hay ningún día con dato real en el mes.
    """
    total = 0.0
    hubo_dato = False
    for g in generaciones:
        if not _en_mes(getattr(g, "fecha", None), anio, mes):
            continue
        val = getattr(g, "kwh_real", None)
        if val is None:
            continue
        total += float(val)
        hubo_dato = True
    if not hubo_dato:
        return None
    return round(total, 3)


def calcular_valores_cumplimiento(
    gen_kwh: Optional[float],
    min_mwh: Optional[float],
    max_mwh: Optional[float],
    tarifa_ppa_cop_kwh: Optional[float] = None,
    precio_bolsa_cop_kwh: Optional[float] = None,
) -> dict:
    """Deriva cumplimiento y valores de liquidación a partir de la energía real.

    Misma semántica que ``/cumplimiento/cerrar-periodo`` (compras = déficit vs.
    el mínimo, excedentes = sobre el máximo), pero recibiendo la energía en kWh
    ya agregada por el pipeline. Función pura: no consulta la base de datos.

    - ``estado_calc``: 'deficit' | 'excedente' | 'ok' | 'sin_compromisos'.
    - ``energia_facturable_kwh``: energía a facturar bajo el PPA, capada al
      máximo del contrato (o toda la generación si no hay compromisos).
    """
    gen_mwh = round((gen_kwh or 0.0) / 1000, 3)
    out = {
        "gen_total_mwh": gen_mwh,
        "compromiso_mwh": min_mwh,
        "compras_bolsa_mwh": None,
        "excedentes_bolsa_mwh": None,
        "compras_bolsa_cop": None,
        "excedentes_bolsa_cop": None,
        "precio_bolsa_promedio": precio_bolsa_cop_kwh,
        "tarifa_ppa_cop_mwh": tarifa_ppa_cop_kwh,
        "valoracion_contrato_cop": None,
        "estado_calc": "sin_compromisos",
        "energia_facturable_kwh": round(gen_kwh, 3) if gen_kwh is not None else 0.0,
    }

    if min_mwh is not None:
        max_val = max_mwh if max_mwh is not None else min_mwh
        compras = round(max(0.0, min_mwh - gen_mwh), 3)
        excedentes = round(max(0.0, gen_mwh - max_val), 3)
        out["compras_bolsa_mwh"] = compras
        out["excedentes_bolsa_mwh"] = excedentes
        if gen_mwh < min_mwh:
            out["estado_calc"] = "deficit"
        elif gen_mwh > max_val:
            out["estado_calc"] = "excedente"
        else:
            out["estado_calc"] = "ok"
        # Energía a facturar bajo el PPA: capada al máximo contratado.
        out["energia_facturable_kwh"] = round(min(gen_kwh or 0.0, max_val * 1000), 3)
        if precio_bolsa_cop_kwh is not None:
            out["compras_bolsa_cop"] = round(compras * 1000 * precio_bolsa_cop_kwh, 2)
            out["excedentes_bolsa_cop"] = round(excedentes * 1000 * precio_bolsa_cop_kwh, 2)

    if tarifa_ppa_cop_kwh is not None and gen_mwh > 0:
        out["valoracion_contrato_cop"] = round(gen_mwh * 1000 * tarifa_ppa_cop_kwh, 2)

    return out


# ── Acceso a DB (energía por proyecto, usuario del sistema) ──────────────────

def _energia_proyecto_kwh(db: Session, proyecto_id: int, anio: int, mes: int) -> dict:
    """Energía real del proyecto en (anio, mes).

    Prefiere lecturas de frontera (generación); si ninguna frontera tiene
    lectura, cae a la generación diaria. Devuelve dict con ``energia_kwh``,
    ``fuente`` ('frontera' | 'generacion_diaria' | None) y ``frontera_id`` (la
    frontera de generación con más energía, para etiquetar el dato XM).
    """
    from app.models.fronteras import Frontera, FronteraLectura, TipoFronteraEnum

    fronteras = (
        db.query(Frontera)
        .filter(
            Frontera.proyecto_id == proyecto_id,
            Frontera.deleted_at.is_(None),
            Frontera.tipo_frontera.in_([
                TipoFronteraEnum.generacion,
                TipoFronteraEnum.generacion_consumo,
            ]),
        )
        .all()
    )

    total = 0.0
    hubo_dato = False
    mejor_frontera_id: Optional[int] = None
    mejor_kwh = -1.0
    for f in fronteras:
        lecturas = (
            db.query(FronteraLectura)
            .filter(FronteraLectura.frontera_id == f.id)
            .all()
        )
        e = agregar_energia_lecturas_kwh(lecturas, anio, mes)
        if e is not None:
            total += e
            hubo_dato = True
            if e > mejor_kwh:
                mejor_kwh = e
                mejor_frontera_id = f.id

    if hubo_dato:
        return {"energia_kwh": round(total, 3), "fuente": "frontera", "frontera_id": mejor_frontera_id}

    # Respaldo: generación diaria del proyecto.
    from app.models.generacion import GeneracionDiaria

    generaciones = (
        db.query(GeneracionDiaria)
        .filter(GeneracionDiaria.proyecto_id == proyecto_id)
        .all()
    )
    e = agregar_energia_generacion_kwh(generaciones, anio, mes)
    if e is not None:
        frontera_id = fronteras[0].id if fronteras else None
        return {"energia_kwh": e, "fuente": "generacion_diaria", "frontera_id": frontera_id}

    return {"energia_kwh": None, "fuente": None, "frontera_id": (fronteras[0].id if fronteras else None)}


def _usuario_sistema_id(db: Session) -> Optional[int]:
    """Usuario bajo el que se crean las liquidaciones automáticas.

    Prefiere operaciones@unergy.io; si no, el primer admin; si no, cualquier
    usuario activo. Devuelve None si no hay ninguno (el pipeline entonces omite
    la creación de datos XM y solo persiste el cumplimiento).
    """
    from app.models.usuarios import Usuario

    u = db.query(Usuario).filter(Usuario.email == "operaciones@unergy.io").first()
    if u:
        return u.id
    u = db.query(Usuario).filter(Usuario.rol == "admin").order_by(Usuario.id).first()
    if u:
        return u.id
    u = db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.id).first()
    return u.id if u else None


# ── Orquestación ─────────────────────────────────────────────────────────────

def run_pipeline_mensual(
    db: Session, anio: int, mes: int, origen: str = "automatico",
) -> dict:
    """Corre el pipeline de cumplimiento + liquidación para (anio, mes).

    Idempotente: reprocesa contratos ya calculados (upsert) y regenera los datos
    XM automáticos del período (borra los enlazados a cada snapshot antes de
    recrearlos). No sobrescribe snapshots ya facturados.

    Devuelve un resumen: ``status``, ``message``, ``cumplimiento_recs_processed``,
    ``liquidaciones_recs_created``.
    """
    # Import diferido: rompe el ciclo api.cumplimiento ↔ este servicio y reutiliza
    # la resolución de vigencias GESCON ya probada.
    from app.api.v1.cumplimiento import (
        _contratos_vigentes, _resolve_gescon, _get_bolsa_avg,
    )
    from app.models.contratos import PPACompromisoEnergia, PPATarifa
    from app.models.cumplimiento import CumplimientoMensual, EstadoCumplimientoEnum
    from app.models.liquidaciones import (
        Liquidacion, LiquidacionXMDato, TipoVentaLiqEnum, EstadoLiquidacionEnum,
    )

    periodo = date(anio, mes, 1)

    contratos = _contratos_vigentes(db, anio, mes)
    if not contratos:
        return {
            "status": "ok",
            "message": f"No hay contratos PPA vigentes en {anio}-{mes:02d}",
            "anio": anio, "mes": mes,
            "cumplimiento_recs_processed": 0,
            "liquidaciones_recs_created": 0,
        }

    compromisos_map = {
        c.contrato_id: c
        for c in db.query(PPACompromisoEnergia).filter(
            PPACompromisoEnergia.año == anio,
            PPACompromisoEnergia.mes == mes,
        ).all()
    }
    tarifas_map = {
        t.contrato_id: float(t.tarifa)
        for t in db.query(PPATarifa).filter(
            PPATarifa.año == anio, PPATarifa.mes == mes,
        ).all()
        if t.tarifa is not None
    }

    precio_bolsa = _get_bolsa_avg(db, anio, mes)["precio_promedio"]
    usuario_id = _usuario_sistema_id(db)

    cumplimiento_procesados = 0
    liquidaciones_creadas = 0
    liquidacion_por_proyecto: dict[tuple[int, date], Liquidacion] = {}

    for c in contratos:
        assignments = (
            _resolve_gescon(db, c.numero_codigo_contrato, anio, mes)
            if c.numero_codigo_contrato else []
        )

        # Energía por planta (una consulta por proyecto), escalada por % despacho.
        gen_kwh_total = 0.0
        hubo_energia = False
        detalle_plantas: list[dict] = []
        for asic in assignments:
            if not asic.proyecto_id:
                continue
            pct = float(asic.porcentaje_despacho or 0)
            ener = _energia_proyecto_kwh(db, asic.proyecto_id, anio, mes)
            if ener["energia_kwh"] is not None:
                aporte = ener["energia_kwh"] * pct
                gen_kwh_total += aporte
                hubo_energia = True
                detalle_plantas.append({
                    "proyecto_id": asic.proyecto_id,
                    "frontera_id": ener["frontera_id"],
                    "energia_kwh": round(aporte, 3),
                    "fuente": ener["fuente"],
                })

        gen_kwh = round(gen_kwh_total, 3) if hubo_energia else None

        compromiso = compromisos_map.get(c.id)
        min_mwh = (
            float(compromiso.energia_minima)
            if compromiso and compromiso.energia_minima is not None else None
        )
        max_mwh = (
            float(compromiso.energia_maxima)
            if compromiso and compromiso.energia_maxima is not None else None
        )
        tarifa = tarifas_map.get(c.id)

        valores = calcular_valores_cumplimiento(gen_kwh, min_mwh, max_mwh, tarifa, precio_bolsa)

        # ── Upsert del snapshot de cumplimiento ────────────────────────────────
        row = (
            db.query(CumplimientoMensual)
            .filter(
                CumplimientoMensual.contrato_ppa_id == c.id,
                CumplimientoMensual.anio == anio,
                CumplimientoMensual.mes == mes,
            )
            .first()
        )
        if row and row.estado == EstadoCumplimientoEnum.facturado:
            # No se toca un período ya facturado.
            continue

        if not row:
            row = CumplimientoMensual(contrato_ppa_id=c.id, anio=anio, mes=mes)
            db.add(row)

        row.gen_total_mwh = valores["gen_total_mwh"]
        row.compromiso_mwh = valores["compromiso_mwh"]
        row.compras_bolsa_mwh = valores["compras_bolsa_mwh"]
        row.excedentes_bolsa_mwh = valores["excedentes_bolsa_mwh"]
        row.precio_bolsa_promedio = valores["precio_bolsa_promedio"]
        row.compras_bolsa_cop = valores["compras_bolsa_cop"]
        row.excedentes_bolsa_cop = valores["excedentes_bolsa_cop"]
        row.tarifa_ppa_cop_mwh = valores["tarifa_ppa_cop_mwh"]
        row.valoracion_contrato_cop = valores["valoracion_contrato_cop"]
        row.estado = EstadoCumplimientoEnum.cerrado
        row.origen = origen
        row.fecha_calculo = datetime.now(timezone.utc)
        db.flush()  # asegura row.id para enlazar los datos XM
        cumplimiento_procesados += 1

        # ── Regenera los datos XM de este snapshot (idempotente) ───────────────
        db.query(LiquidacionXMDato).filter(
            LiquidacionXMDato.cumplimiento_mensual_id == row.id,
        ).delete(synchronize_session=False)

        if usuario_id is None:
            # Sin usuario del sistema no se pueden crear liquidaciones; el
            # cumplimiento igual queda persistido.
            continue

        for pl in detalle_plantas:
            if pl["frontera_id"] is None or not pl["energia_kwh"]:
                continue
            key = (pl["proyecto_id"], periodo)
            liq = liquidacion_por_proyecto.get(key)
            if liq is None:
                liq = (
                    db.query(Liquidacion)
                    .filter(
                        Liquidacion.proyecto_id == pl["proyecto_id"],
                        Liquidacion.periodo == periodo,
                        Liquidacion.deleted_at.is_(None),
                    )
                    .first()
                )
                if liq is None:
                    liq = Liquidacion(
                        proyecto_id=pl["proyecto_id"],
                        generado_por_id=usuario_id,
                        periodo=periodo,
                        tipo_venta=TipoVentaLiqEnum.ppa,
                        estado=EstadoLiquidacionEnum.iniciada,
                    )
                    db.add(liq)
                    db.flush()
                liquidacion_por_proyecto[key] = liq

            tarifa_kwh = float(tarifa) if tarifa is not None else 0.0
            energia_kwh = pl["energia_kwh"]
            db.add(LiquidacionXMDato(
                liquidacion_id=liq.id,
                frontera_id=pl["frontera_id"],
                tipo_venta=TipoVentaLiqEnum.ppa,
                energia_kwh=energia_kwh,
                tarifa_aplicada_kwh=tarifa_kwh,
                valor_bruto_cop=round(energia_kwh * tarifa_kwh, 2),
                cumplimiento_mensual_id=row.id,
            ))
            liquidaciones_creadas += 1

    db.commit()

    return {
        "status": "ok",
        "message": (
            f"Pipeline {anio}-{mes:02d}: {cumplimiento_procesados} cumplimientos, "
            f"{liquidaciones_creadas} datos XM"
        ),
        "anio": anio, "mes": mes,
        "cumplimiento_recs_processed": cumplimiento_procesados,
        "liquidaciones_recs_created": liquidaciones_creadas,
    }
