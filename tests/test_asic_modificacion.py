"""POST /asic/modificacion — registrar una modificación sin recapturar el contrato.

Una modificación en GESCON es otra versión del MISMO código SIC. Lo único que
cambia es la fecha de fin, la planta inscrita, su % de despacho y su modalidad;
todo lo demás se hereda de la versión vigente. La fecha de entrada es la que
manda: la modificación no surte efecto antes de ese día.

Estas pruebas cubren la herencia, el corte de la versión anterior (incluido el
caso de un SIC con varias plantas coexistiendo, donde un relevo global se
llevaría por delante a las que no cambian) y las validaciones que impiden
registrar una modificación incoherente.
"""
import pytest
from fastapi import HTTPException
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from datetime import date

from app.models.base import Base
import app.models  # noqa: F401  registra todos los modelos en el metadata
from app.models import AsicSolicitud, PPAContrato
from app.models.proyectos import Proyecto
from app.models.asic import TipoSolicitudAsicEnum, EstadoSolicitudAsicEnum
from app.schemas.asic import AsicModificacionCreate
from app.utils.gescon_vigencia import resolver_vigencias
from app.api.v1 import asic as asic_api


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    """El endpoint inserta sin `id` (en Postgres lo pone la secuencia). SQLite
    solo autoincrementa un PK declarado INTEGER, no BIGINT."""
    return "INTEGER"


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
    # Explícitos: los server_default booleanos ("false") vuelven como texto bajo
    # SQLite y evalúan a True. En Postgres son booleanos de verdad.
    kw.setdefault("es_duplicado", False)
    kw.setdefault("uso_del_recurso", False)
    s = AsicSolicitud(id=next(_ids), **kw)
    db.add(s)
    return s


def _registro_base(db, **overrides):
    """Registro típico: un SIC con una planta, con todos los campos llenos."""
    planta = _planta(db, "MGS 0031 Marimonda")
    campos = dict(
        proyecto_id=planta.id,
        tipo_solicitud=TipoSolicitudAsicEnum.registro,
        codigo_sic_contrato="88806",
        codigo_sic_vendedor="UNGG",
        codigo_sic_comprador="BIAC",
        cedula_agente_vendedor="1037625350",
        cedula_agente_comprador="1107047209",
        contrato_interno="UNERGY 001-2024",
        nombre_interno="Terpel 1",
        nombre_contacto_solicitante="Laura",
        prioridad_limitacion=83,
        tipo_mercado="No regulado",
        tipo_asignacion="Prorrata",
        porcentaje_fncer=100,
        porcentaje_despacho=0.9,
        requerimiento_asic="20240419001",
        fecha_inicio=date(2024, 5, 1),
        fecha_fin=date(2030, 12, 31),
    )
    campos.update(overrides)
    s = _sol(db, **campos)
    db.commit()
    return planta, s


def _payload(**kw):
    base = dict(
        codigo_sic_contrato="88806",
        fecha_entrada=date(2026, 9, 1),
        requerimiento_asic="20260819007",
    )
    base.update(kw)
    return AsicModificacionCreate(**base)


def _crear(db, **kw):
    return asic_api.create_modificacion(data=_payload(**kw), db=db, _=None)


def _fila(db, id_):
    return db.query(AsicSolicitud).filter(AsicSolicitud.id == id_).first()


# ── Herencia: el punto del feature ────────────────────────────────────────

def test_hereda_los_campos_del_contrato_sin_recapturarlos(db):
    """Solo se envían SIC, fecha de entrada, requerimiento y lo que cambia:
    el resto lo pone el backend desde la versión vigente."""
    _, registro = _registro_base(db)
    nueva_planta = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    out = _crear(db, proyecto_id=nueva_planta.id, fecha_fin=date(2028, 6, 30))

    creada = _fila(db, out.modificacion.id)
    assert creada.tipo_solicitud == TipoSolicitudAsicEnum.modificacion
    assert creada.codigo_sic_contrato == "88806", "todo ocurre bajo el mismo SIC"
    assert creada.requerimiento_asic == "20260819007"
    # Heredados — sin ellos la fila se cae de Cumplimiento, que agrupa por contrato_interno
    assert creada.contrato_interno == "UNERGY 001-2024"
    assert creada.nombre_interno == "Terpel 1"
    assert creada.codigo_sic_vendedor == "UNGG"
    assert creada.codigo_sic_comprador == "BIAC"
    assert creada.cedula_agente_vendedor == "1037625350"
    assert creada.cedula_agente_comprador == "1107047209"
    assert creada.nombre_contacto_solicitante == "Laura"
    assert creada.prioridad_limitacion == 83
    assert creada.tipo_mercado == "No regulado"
    assert creada.tipo_asignacion == "Prorrata"
    assert float(creada.porcentaje_fncer) == 100
    # Lo que sí cambió
    assert creada.proyecto_id == nueva_planta.id
    assert creada.fecha_inicio == date(2026, 9, 1)
    assert creada.fecha_fin == date(2028, 6, 30)
    # No enviado -> heredado
    assert float(creada.porcentaje_despacho) == 0.9
    assert registro.contrato_interno == "UNERGY 001-2024"


