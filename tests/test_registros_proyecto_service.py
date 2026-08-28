"""Servicio de la seccion "Registros" contra una base sqlite en memoria.

El test central es `test_el_mismo_dato_desde_dos_documentos_no_se_duplica`: es la
regla entera del modulo. Si eso deja de cumplirse, el resto del diseno no sirve.
"""

from datetime import date

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.models.base import Base
from app.models.proyectos import Proyecto
from app.models.registros_proyecto import (
    ArchivoDocumentoProyecto, DocumentoProyecto, EstadoDocumento, ParametroProyecto,
)
from app.services.registros_proyecto import service
from app.services.registros_proyecto.catalogo_items import Proceso


@compiles(JSONB, "sqlite")
def _j(e, c, **k):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _b(e, c, **k):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[
        Proyecto.__table__, DocumentoProyecto.__table__,
        ArchivoDocumentoProyecto.__table__, ParametroProyecto.__table__,
    ])
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture
def proyecto(db):
    p = Proyecto(nombre_comercial="MGS 0092 - San Luis de Since")
    db.add(p)
    db.commit()
    return p


# ---------------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------------
def test_la_casilla_se_crea_perezosamente_y_no_se_duplica(db, proyecto):
    a = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    b = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    assert a.id == b.id
    assert a.estado == EstadoDocumento.PENDIENTE
    assert db.scalar(select(DocumentoProyecto).where(
        DocumentoProyecto.proyecto_id == proyecto.id)) is not None


def test_rechaza_un_item_que_no_esta_en_el_catalogo(db, proyecto):
    with pytest.raises(ValueError, match="no existe en el catalogo"):
        service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "99")


def test_rechaza_un_proyecto_inexistente(db):
    with pytest.raises(ValueError, match="no existe"):
        service.get_or_create_documento(db, 9999, Proceso.SIC, "01")


def test_montar_un_archivo_marca_la_casilla_como_cargada(db, proyecto):
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "08")
    service.agregar_archivo(db, doc, {"url": "https://drive/x", "nombre_archivo": "Corriente-498197.pdf"})
    db.refresh(doc)
    assert doc.estado == EstadoDocumento.CARGADO


def test_quitar_el_ultimo_archivo_devuelve_la_casilla_a_pendiente(db, proyecto):
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "08")
    a = service.agregar_archivo(db, doc, {"url": "https://drive/x"})
    service.eliminar_archivo(db, a)
    db.refresh(doc)
    assert doc.estado == EstadoDocumento.PENDIENTE
    assert doc.archivos == []


def test_un_item_multiple_admite_varios_archivos(db, proyecto):
    """El item 08 lleva seis certificados: uno por transformador."""
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "08")
    for n in ("498197", "498198", "498199"):
        service.agregar_archivo(db, doc, {"url": f"https://drive/{n}"})
    db.refresh(doc)
    assert len(doc.archivos) == 3


def test_un_item_no_multiple_rechaza_el_segundo_archivo(db, proyecto):
    """La hoja de vida es una sola: montar dos seria tener dos verdades."""
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    service.agregar_archivo(db, doc, {"url": "https://drive/hv1"})
    with pytest.raises(ValueError, match="un solo archivo"):
        service.agregar_archivo(db, doc, {"url": "https://drive/hv2"})


def test_no_acepta_un_estado_invalido(db, proyecto):
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    with pytest.raises(ValueError, match="Estado invalido"):
        service.actualizar_documento(db, doc, {"estado": "APROBADO_POR_XM"})


