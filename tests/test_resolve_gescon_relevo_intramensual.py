"""_resolve_gescon debe conservar a la planta saliente cuando el relevo entre
DOS PLANTAS DISTINTAS en el mismo codigo_sic_contrato ocurre a mitad de mes.

Bug real (SIC 89115, Terpel 2 = UNERGY 002-2024, febrero-2026):
  - asic 31: Baraya (proyecto 4), registro, 100%, fecha_inicio 2026-02-05,
    fecha_fin 2039-12-31, reemplaza_anterior=True.
  - asic 18: Yurbaqua (proyecto 56), modificación, 100%, fecha_inicio
    2026-02-26, fecha_fin 2039-12-31, reemplaza_anterior=True.
Antes del fix, el `active.clear()` del relevo borraba a Baraya sin importar
que estuvo vigente del 5 al 25 de febrero (21 días) — la matriz solo
mostraba a Yurbaqua (3 días) y esos 21 días no se contaban en ningún lado.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1.cumplimiento import _resolve_gescon


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Proyecto.__table__, AsicSolicitud.__table__, PPAContrato.__table__],
    )
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _planta(db, nombre):
    p = Proyecto(id=next(_ids), nombre_comercial=nombre)
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("reemplaza_anterior", True)
    db.add(AsicSolicitud(id=next(_ids), **kw))


CONTRATO = "UNERGY 002-2024"
SIC = "89115"


def _cargar_caso_baraya_yurbaqua(db):
    baraya = _planta(db, "Minigranja Solar Baraya")
    yurbaqua = _planta(db, "PSF - Yurbaqua")
    _sol(db, proyecto_id=baraya.id, codigo_sic_contrato=SIC, contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         fecha_solicitud=date(2026, 1, 24), fecha_inicio=date(2026, 2, 5),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
    _sol(db, proyecto_id=yurbaqua.id, codigo_sic_contrato=SIC, contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_solicitud=date(2026, 2, 13), fecha_inicio=date(2026, 2, 26),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
    db.commit()
    return baraya, yurbaqua


def _por_nombre(asics, nombre):
    return next((a for a in asics if a.proyecto.nombre_comercial == nombre), None)


def test_ambas_plantas_aparecen_en_el_mes_del_relevo(db):
    _cargar_caso_baraya_yurbaqua(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    assert len(asics) == 2, "deben aparecer ambas plantas, no solo la más reciente"
    nombres = {a.proyecto.nombre_comercial for a in asics}
    assert nombres == {"Minigranja Solar Baraya", "PSF - Yurbaqua"}


def test_baraya_queda_recortada_al_dia_anterior_al_relevo(db):
    _cargar_caso_baraya_yurbaqua(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    baraya = _por_nombre(asics, "Minigranja Solar Baraya")
    assert baraya.fecha_inicio == date(2026, 2, 5)
    assert baraya.fecha_fin == date(2026, 2, 25), (
        "la fecha_fin EFECTIVA debe recortarse al día anterior al relevo, "
        "aunque el registro real diga 2039-12-31"
    )


def test_yurbaqua_conserva_su_fecha_fin_real(db):
    _cargar_caso_baraya_yurbaqua(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    yurbaqua = _por_nombre(asics, "PSF - Yurbaqua")
    assert yurbaqua.fecha_inicio == date(2026, 2, 26)
    assert yurbaqua.fecha_fin == date(2039, 12, 31)


def test_dias_prorrateados_no_se_solapan_ni_sobrecuentan(db):
    """Reproduce el prorrateo real de _anual_meses_para_contrato: cada quien
    sus días, sin duplicar ni perder ninguno."""
    _cargar_caso_baraya_yurbaqua(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    first_day, last_day = date(2026, 2, 1), date(2026, 2, 28)
    total_dias = 0
    for a in asics:
        eff_start = max(first_day, a.fecha_inicio) if a.fecha_inicio else first_day
        eff_end = min(last_day, a.fecha_fin) if a.fecha_fin else last_day
        dias = max(0, (eff_end - eff_start).days + 1)
        total_dias += dias
        if a.proyecto.nombre_comercial == "Minigranja Solar Baraya":
            assert dias == 21   # 5 al 25 de febrero, inclusive
        else:
            assert dias == 3    # 26 al 28 de febrero, inclusive
    assert total_dias == 24     # <= 28 (días 1-4 no le pertenecen a este SIC)


def test_mes_anterior_al_relevo_baraya_sola_mes_completo(db):
    """Enero-2026: Baraya todavía no había empezado en este SIC (fecha_inicio
    5-feb) — no debe aparecer nada de este SIC."""
    _cargar_caso_baraya_yurbaqua(db)
    assert _resolve_gescon(db, CONTRATO, 2026, 1) == []


def test_mes_posterior_al_relevo_solo_yurbaqua_mes_completo(db):
    """Marzo-2026: Baraya ya quedó recortada al 25-feb (mes anterior) — su
    fecha_fin efectiva no debe filtrarse hacia marzo."""
    _cargar_caso_baraya_yurbaqua(db)
    asics = _resolve_gescon(db, CONTRATO, 2026, 3)
    assert len(asics) == 1
    assert asics[0].proyecto.nombre_comercial == "PSF - Yurbaqua"
    assert asics[0].fecha_fin == date(2039, 12, 31)


def test_modificacion_en_sitio_misma_planta_no_se_recorta(db):
    """Control: una modificación a LA MISMA planta (mismo proyecto_id, solo
    cambia %) no es un relevo — no debe generar ninguna versión recortada."""
    p = _planta(db, "Planta Estable")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="999", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro,
         fecha_solicitud=date(2025, 1, 1), fecha_inicio=date(2025, 1, 1),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="999", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_solicitud=date(2026, 2, 10), fecha_inicio=date(2026, 2, 15),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=0.5)
    db.commit()

    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    assert len(asics) == 1, "modificación en sitio no debe duplicar/recortar nada"
    assert float(asics[0].porcentaje_despacho) == 0.5
    assert asics[0].fecha_fin == date(2039, 12, 31)


def test_relevo_con_multiples_plantas_coexistentes_recorta_todas(db):
    """Si reemplaza_anterior=False dejó a dos plantas coexistiendo en el SIC y
    luego llega un relevo real (reemplaza_anterior=True), ambas deben quedar
    recortadas al día anterior, no solo una."""
    a = _planta(db, "Planta A")
    b = _planta(db, "Planta B")
    c = _planta(db, "Planta C")
    _sol(db, proyecto_id=a.id, codigo_sic_contrato="777", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro, reemplaza_anterior=True,
         fecha_solicitud=date(2025, 1, 1), fecha_inicio=date(2025, 1, 1),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=0.5)
    _sol(db, proyecto_id=b.id, codigo_sic_contrato="777", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro, reemplaza_anterior=False,
         fecha_solicitud=date(2025, 1, 1), fecha_inicio=date(2025, 1, 1),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=0.5)
    _sol(db, proyecto_id=c.id, codigo_sic_contrato="777", contrato_interno=CONTRATO,
         tipo_solicitud=TipoSolicitudAsicEnum.registro, reemplaza_anterior=True,
         fecha_solicitud=date(2026, 1, 20), fecha_inicio=date(2026, 2, 10),
         fecha_fin=date(2039, 12, 31), porcentaje_despacho=1.0)
    db.commit()

    asics = _resolve_gescon(db, CONTRATO, 2026, 2)
    assert len(asics) == 3
    a_out = _por_nombre(asics, "Planta A")
    b_out = _por_nombre(asics, "Planta B")
    c_out = _por_nombre(asics, "Planta C")
    assert a_out.fecha_fin == date(2026, 2, 9)
    assert b_out.fecha_fin == date(2026, 2, 9)
    assert c_out.fecha_fin == date(2039, 12, 31)