def test_hereda_el_contrato_ppa_para_no_romper_cumplimiento(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1")
    db.add(ppa)
    db.flush()
    _, _ = _registro_base(db, contrato_ppa_id=ppa.id)

    out = _crear(db, fecha_fin=date(2029, 12, 31))

    assert _fila(db, out.modificacion.id).contrato_ppa_id == ppa.id


# ── Vigencia: la modificación entra el día indicado, ni antes ni después ──

def test_la_version_anterior_se_recorta_al_dia_previo(db):
    _, registro = _registro_base(db)
    nueva_planta = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    out = _crear(db, proyecto_id=nueva_planta.id)

    outs = asic_api.list_solicitudes(db=db, _=None, codigo_sic_contrato=None,
                                     contrato_interno=None, proyecto_id=None)
    por_id = {o.id: o for o in outs}
    assert por_id[registro.id].fecha_fin_efectiva == date(2026, 8, 31)
    assert por_id[registro.id].es_version_vigente is False
    assert por_id[out.modificacion.id].es_version_vigente is True
    # No destructivo: la fecha cruda del registro queda intacta
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)


def test_no_altera_los_meses_anteriores_a_la_fecha_de_entrada(db):
    """Con `hasta` en un mes previo, la modificación ni siquiera se procesa:
    Cumplimiento sigue viendo la planta original en ese mes."""
    planta, registro = _registro_base(db)
    nueva_planta = _planta(db, "MGS 0044 San Pelayo")
    db.commit()
    out = _crear(db, proyecto_id=nueva_planta.id)

    filas = db.query(AsicSolicitud).all()
    en_agosto = resolver_vigencias(filas, hasta=date(2026, 8, 31))
    assert en_agosto[registro.id].vigente is True
    assert en_agosto[out.modificacion.id].procesado is False

    en_septiembre = resolver_vigencias(filas, hasta=date(2026, 9, 30))
    assert en_septiembre[registro.id].vigente is False
    assert en_septiembre[out.modificacion.id].vigente is True


def test_adelantar_la_fecha_de_fin_sin_cambiar_de_planta(db):
    planta, registro = _registro_base(db)

    out = _crear(db, fecha_fin=date(2026, 12, 31))

    creada = _fila(db, out.modificacion.id)
    assert creada.proyecto_id == planta.id, "misma planta"
    assert creada.fecha_fin == date(2026, 12, 31)
    outs = {o.id: o for o in asic_api.list_solicitudes(
        db=db, _=None, codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None)}
    # Supersesión en sitio: la versión previa cede el 31/08, la nueva manda desde el 01/09
    assert outs[registro.id].fecha_fin_efectiva == date(2026, 8, 31)
    assert outs[creada.id].es_version_vigente is True


def test_atrasar_la_fecha_de_fin_extiende_el_contrato(db):
    _, registro = _registro_base(db)

    out = _crear(db, fecha_fin=date(2033, 12, 31))

    assert _fila(db, out.modificacion.id).fecha_fin == date(2033, 12, 31)
    assert "fin 31/12/2030 → 31/12/2033" in out.resumen


def test_cambiar_solo_el_porcentaje_de_despacho(db):
    planta, _ = _registro_base(db)

    out = _crear(db, porcentaje_despacho=0.55)

    creada = _fila(db, out.modificacion.id)
    assert float(creada.porcentaje_despacho) == 0.55
    assert creada.proyecto_id == planta.id
    assert creada.fecha_fin == date(2030, 12, 31), "la fecha de fin se hereda"
    assert "despacho 90% → 55%" in out.resumen


# ── SIC con varias plantas coexistiendo ───────────────────────────────────

def _sic_con_dos_plantas(db):
    planta_a, registro = _registro_base(db)
    planta_b = _planta(db, "MGS 0022 Yuan")
    coexistente = _sol(
        db, proyecto_id=planta_b.id,
        tipo_solicitud=TipoSolicitudAsicEnum.registro,
        codigo_sic_contrato="88806", contrato_interno="UNERGY 001-2024",
        nombre_interno="Terpel 1", requerimiento_asic="20240419002",
        fecha_inicio=date(2024, 6, 1), fecha_fin=date(2030, 12, 31),
        porcentaje_despacho=0.5, reemplaza_anterior=False,
    )
    db.commit()
    return planta_a, registro, planta_b, coexistente