# ---------------------------------------------------------------------------
# Parametros: la regla del modulo
# ---------------------------------------------------------------------------
def test_el_mismo_dato_desde_dos_documentos_no_se_duplica(db, proyecto):
    """La serie del medidor sale de la hoja de vida y se repite en el acta.

    Guardarla desde los dos documentos tiene que dejar UNA fila, con el valor
    mas reciente y la fuente de verdad actualizada -- no dos filas en conflicto.
    """
    hoja = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    acta = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "13")

    service.guardar_parametros(db, proyecto.id, [{
        "clave": "medidor.numero_de_serie", "valor": "88866569",
        "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1,
        "documento_origen_id": hoja.id,
    }])
    service.guardar_parametros(db, proyecto.id, [{
        "clave": "medidor.numero_de_serie", "valor": "88866569",
        "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1,
        "documento_origen_id": acta.id,
    }])

    filas = list(db.scalars(select(ParametroProyecto).where(
        ParametroProyecto.clave == "medidor.numero_de_serie")))
    assert len(filas) == 1
    assert filas[0].valor == "88866569"
    assert filas[0].documento_origen_id == acta.id


def test_el_medidor_principal_y_el_de_respaldo_son_filas_distintas(db, proyecto):
    """Misma clave, distinto equipo: son dos datos, no una duplicacion."""
    service.guardar_parametros(db, proyecto.id, [
        {"clave": "medidor.numero_de_serie", "valor": "88866569",
         "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1},
        {"clave": "medidor.numero_de_serie", "valor": "88866570",
         "equipo_tipo": "MEDIDOR_RESPALDO", "equipo_posicion": 1},
    ])
    filas = list(db.scalars(select(ParametroProyecto).where(
        ParametroProyecto.clave == "medidor.numero_de_serie")))
    assert sorted(f.valor for f in filas) == ["88866569", "88866570"]


def test_los_tres_transformadores_de_corriente_son_tres_filas(db, proyecto):
    """Los certificados 498197/98/99 del expediente real, uno por fase."""
    service.guardar_parametros(db, proyecto.id, [
        {"clave": "tc.cert_calibracion_numero_certificado_1ra_relacion",
         "valor": numero, "equipo_tipo": "TC", "equipo_posicion": pos}
        for pos, numero in enumerate(("498197", "498198", "498199"), start=1)
    ])
    filas = list(db.scalars(select(ParametroProyecto).where(
        ParametroProyecto.equipo_tipo == "TC")))
    assert len(filas) == 3
    assert sorted(f.valor for f in filas) == ["498197", "498198", "498199"]


def test_un_dato_del_proyecto_se_guarda_una_vez_aunque_se_mande_con_equipo(db, proyecto):
    service.guardar_parametros(db, proyecto.id, [
        {"clave": "frontera.nombre_frontera", "valor": "MGS 0092 - San Luis de Since"},
        {"clave": "frontera.nombre_frontera", "valor": "MGS 0092 - San Luis de Since",
         "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1},
    ])
    filas = list(db.scalars(select(ParametroProyecto).where(
        ParametroProyecto.clave == "frontera.nombre_frontera")))
    assert len(filas) == 1
    assert (filas[0].equipo_tipo, filas[0].equipo_posicion) == ("", 0)


def test_guardar_llena_las_columnas_tipadas(db, proyecto):
    service.guardar_parametros(db, proyecto.id, [
        {"clave": "frontera.latitud", "valor": "9.21189898140427"},
        {"clave": "medidor.fecha_calibracion", "valor": "2026-05-19",
         "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1},
    ])
    lat = db.scalar(select(ParametroProyecto).where(
        ParametroProyecto.clave == "frontera.latitud"))
    fecha = db.scalar(select(ParametroProyecto).where(
        ParametroProyecto.clave == "medidor.fecha_calibracion"))
    assert float(lat.valor_numero) == pytest.approx(9.21189898140427)
    assert lat.valor == "9.21189898140427"      # el texto exacto se conserva
    assert fecha.valor_fecha == date(2026, 5, 19)


# ---------------------------------------------------------------------------
# Vistas compuestas
# ---------------------------------------------------------------------------
def test_el_formulario_dice_en_que_otros_documentos_aparece_cada_dato(db, proyecto):
    form = service.formulario_item(db, proyecto.id, Proceso.SIC, "13")
    serie = next(c for c in form["campos"]
                 if c["clave"] == "medidor.numero_de_serie"
                 and c["equipo_tipo"] == "MEDIDOR_PRINCIPAL")
    otros = {(o["proceso"], o["item"]) for o in serie["tambien_en"]}
    assert (Proceso.SIC, "01") in otros      # hoja de vida
    assert (Proceso.SIC, "07") in otros      # certificado de calibracion
    assert (Proceso.SIC, "13") not in otros  # no se lista a si mismo


def test_el_formulario_marca_lo_que_ya_vino_de_otro_documento(db, proyecto):
    hoja = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    service.guardar_parametros(db, proyecto.id, [{
        "clave": "medidor.numero_de_serie", "valor": "88866569",
        "equipo_tipo": "MEDIDOR_PRINCIPAL", "equipo_posicion": 1,
        "documento_origen_id": hoja.id,
    }])
    form = service.formulario_item(db, proyecto.id, Proceso.SIC, "13")
    serie = next(c for c in form["campos"]
                 if c["clave"] == "medidor.numero_de_serie"
                 and c["equipo_tipo"] == "MEDIDOR_PRINCIPAL")
    assert serie["valor"] == "88866569"
    assert serie["diligenciado_en_otro_documento"] is True


def test_el_resumen_trae_los_dos_procesos_con_su_avance(db, proyecto):
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    service.agregar_archivo(db, doc, {"url": "https://drive/hv"})

    resumen = service.resumen_proyecto(db, proyecto.id)
    procesos = {p["proceso"]: p for p in resumen["procesos"]}
    assert set(procesos) == {Proceso.SIC, Proceso.CND}
    assert procesos[Proceso.SIC]["total_items"] == 28
    assert procesos[Proceso.CND]["total_items"] == 10
    assert procesos[Proceso.SIC]["items_cargados"] == 1
    assert procesos[Proceso.CND]["avance_pct"] == 0


def test_el_resumen_puede_filtrarse_a_un_proceso(db, proyecto):
    resumen = service.resumen_proyecto(db, proyecto.id, Proceso.CND)
    assert [p["proceso"] for p in resumen["procesos"]] == [Proceso.CND]


def test_los_items_no_aplicables_no_castigan_el_avance(db, proyecto):
    """Marcar un item como NO_APLICA lo saca del denominador, no lo deja en rojo."""
    antes = service.resumen_proyecto(db, proyecto.id)["procesos"][0]["avance_pct"]
    for codigo in ("03", "05", "06", "09"):
        doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, codigo)
        service.actualizar_documento(db, doc, {"estado": EstadoDocumento.NO_APLICA})
    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    service.agregar_archivo(db, doc, {"url": "https://drive/hv"})

    despues = service.resumen_proyecto(db, proyecto.id)["procesos"][0]
    assert antes == 0
    assert despues["avance_pct"] == round(100 * 1 / 24)


def test_el_indice_resume_el_avance_de_los_dos_procesos(db, proyecto):
    otro = Proyecto(nombre_comercial="MGS 0077 - Chiriguana Norte 4")
    db.add(otro)
    db.commit()

    doc = service.get_or_create_documento(db, proyecto.id, Proceso.SIC, "01")
    service.agregar_archivo(db, doc, {"url": "https://drive/hv"})
    service.guardar_parametros(db, proyecto.id, [
        {"clave": "frontera.nombre_frontera", "valor": "MGS 0092 - San Luis de Since"}])

    filas = {f["proyecto_id"]: f for f in service.listar_proyectos(db)}
    assert set(filas) == {proyecto.id, otro.id}
    assert filas[proyecto.id]["sic"] == {"cargados": 1, "total": 28, "pct": round(100 / 28)}
    assert filas[proyecto.id]["cnd"]["pct"] == 0
    assert filas[proyecto.id]["parametros_diligenciados"] == 1
    # Un proyecto sin expediente aparece igual, en ceros: no se esconde.
    assert filas[otro.id]["sic"]["cargados"] == 0
    assert filas[otro.id]["parametros_diligenciados"] == 0
