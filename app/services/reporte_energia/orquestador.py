"""Orquestador diario del pipeline de reporte de energía -- puerto de
process/src/main.py (repo Reporte-Energia).

Reemplaza el loop de main.py: en vez de recorrer el catálogo completo de
Quoia y mapear por nombre (mapeo.py), itera las fronteras YA registradas en
la base de datos de Operaciones (fuente de verdad: fronteras.proyecto_id +
proyectos.project_id_solenium, ya reconciliados por el equipo).

v1: fronteras con tipo 'generacion_consumo', 'consumo_auxiliar' o
'consumo_propio' se omiten (se reportan pero no se clasifican) -- el árbol
de Casos portado asume una frontera de un solo tipo (generación O consumo).
Confirmar con el equipo si hace falta cubrir esos tipos.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fronteras import Frontera, TipoFronteraEnum, EstadoFronteraEnum
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.services.mgs.gaia_client import GaiaClient
from app.services.mgs.solenium_client import SoleniumClient
from app.services.reporte_energia import curvas, clasificador, clasificador_consumo
from app.services.reporte_energia.utils import curva_a_lista

TIPOS_SOPORTADOS = {TipoFronteraEnum.generacion, TipoFronteraEnum.consumo}


def _construir_mapa_borders(gaia: GaiaClient) -> dict[str, dict]:
    """frt_code (lowercase) -> {border_id, main_meter, backup_meter} desde
    /api/cgm/v1/border/ (gaia.get_all_borders())."""
    mapa: dict[str, dict] = {}
    for proyecto in gaia.get_all_borders():
        for key in ("frt_generation", "frt_consumption"):
            frt = proyecto.get(key)
            if not frt:
                continue
            frt_code = (frt.get("frt_code") or "").strip().lower()
            if not frt_code:
                continue
            mapa[frt_code] = {
                "border_id": frt.get("id"),
                "main_meter": frt.get("main_meter"),
                "backup_meter": frt.get("backup_meter"),
            }
    return mapa


def _fronteras_activas(db: Session) -> list[tuple[Frontera, str | None]]:
    """(Frontera, project_id_solenium) de todas las fronteras activas con
    tipo soportado."""
    filas = db.execute(
        select(Frontera, Proyecto.project_id_solenium)
        .join(Proyecto, Proyecto.id == Frontera.proyecto_id, isouter=True)
        .where(
            Frontera.estado == EstadoFronteraEnum.activa,
            Frontera.codigo_frontera.is_not(None),
            Frontera.deleted_at.is_(None),
        )
    ).all()
    return [(f, sid) for f, sid in filas]


def _upsert_generacion(db: Session, frontera_id: int, fecha: date, resultado: dict) -> None:
    existente = db.execute(
        select(ReporteEnergiaGeneracion).where(
            ReporteEnergiaGeneracion.frontera_id == frontera_id,
            ReporteEnergiaGeneracion.fecha == fecha,
        )
    ).scalar_one_or_none()

    if existente is not None and existente.editado_manualmente:
        # No se pisa una corrección manual con el resultado automático de
        # una re-ejecución -- el reporte semiautomático depende de esto.
        return

    fila = existente or ReporteEnergiaGeneracion(frontera_id=frontera_id, fecha=fecha)
    fila.caso = resultado["caso"]
    fila.medidor_usado = resultado.get("medidor_usado")
    fila.energia_final_kwh = resultado.get("energia_final_kwh")
    fila.curva_final = curva_a_lista(resultado.get("curva_final"))
    fila.fp = resultado.get("fp")
    fila.fp_calculada = resultado.get("fp_calculada")
    fila.error_final_pct = resultado.get("error_final_pct")
    fila.energia_cgm_kwh = resultado.get("energia_cgm_kwh")
    fila.estado_reporte = resultado.get("estado_reporte")
    fila.energia_solenium_kwh = resultado.get("energia_solenium_kwh")
    fila.solenium_completo = resultado.get("solenium_completo")
    fila.nota_solenium = resultado.get("nota_solenium")
    fila.horas_rellenadas_reconectador = resultado.get("horas_rellenadas_reconectador")
    fila.horas_rellenadas_solenium = resultado.get("horas_rellenadas_solenium")
    fila.horas_rellenadas_historico = resultado.get("horas_rellenadas_historico")
    fila.recuperacion_datos = resultado.get("recuperacion_datos")
    fila.revisar_manualmente = bool(resultado.get("revisar_manualmente", False))
    fila.energia_medidor_principal_kwh = resultado.get("energia_medidor_principal_kwh")
    fila.energia_medidor_respaldo_kwh = resultado.get("energia_medidor_respaldo_kwh")
    fila.medidor_principal_completo = resultado.get("medidor_principal_completo")
    fila.medidor_respaldo_completo = resultado.get("medidor_respaldo_completo")
    if existente is None:
        db.add(fila)


def _upsert_consumo(db: Session, frontera_id: int, fecha: date, resultado: dict) -> None:
    existente = db.execute(
        select(ReporteEnergiaConsumo).where(
            ReporteEnergiaConsumo.frontera_id == frontera_id,
            ReporteEnergiaConsumo.fecha == fecha,
        )
    ).scalar_one_or_none()

    if existente is not None and existente.editado_manualmente:
        return

    fila = existente or ReporteEnergiaConsumo(frontera_id=frontera_id, fecha=fecha)
    fila.caso = resultado["caso"]
    fila.medidor_usado = resultado.get("medidor_usado")
    fila.energia_final_kwh = resultado.get("energia_final_kwh")
    fila.curva_final = curva_a_lista(resultado.get("curva_final"))
    fila.energia_cgm_kwh = resultado.get("energia_cgm_kwh")
    fila.estado_reporte = resultado.get("estado_reporte")
    fila.horas_rellenadas_historico = resultado.get("horas_rellenadas_historico")
    fila.recuperacion_datos = resultado.get("recuperacion_datos")
    fila.revisar_manualmente = bool(resultado.get("revisar_manualmente", False))
    if existente is None:
        db.add(fila)


def ejecutar_dia(db: Session, fecha: date) -> dict:
    """Corre la clasificación de Generación y Consumo para todas las
    fronteras activas, para una fecha dada, y guarda el resultado.

    Retorna un resumen {'generacion': {...}, 'consumo': {...}} con conteos
    por caso, para log/depuración -- el detalle real vive en la BD.
    """
    gaia = GaiaClient()
    sol = SoleniumClient()

    bordes = _construir_mapa_borders(gaia)
    mapa_medidor_nodo = curvas.construir_mapa_medidor_nodo(gaia)

    resumen_gen: dict[str, int] = {}
    resumen_con: dict[str, int] = {}
    omitidas: list[str] = []

    for frontera, project_id_solenium in _fronteras_activas(db):
        frt_code = frontera.codigo_frontera.strip().lower()
        border_meta = bordes.get(frt_code)
        pid_solenium = int(project_id_solenium) if project_id_solenium and project_id_solenium.isdigit() else None

        if frontera.tipo_frontera == TipoFronteraEnum.generacion:
            resultado = clasificador.clasificar_generacion(
                db, gaia, sol, frontera.id, frt_code, border_meta, pid_solenium, mapa_medidor_nodo, fecha,
            )
            _upsert_generacion(db, frontera.id, fecha, resultado)
            clave = str(resultado["caso"])
            resumen_gen[clave] = resumen_gen.get(clave, 0) + 1

        elif frontera.tipo_frontera == TipoFronteraEnum.consumo:
            resultado = clasificador_consumo.clasificar_consumo(
                db, gaia, frontera.id, frt_code, border_meta, mapa_medidor_nodo, fecha,
            )
            _upsert_consumo(db, frontera.id, fecha, resultado)
            clave = str(resultado["caso"])
            resumen_con[clave] = resumen_con.get(clave, 0) + 1

        else:
            omitidas.append(f"{frontera.nombre_frontera} ({frontera.tipo_frontera})")

    db.commit()
    return {"generacion": resumen_gen, "consumo": resumen_con, "omitidas": omitidas, "fecha": str(fecha)}