def test_relevar_una_planta_no_saca_a_las_demas_del_sic(db):
    planta_a, registro, planta_b, coexistente = _sic_con_dos_plantas(db)
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    out = _crear(db, proyecto_id=entrante.id, proyecto_saliente_id=planta_a.id)

    outs = {o.id: o for o in asic_api.list_solicitudes(
        db=db, _=None, codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None)}
    # La planta que sale cierra el día antes de la entrada…
    assert _fila(db, registro.id).fecha_fin == date(2026, 8, 31)
    assert outs[registro.id].fecha_fin_efectiva == date(2026, 8, 31)
    # …y la que no cambia sigue vigente con su fecha original
    assert _fila(db, coexistente.id).fecha_fin == date(2030, 12, 31)
    assert outs[coexistente.id].es_version_vigente is True
    # La entrante coexiste, no releva a todo el SIC
    assert _fila(db, out.modificacion.id).reemplaza_anterior is False
    assert out.saliente is not None and out.saliente.id == registro.id


def test_la_planta_que_ya_salio_no_cuenta_para_la_siguiente_modificacion(db):
    """`es_version_vigente` significa "última versión de su SIC", no "en curso":
    hay que descartar por fecha o una planta que ya salió reaparece inscrita."""
    planta_a, _, planta_b, _ = _sic_con_dos_plantas(db)
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()
    _crear(db, proyecto_id=entrante.id, proyecto_saliente_id=planta_a.id)

    inscritas = asic_api._versiones_vigentes_sic(db, "88806", en_fecha=date(2027, 1, 1))
    plantas = {f.proyecto_id for f in inscritas}
    assert plantas == {planta_b.id, entrante.id}
    assert planta_a.id not in plantas

    with pytest.raises(HTTPException) as e:
        asic_api.create_modificacion(
            data=_payload(fecha_entrada=date(2027, 1, 1), requerimiento_asic="20270101009",
                          proyecto_saliente_id=planta_a.id),
            db=db, _=None)
    assert "no está inscrita" in e.value.detail


def test_sic_multiplanta_exige_saber_cual_planta_sale(db):
    _sic_con_dos_plantas(db)
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    with pytest.raises(HTTPException) as e:
        _crear(db, proyecto_id=entrante.id)
    assert e.value.status_code == 422
    assert "2 plantas" in e.value.detail
    assert "Marimonda" in e.value.detail and "Yuan" in e.value.detail


def test_sic_multiplanta_permite_modificar_una_sola_planta_en_sitio(db):
    _, registro, planta_b, coexistente = _sic_con_dos_plantas(db)

    out = _crear(db, proyecto_id=planta_b.id, porcentaje_despacho=0.7)

    creada = _fila(db, out.modificacion.id)
    assert creada.proyecto_id == planta_b.id
    assert float(creada.porcentaje_despacho) == 0.7
    assert creada.reemplaza_anterior is False, "conserva la coexistencia de la planta"
    outs = {o.id: o for o in asic_api.list_solicitudes(
        db=db, _=None, codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None)}
    assert outs[registro.id].es_version_vigente is True, "la otra planta no se toca"
    assert outs[coexistente.id].es_version_vigente is False


def test_no_deja_inscribir_dos_veces_la_misma_planta(db):
    planta_a, _, planta_b, _ = _sic_con_dos_plantas(db)

    with pytest.raises(HTTPException) as e:
        _crear(db, proyecto_id=planta_b.id, proyecto_saliente_id=planta_a.id)
    assert e.value.status_code == 422
    assert "ya está inscrita" in e.value.detail


# ── Modalidad de suministro de la planta entrante ─────────────────────────

def test_la_planta_entrante_puede_declarar_modalidad(db):
    _registro_base(db)
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    out = _crear(db, proyecto_id=entrante.id, modalidad="uso_recurso")

    creada = _fila(db, out.modificacion.id)
    assert creada.uso_del_recurso is True
    assert creada.es_duplicado is False


def test_la_modalidad_no_se_arrastra_a_una_planta_distinta(db):
    """es_duplicado / uso_del_recurso describen a la planta, no al contrato."""
    _registro_base(db, es_duplicado=True)
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    out = _crear(db, proyecto_id=entrante.id)

    creada = _fila(db, out.modificacion.id)
    assert creada.es_duplicado is False
    assert creada.uso_del_recurso is False


def test_la_modalidad_se_conserva_si_la_planta_no_cambia(db):
    _registro_base(db, es_duplicado=True)

    out = _crear(db, fecha_fin=date(2029, 1, 31))

    assert _fila(db, out.modificacion.id).es_duplicado is True


def test_modalidad_invalida_se_rechaza(db):
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, modalidad="bolsa")
    assert e.value.status_code == 422


# ── Validaciones ──────────────────────────────────────────────────────────

