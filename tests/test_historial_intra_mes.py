"""Historial intra-mes en el tab Proyectos de Cumplimiento.

El mes muestra el HISTORIAL, no una foto: una planta que cambió de modalidad a
mitad de mes aparece en todas las piscinas por las que pasó, cada una con su
ventana de días. Los contadores solo cuentan lo vigente a la fecha de corte.

Bug original: una planta liberada el 23-jul quedaba en (a) los 31 días de julio
y la piscina (e) salía vacía; solo aparecía en (e) el 1-ago.
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
from app.api.v1.cumplimiento import (
    get_plantas_contratos, _fecha_corte, _recortar, _restar_intervalos,
    _estado_segmento,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


_ids = iter(range(1, 10_000))


def _planta(db, nombre, **kw):
    p = Proyecto(
        id=next(_ids), nombre_comercial=nombre, sub_project=nombre.lower().replace(" ", "-"),
        tipo_proyecto="minigranja", estado="en_operacion", srv_representacion=True, **kw
    )
    db.add(p)
    db.flush()
    return p


def _sol(db, **kw):
    kw.setdefault("estado_solicitud", EstadoSolicitudAsicEnum.publicado)
    kw.setdefault("reemplaza_anterior", True)
    # SQLite: los server_default 'false' llegan como cadena truthy
    kw.setdefault("es_duplicado", False)
    kw.setdefault("uso_del_recurso", False)
    kw.setdefault("tipo_solicitud", TipoSolicitudAsicEnum.registro)
    db.add(AsicSolicitud(id=next(_ids), **kw))


def _contrato_venta(db, nombre, codigo, fin=date(2039, 12, 31)):
    c = PPAContrato(id=next(_ids), nombre_interno=nombre, tipo_contrato="venta",
                    numero_codigo_contrato=codigo, comprador_nombre="Terpel",
                    fecha_inicio=date(2025, 1, 1), fecha_fin=fin)
    db.add(c)
    db.flush()
    return c


def _fila_en_contrato(out, pool, pid):
    for ct in out["pools"][pool]:
        for p in ct.get("plantas") or []:
            if p["id"] == pid:
                return p
    return None


# ── Helpers de fechas (aritmética pura) ──────────────────────────────────────

def test_fecha_corte_mes_en_curso_es_hoy():
    hoy = date(2026, 7, 26)
    assert _fecha_corte(2026, 7, hoy) == hoy, "mes en curso: corta en hoy"
    assert _fecha_corte(2026, 3, hoy) == date(2026, 3, 31), "mes pasado: cierre de mes"
    assert _fecha_corte(2026, 9, hoy) == date(2026, 9, 30), "mes futuro: fin de mes"


def test_recortar_intersecta_con_el_mes():
    lo, hi = date(2026, 7, 1), date(2026, 7, 31)
    assert _recortar(date(2025, 1, 1), date(2026, 7, 23), lo, hi) == (lo, date(2026, 7, 23))
    assert _recortar(None, None, lo, hi) == (lo, hi), "bordes nulos = abiertos"
    assert _recortar(date(2026, 8, 1), None, lo, hi) is None, "no toca el mes"


def test_restar_intervalos_deja_los_dias_libres():
    mes = (date(2026, 7, 1), date(2026, 7, 31))
    # contrato del 1 al 23 → quedan libres del 24 al 31
    assert _restar_intervalos(mes, [(date(2026, 7, 1), date(2026, 7, 23))]) == [
        (date(2026, 7, 24), date(2026, 7, 31))
    ]
    # contrato en el medio → dos tramos libres
    assert _restar_intervalos(mes, [(date(2026, 7, 10), date(2026, 7, 20))]) == [
        (date(2026, 7, 1), date(2026, 7, 9)),
        (date(2026, 7, 21), date(2026, 7, 31)),
    ]
    # mes completo cubierto → sin residuo
    assert _restar_intervalos(mes, [mes]) == []
    assert _restar_intervalos(None, []) == []


def test_estado_segmento():
    corte = date(2026, 7, 26)
    assert _estado_segmento(date(2026, 7, 1), date(2026, 7, 23), corte) == "terminado"
    assert _estado_segmento(date(2026, 7, 24), date(2026, 7, 31), corte) == "vigente"
    assert _estado_segmento(date(2026, 7, 28), date(2026, 7, 31), corte) == "futuro"


# ── El caso que motivó el feature ────────────────────────────────────────────

def test_planta_liberada_a_mitad_de_mes_aparece_en_las_dos_piscinas(db):
    p = _planta(db, "MGS Liberada")
    c = _contrato_venta(db, "Terpel X", "TPL-X")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7777", contrato_interno="TPL-X",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2026, 7, 23))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)

    # (a) la conserva, con su ventana del mes y marcada como terminada
    fila_a = _fila_en_contrato(out, "ppa_venta_ungg", p.id)
    assert fila_a is not None, "no se borra del contrato: Terpel la tuvo 23 días"
    assert fila_a["segmento_inicio"] == "2026-07-01"
    assert fila_a["segmento_fin"] == "2026-07-23"
    assert fila_a["estado"] == "terminado"

    # (e) la recibe desde el día siguiente
    libres = [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == p.id]
    assert len(libres) == 1, "un tramo libre: del 24 al 31"
    assert libres[0]["segmento_inicio"] == "2026-07-24"
    assert libres[0]["segmento_fin"] == "2026-07-31"
    assert libres[0]["estado"] == "vigente"


def test_meses_vecinos_ven_una_sola_modalidad(db):
    p = _planta(db, "MGS Liberada Vecinos")
    c = _contrato_venta(db, "Terpel V", "TPL-V")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7778", contrato_interno="TPL-V",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2026, 7, 23))
    db.commit()

    jun = get_plantas_contratos(year=2026, month=6, db=db, _=None)
    assert _fila_en_contrato(jun, "ppa_venta_ungg", p.id)["estado"] == "vigente"
    assert [x for x in jun["pools"]["bolsa_venta_ungg"] if x["id"] == p.id] == []

    ago = get_plantas_contratos(year=2026, month=8, db=db, _=None)
    assert _fila_en_contrato(ago, "ppa_venta_ungg", p.id) is None
    libres = [x for x in ago["pools"]["bolsa_venta_ungg"] if x["id"] == p.id]
    assert libres[0]["segmento_inicio"] == "2026-08-01"
    assert libres[0]["segmento_fin"] == "2026-08-31"


def test_planta_asignada_todo_el_mes_no_genera_fila_de_bolsa(db):
    """Sin regresión: lo que antes no estaba en bolsa sigue sin estarlo."""
    p = _planta(db, "MGS Completa")
    c = _contrato_venta(db, "Terpel C", "TPL-C")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7779", contrato_interno="TPL-C",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    assert _fila_en_contrato(out, "ppa_venta_ungg", p.id)["estado"] == "vigente"
    assert out["pools"]["bolsa_venta_ungg"] == []
    assert out["pools"]["bolsa_venta_ungc"] == []


def test_planta_que_entra_a_contrato_a_mitad_de_mes_deja_tramo_previo(db):
    p = _planta(db, "MGS Entrante")
    c = _contrato_venta(db, "Terpel E", "TPL-E")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7780", contrato_interno="TPL-E",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2026, 7, 10), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    libres = [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == p.id]
    assert len(libres) == 1
    assert (libres[0]["segmento_inicio"], libres[0]["segmento_fin"]) == ("2026-07-01", "2026-07-09")
    assert libres[0]["estado"] == "terminado"


def test_no_inventa_bolsa_antes_de_iniciar_comercializacion(db):
    """Si la planta arrancó comercialización el mismo día que entró al contrato,
    no hay tramo fantasma 1→9 de julio."""
    p = _planta(db, "MGS Nueva", fecha_inicio_comercializacion=date(2026, 7, 10))
    c = _contrato_venta(db, "Terpel N", "TPL-N")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7781", contrato_interno="TPL-N",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2026, 7, 10), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    assert [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == p.id] == []


def test_tramo_liberado_con_sic_ungc_cae_en_f_no_en_e(db):
    """La modalidad del residuo se evalúa sobre el tramo: si al salir del
    contrato la planta queda con SIC comprador UNGC, es (f)."""
    p = _planta(db, "MGS A UNGC")
    c = _contrato_venta(db, "Terpel U", "TPL-U")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7782", contrato_interno="TPL-U",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2026, 7, 23))
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="9999",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="UNGC",
         fecha_inicio=date(2026, 7, 24), fecha_fin=None)
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    assert [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == p.id] == []
    ungc = [x for x in out["pools"]["bolsa_venta_ungc"] if x["id"] == p.id]
    assert len(ungc) == 1
    assert ungc[0]["segmento_inicio"] == "2026-07-24"
    assert ungc[0]["codigo_sic"] == "9999"


def test_dos_tramos_libres_en_el_mismo_mes(db):
    """Contrato solo del 10 al 20 → la planta queda con DOS filas en (e), una
    antes y otra después. El front las distingue por (id, segmento_inicio)."""
    p = _planta(db, "MGS Dos Tramos")
    c = _contrato_venta(db, "Terpel D", "TPL-D")
    _sol(db, proyecto_id=p.id, codigo_sic_contrato="7785", contrato_interno="TPL-D",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2026, 7, 10), fecha_fin=date(2026, 7, 20))
    db.commit()

    out = get_plantas_contratos(year=2026, month=7, db=db, _=None)
    tramos = [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == p.id]
    assert [(t["segmento_inicio"], t["segmento_fin"]) for t in tramos] == [
        ("2026-07-01", "2026-07-09"),
        ("2026-07-21", "2026-07-31"),
    ]
    claves = {(t["id"], t["segmento_inicio"]) for t in tramos}
    assert len(claves) == 2, "las dos filas deben ser distinguibles por clave"
    # y el contrato conserva su propio tramo
    assert _fila_en_contrato(out, "ppa_venta_ungg", p.id)["segmento_fin"] == "2026-07-20"


def test_planta_relevada_a_mitad_de_mes_pasa_a_bolsa(db):
    """Si otra planta la releva en el SIC el 26-feb, la saliente no desaparece:
    queda en (a) hasta el 25 y en bolsa del 26 en adelante."""
    saliente = _planta(db, "MGS Saliente")
    entrante = _planta(db, "MGS Entrante Relevo")
    c = _contrato_venta(db, "Terpel R", "TPL-R")
    # arranca antes del mes: el único tramo libre debe ser el posterior al relevo
    _sol(db, proyecto_id=saliente.id, codigo_sic_contrato="7786", contrato_interno="TPL-R",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31))
    _sol(db, proyecto_id=entrante.id, codigo_sic_contrato="7786", contrato_interno="TPL-R",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         tipo_solicitud=TipoSolicitudAsicEnum.modificacion,
         fecha_inicio=date(2026, 2, 26), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=2, db=db, _=None)
    fila = _fila_en_contrato(out, "ppa_venta_ungg", saliente.id)
    assert fila["segmento_fin"] == "2026-02-25", "recortada por el relevo"
    assert fila["estado"] == "terminado"
    libres = [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == saliente.id]
    assert [(t["segmento_inicio"], t["segmento_fin"]) for t in libres] == [
        ("2026-02-26", "2026-02-28")
    ]
    # Simétrico: la entrante tampoco estaba en contrato antes del relevo, así que
    # su tramo del 1 al 25 aparece en bolsa marcado como terminado.
    entrantes = [x for x in out["pools"]["bolsa_venta_ungg"] if x["id"] == entrante.id]
    assert [(t["segmento_inicio"], t["segmento_fin"], t["estado"]) for t in entrantes] == [
        ("2026-02-01", "2026-02-25", "terminado")
    ]
    assert _fila_en_contrato(out, "ppa_venta_ungg", entrante.id)["estado"] == "vigente"


# ── Contadores ───────────────────────────────────────────────────────────────

def test_contadores_solo_cuentan_vigentes(db):
    """Mes pasado (corte = cierre de mes) para que el resultado no dependa de
    cuándo se corra la suite."""
    liberada = _planta(db, "MGS Sale En Marzo")
    sigue = _planta(db, "MGS Sigue")
    c = _contrato_venta(db, "Terpel M", "TPL-M")
    _sol(db, proyecto_id=liberada.id, codigo_sic_contrato="7783", contrato_interno="TPL-M",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2026, 3, 23))
    _sol(db, proyecto_id=sigue.id, codigo_sic_contrato="7784", contrato_interno="TPL-M",
         codigo_sic_vendedor="UNGG", codigo_sic_comprador="TERP", contrato_ppa_id=c.id,
         fecha_inicio=date(2025, 1, 1), fecha_fin=date(2039, 12, 31))
    db.commit()

    out = get_plantas_contratos(year=2026, month=3, db=db, _=None)
    assert out["fecha_corte"] == "2026-03-31"
    # (a) lista las dos, pero solo una sigue vigente al cierre
    assert out["counts"]["ppa_venta_ungg"] == 2
    assert out["counts_vigentes"]["ppa_venta_ungg"] == 1
    assert out["counts_terminados"]["ppa_venta_ungg"] == 1
    # (e) recibe el tramo del 24 al 31, vigente al cierre
    assert out["counts"]["bolsa_venta_ungg"] == 1
    assert out["counts_vigentes"]["bolsa_venta_ungg"] == 1
    assert out["counts_terminados"]["bolsa_venta_ungg"] == 0
