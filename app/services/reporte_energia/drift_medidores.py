"""Detección de drift de medidores tras la clasificación diaria.

El aviso "el medidor ya muestra un valor distinto en Quoia" (ver MGS 0032
El Paso Norte 2026-08-05, curva_cambio() en utils.py) ya existía, pero
solo se calculaba al abrir el detalle de UNA frontera puntual -- invisible
para el resumen del día y la lista "Revisión de hoy" (pedido de Sara
2026-08-26: si el valor de un medidor cambió, debería aparecer marcado
para revisar, no quedar escondido hasta que alguien abra esa frontera).

Corre encadenado justo después de ejecutar_dia_background() (mismo
scheduler, ver _scheduled_reporte_energia en main.py) -- no como job aparte
en otro horario, para que quien entre a reportar ya vea el resultado
reflejado, sin depender de que alguien abra cada frontera una por una.

Reusa curvas.curva_medidor_en_vivo() -- la misma consulta liviana (1
variable, sin recuperación activa) que ya usa _construir_detalle(), con el
catálogo de nodos/borders cacheado (curvas._CACHE_TTL) para todo el lote en
vez de repetirlo por frontera.
"""
from __future__ import annotations

import traceback
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fronteras import Frontera
from app.models.proyectos import Proyecto
from app.models.reporte_energia import ReporteEnergiaGeneracion, ReporteEnergiaConsumo
from app.services.mgs.gaia_client import GaiaClient
from app.services.reporte_energia import curvas
from app.services.reporte_energia.utils import curva_a_lista, curva_cambio


def _revisar_tabla(
    db: Session, Modelo, gaia, mapa_nodo, borders, fecha: date, var_name: str, es_generacion: bool,
) -> int:
    filas = db.execute(
        select(Modelo, Frontera, Proyecto)
        .join(Frontera, Frontera.id == Modelo.frontera_id)
        .join(Proyecto, Proyecto.id == Frontera.proyecto_id, isouter=True)
        .where(Modelo.fecha == fecha, Modelo.revisar_manualmente.is_(False))
    ).all()

    marcadas = 0
    for rep, front, proyecto in filas:
        if not rep.curva_medidor_principal and not rep.curva_medidor_respaldo:
            continue  # nada persistido con qué comparar (Caso CGM sin medidor consultado, o fila vieja)
        meta = borders.get((front.codigo_frontera or "").strip().lower())
        if not meta:
            continue
        # Solo Generación -- Consumo no tiene un concepto de capacidad
        # efectiva definido todavía (decidido con Sara 2026-08-26).
        capacidad_efectiva_mw = (
            float(proyecto.potencia_instalada_kwp) / 1000
            if es_generacion and proyecto and proyecto.potencia_instalada_kwp is not None else None
        )
        try:
            curva_p, curva_r = curvas.curva_medidor_en_vivo(
                gaia, mapa_nodo, meta.get("main_meter"), meta.get("backup_meter"),
                str(fecha), front.codigo_frontera, var_name, capacidad_efectiva_mw,
            )
        except Exception:
            continue  # el aviso es informativo -- si Quoia falla acá, se sigue con las demás fronteras

        cambio_ppal = curva_cambio(rep.curva_medidor_principal, curva_a_lista(curva_p))
        cambio_resp = curva_cambio(rep.curva_medidor_respaldo, curva_a_lista(curva_r))
        if cambio_ppal or cambio_resp:
            rep.revisar_manualmente = True
            marcadas += 1
    return marcadas


def verificar_drift_medidores(db: Session, fecha: date) -> dict:
    """Vuelve a consultar Quoia (mismo helper liviano del detalle, sin
    recuperación activa) para cada fila SIN revisar_manualmente y, si el
    medidor ya muestra un valor distinto, marca revisar_manualmente=True.

    Retorna {'generacion': N, 'consumo': N} -- cuántas filas se marcaron en
    cada tabla."""
    gaia = GaiaClient()
    mapa_nodo = curvas.construir_mapa_medidor_nodo(gaia)
    borders = curvas.construir_mapa_borders(gaia)
    marcadas_gen = _revisar_tabla(db, ReporteEnergiaGeneracion, gaia, mapa_nodo, borders, fecha, "eae", True)
    marcadas_con = _revisar_tabla(db, ReporteEnergiaConsumo, gaia, mapa_nodo, borders, fecha, "iae", False)
    db.commit()
    return {"generacion": marcadas_gen, "consumo": marcadas_con}


def verificar_drift_medidores_background(fecha: date) -> dict:
    """Igual que verificar_drift_medidores(), pero abre su propia sesión de
    BD -- mismo patrón que ejecutar_dia_background() (orquestador.py),
    pensada para encadenarse después de clasificar en el scheduler."""
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        return verificar_drift_medidores(db, fecha)
    except Exception:
        db.rollback()
        print(f"[reporte_energia] verificar_drift_medidores fecha={fecha} FALLÓ:")
        print(traceback.format_exc())
        return {"generacion": 0, "consumo": 0, "error": True}
    finally:
        db.close()
