"""La piscina COMPRA (b. ppa_compra_ungc) sale de GESCON, no del módulo PPA.

Antes: PPAContrato con tipo_contrato='compra' (compras GD a terceros
registradas a mano) — eso no es UNGC comprando en el MEM. Ahora: registros
publicados de asic_solicitudes con codigo_sic_comprador == 'UNGC', agrupados
por contrato_interno, con vigencia efectiva (relevos) recortada al mes.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.api.v1.cumplimiento import get_plantas_contratos


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)  # el endpoint toca varias tablas
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _planta(db, nombre):
    p = Proyecto(
        id=next(_ids), nombre_comercial=nombre, sub_project=nombre.lower().replace(" ", "-"),
        tipo_proyecto="minigranja", estado="en_operacion", srv_representacion=True,
    )
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("reemplaza_anterior", True)
    kw.setdefault("es_duplicado", False)  # SQLite: server_default 'false' es truthy
    kw.setdefault("tipo_solicitud", TipoSolicitudAsicEnum.registro)
    db.add(AsicSolicitud(id=next(_ids), **kw))


def test_compra_sale_de_gescon_no_del_modulo_ppa(db):
    p = _planta(db, "MGS Vendida a UNGC")
    # Registro GESCON: UNGG le vende a UNGC → debe aparecer en compra (b)
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="900",
         contrato_interno="UNGC-UNGG 001", codigo_sic_vendedor="UNGG",
         codigo_sic_comprador="UNGC",
         fecha_inicio=date(2026, 1, 1), fecha_fin=date(2039, 12, 31))
    # Contrato PPA tipo compra (GD a tercero) → NO debe aparecer
    otra = _planta(db, "GD Astrolumen")
    ppa = PPAContrato(id=next(_ids), nombre_interno="Compra Astrolumen",
                      tipo_contrato="compra", vendedor_nombre="EIG SAS",
                      fecha_inicio=date(2026, 3, 26), fecha_fin=date(2026, 9, 30))
    ppa.proyectos.append(otra)
    db.add(ppa)
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    nombres = [c["nombre"] for c in out["compra"]]
    assert "UNGC-UNGG 001" in nombres, "el registro GESCON con comprador UNGC debe listarse"
    assert "Compra Astrolumen" not in nombres, "los PPA tipo compra ya no alimentan esta piscina"
    card = next(c for c in out["compra"] if c["nombre"] == "UNGC-UNGG 001")
    assert card["vendedor_nombre"] == "UNGG"
    assert [pl["id"] for pl in card["plantas"]] == [p.id]
    # y pools/counts lo reflejan
    assert out["counts"]["ppa_compra_ungc"] == 1


def test_compra_respeta_vigencia_efectiva_y_mes(db):
    p = _planta(db, "Planta Relevada")
    q = _planta(db, "Planta Nueva")
    # p con comprador UNGC, relevada por q (también UNGC) desde el 1-mar-2026
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="901",
         contrato_interno="UNGC-UNGG 002", codigo_sic_comprador="UNGC",
         codigo_sic_vendedor="UNGG",
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31))
    _sol(db, proyecto_id=q.id, codigo_sic_contrato="901",
         contrato_interno="UNGC-UNGG 002", codigo_sic_comprador="UNGC",
         codigo_sic_vendedor="UNGG", tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_inicio=date(2026, 3, 1), fecha_fin=date(2039, 12, 31))
    db.commit()

    # Julio: solo la planta nueva (la relevada terminó efectivamente el 28-feb)
    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    card = next(c for c in out["compra"] if c["nombre"] == "UNGC-UNGG 002")
    assert [pl["id"] for pl in card["plantas"]] == [q.id]

    # Febrero: la relevada aún vigente. El relevo (efecto 1-mar) todavía no
    # existía desde la vista de febrero → su ventana es la cruda (semántica
    # histórica de _resolve_gescon: eventos futuros no desplazan ni recortan).
    out_feb = get_plantas_contratos(year=2026, month=2, db=db, _=None)
    card_feb = next(c for c in out_feb["compra"] if c["nombre"] == "UNGC-UNGG 002")
    assert {pl["id"] for pl in card_feb["plantas"]} == {p.id}

    # Marzo: el relevo ya tomó efecto → solo la nueva; la vieja quedó recortada
    # al 28-feb y su ventana efectiva ya no pisa el mes.
    out_mar = get_plantas_contratos(year=2026, month=3, db=db, _=None)
    card_mar = next(c for c in out_mar["compra"] if c["nombre"] == "UNGC-UNGG 002")
    assert [pl["id"] for pl in card_mar["plantas"]] == [q.id]


def test_bolsa_comercializador_expone_fechas_de_la_modalidad(db):
    """(f) Venta en Bolsa UNGC: cada planta trae la ventana del registro SIC
    que la pone en esa modalidad; fecha_fin nula = sigue vigente."""
    p = _planta(db, "MGS En Bolsa UNGC")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="903",
         codigo_sic_comprador="UNGC", codigo_sic_vendedor="UNGG",
         fecha_inicio=date(2026, 3, 1), fecha_fin=None)
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    entry = next(e for e in out["bolsa_comercializador"] if e["id"] == p.id)
    assert entry["fecha_inicio"] == "2026-03-01"
    assert entry["fecha_fin"] is None
    # la planta libre (sin SIC UNGC) no trae ventana
    libre = _planta(db, "MGS Libre")
    db.commit()
    out2 = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    entry_libre = next(e for e in out2["bolsa_libre"] if e["id"] == libre.id)
    assert entry_libre["fecha_inicio"] is None and entry_libre["fecha_fin"] is None


def test_bolsa_comercializador_fecha_fin_es_la_efectiva(db):
    """Si otra planta releva el SIC, la ventana mostrada termina el día anterior
    al relevo (fin EFECTIVO), no en la fecha_fin cruda (caso La Reserva)."""
    p = _planta(db, "Relevada Bolsa")
    q = _planta(db, "Nueva Bolsa")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="904",
         codigo_sic_comprador="UNGC", codigo_sic_vendedor="UNGG",
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31))
    _sol(db, proyecto_id=q.id, codigo_sic_contrato="904",
         codigo_sic_comprador="UNGC", codigo_sic_vendedor="UNGG",
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_inicio=date(2026, 6, 1), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    entry_p = next(e for e in out["bolsa_comercializador"] if e["id"] == p.id)
    assert entry_p["fecha_fin"] == "2026-05-31", "recortada por el relevo del 1-jun"
    entry_q = next(e for e in out["bolsa_comercializador"] if e["id"] == q.id)
    assert entry_q["fecha_inicio"] == "2026-06-01"
    assert entry_q["fecha_fin"] == "2039-12-31"

    # Vista histórica de mayo: el relevo aún no tomaba efecto → ventana cruda
    out_may = get_plantas_contratos(year=2026, month=5, db=db, _=None)
    entry_may = next(e for e in out_may["bolsa_comercializador"] if e["id"] == p.id)
    assert entry_may["fecha_fin"] == "2039-12-31"


def test_compra_externa_lista_ppas_de_compra_fuera_de_gescon(db):
    """(g) ppa_compra_externa: los PPA tipo compra sin GESCON van a su propia
    piscina 'plantas externas', con el detalle de a quién se le compra."""
    planta_ext = _planta(db, "GD Astrolumen")
    ppa = PPAContrato(id=next(_ids), nombre_interno="Compra Astrolumen",
                      tipo_contrato="compra", vendedor_nombre="EIG SAS",
                      vendedor_nit="900123456", tarifa_base=310.5,
                      fecha_inicio=date(2026, 3, 26), fecha_fin=date(2026, 9, 30))
    ppa.proyectos.append(planta_ext)
    db.add(ppa)
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    ext = out["compra_externa"]
    assert [c["nombre"] for c in ext] == ["Compra Astrolumen"]
    assert ext[0]["vendedor_nombre"] == "EIG SAS"
    assert ext[0]["vendedor_nit"] == "900123456"
    assert [pl["nombre"] for pl in ext[0]["plantas"]] == ["GD Astrolumen"]
    # y NO contamina la piscina GESCON (b)
    assert "Compra Astrolumen" not in [c["nombre"] for c in out["compra"]]
    # pools/counts estandarizados la exponen como (g)
    assert out["pools"]["ppa_compra_externa"] == ext
    assert out["counts"]["ppa_compra_externa"] == 1

    # fuera de vigencia (el PPA termina el 30-sep) → piscina vacía
    out_dic = get_plantas_contratos(year=2026, month=12, db=db, _=None)
    assert out_dic["compra_externa"] == []


def test_compra_externa_excluye_ppas_que_si_estan_en_gescon(db):
    """Un PPA de compra que sí llegó a GESCON ya se lista en (b): no debe
    duplicarse en (g)."""
    p = _planta(db, "MGS En Gescon")
    ppa = PPAContrato(id=next(_ids), nombre_interno="Compra Con Gescon",
                      tipo_contrato="compra", vendedor_nombre="UNGG",
                      fecha_inicio=date(2026, 1, 1), fecha_fin=date(2039, 12, 31))
    db.add(ppa)
    db.flush()
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="902",
         contrato_interno="UNGC-UNGG 003", codigo_sic_comprador="UNGC",
         codigo_sic_vendedor="UNGG", contrato_ppa_id=ppa.id,
         fecha_inicio=date(2026, 1, 1), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    assert out["compra_externa"] == [], "ya está en (b) vía GESCON"
    assert "UNGC-UNGG 003" in [c["nombre"] for c in out["compra"]]