def test_sic_inexistente_da_404_explicito(db):
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, codigo_sic_contrato="00000")
    assert e.value.status_code == 404
    assert "00000" in e.value.detail


def test_no_se_puede_modificar_un_sic_que_solo_tiene_borradores(db):
    _registro_base(db, estado_solicitud=EstadoSolicitudAsicEnum.en_proceso)
    with pytest.raises(HTTPException) as e:
        _crear(db)
    assert e.value.status_code == 404


def test_la_fecha_de_entrada_debe_ser_posterior_al_inicio_vigente(db):
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, fecha_entrada=date(2024, 1, 1))
    assert e.value.status_code == 422
    assert "01/05/2024" in e.value.detail


def test_la_fecha_de_entrada_no_puede_pasarse_del_fin(db):
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, fecha_entrada=date(2029, 1, 1), fecha_fin=date(2028, 1, 1))
    assert e.value.status_code == 422
    assert "nacería vencida" in e.value.detail


def test_el_requerimiento_debe_ser_nuevo(db):
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, requerimiento_asic="20240419001")
    assert e.value.status_code == 422
    assert "requerimiento nuevo" in e.value.detail


def test_porcentaje_fuera_de_escala_se_rechaza(db):
    """0-1, no 0-100: el formulario viejo corrompió datos por esto."""
    _registro_base(db)
    with pytest.raises(HTTPException) as e:
        _crear(db, porcentaje_despacho=85)
    assert e.value.status_code == 422
    assert "fracción 0-1" in e.value.detail


def test_no_puede_extender_mas_alla_del_ppa_y_no_deja_rastro(db):
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1", fecha_fin=date(2030, 12, 31))
    db.add(ppa)
    db.flush()
    _, registro = _registro_base(db, contrato_ppa_id=ppa.id)
    antes = db.query(AsicSolicitud).count()

    with pytest.raises(HTTPException) as e:
        _crear(db, fecha_fin=date(2035, 12, 31))
    assert e.value.status_code == 422

    db.rollback()
    assert db.query(AsicSolicitud).count() == antes, "la modificación no se guardó"
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)


def test_el_relevo_fallido_no_cierra_la_planta_saliente(db):
    """Si la validación del PPA rechaza la modificación, la planta que iba a
    salir no puede quedar cerrada a medias."""
    ppa = PPAContrato(id=next(_ids), numero_codigo_contrato="UNERGY 001-2024",
                      nombre_interno="Terpel 1", fecha_fin=date(2030, 12, 31))
    db.add(ppa)
    db.flush()
    planta_a, registro, _, _ = _sic_con_dos_plantas(db)
    registro.contrato_ppa_id = ppa.id
    db.commit()
    entrante = _planta(db, "MGS 0044 San Pelayo")
    db.commit()

    with pytest.raises(HTTPException):
        _crear(db, proyecto_id=entrante.id, proyecto_saliente_id=planta_a.id,
               fecha_fin=date(2035, 12, 31))

    db.rollback()
    assert _fila(db, registro.id).fecha_fin == date(2030, 12, 31)


def test_estado_por_defecto_publicado(db):
    """Solo las publicadas cuentan para vigencia: una modificación radicada
    nace publicada salvo que se diga lo contrario."""
    _registro_base(db)
    out = _crear(db, fecha_fin=date(2029, 1, 31))
    assert _fila(db, out.modificacion.id).estado_solicitud == EstadoSolicitudAsicEnum.publicado

    out2 = asic_api.create_modificacion(
        data=_payload(fecha_entrada=date(2027, 1, 1), requerimiento_asic="20270101001",
                      estado_solicitud="en_proceso"),
        db=db, _=None)
    assert _fila(db, out2.modificacion.id).estado_solicitud == EstadoSolicitudAsicEnum.en_proceso


def test_modificar_una_modificacion_encadena_versiones(db):
    """La base es la última versión, no el registro original."""
    _, registro = _registro_base(db)
    primera = _crear(db, fecha_fin=date(2029, 12, 31))

    segunda = asic_api.create_modificacion(
        data=_payload(fecha_entrada=date(2027, 3, 1), requerimiento_asic="20270301001",
                      porcentaje_despacho=0.6),
        db=db, _=None)

    creada = _fila(db, segunda.modificacion.id)
    assert creada.fecha_fin == date(2029, 12, 31), "hereda de la modificación previa"
    outs = {o.id: o for o in asic_api.list_solicitudes(
        db=db, _=None, codigo_sic_contrato=None, contrato_interno=None, proyecto_id=None)}
    assert outs[registro.id].es_version_vigente is False
    assert outs[primera.modificacion.id].fecha_fin_efectiva == date(2027, 2, 28)
    assert outs[segunda.modificacion.id].es_version_vigente is True
