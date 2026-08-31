"""Informe de Puesta en Marcha -- fusión de proyecto_inicio_operacion en
proyecto_informe_om (2026-08-31). Cubre: guardado unificado en un solo PUT
(checklist + fechas + pendientes + estado), los 4 semáforos de checklist
sobre la forma estructurada nueva, y el conteo de checklist en _kpis()."""
import pytest
from sqlalchemy import create_engine, BigInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models import Proyecto
from app.models.informe_om import ProyectoInformeOM
from app.api.v1 import informe_om as api
from app.schemas.informe_om import (
    InformeOMFicha, ChecklistFusionSolar, ChecklistFrontera,
    ChecklistEstacionMeteo, ChecklistReconectador, ItemChecklist,
    ItemChecklistConEvidencia, InversorLimitado, PendienteItem,
)


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _proyecto(db, id=1):
    p = Proyecto(id=id, nombre_comercial="MGS Test")
    db.add(p)
    db.commit()
    return p


# ── Guardado unificado ───────────────────────────────────────────────────────

def test_put_guarda_checklist_fechas_pendientes_y_estado_en_un_solo_request(db, monkeypatch):
    """Antes de la fusión, no existía ningún endpoint capaz de guardar estos
    campos -- este es justo el hueco que se cierra."""
    _proyecto(db)
    monkeypatch.setattr(api, "_inversores_solenium", lambda p: [])
    monkeypatch.setattr(api, "_frontera_live", lambda p, db: {"principal": None, "respaldo": None})

    body = InformeOMFicha(
        estado="en_revision",
        empresa_contratista="Contratista SAS",
        fecha_energizacion="2026-08-01",
        fecha_inicio_operacion="2026-08-15",
        pendientes=[PendienteItem(descripcion="Falta poliza", responsable="Juan")],
        checklist_frontera=ChecklistFrontera(
            principal=ItemChecklistConEvidencia(estado="aprobado", evidencia=[{"id": "1", "nombre": "a.jpg", "url": "http://x/a.jpg"}]),
            respaldo=ItemChecklistConEvidencia(estado="aprobado", evidencia=[{"id": "2", "nombre": "b.jpg", "url": "http://x/b.jpg"}]),
        ),
    )
    resultado = api.guardar(proyecto_id=1, body=body, db=db, _=None)

    assert resultado.ficha.estado == "en_revision"
    assert resultado.ficha.empresa_contratista == "Contratista SAS"
    assert str(resultado.ficha.fecha_inicio_operacion) == "2026-08-15"
    assert len(resultado.ficha.pendientes) == 1
    assert resultado.ficha.pendientes[0].descripcion == "Falta poliza"
    assert resultado.frontera_estado == "aprobado"

    # persiste de verdad, no solo en la respuesta
    f = db.query(ProyectoInformeOM).filter_by(proyecto_id=1).first()
    assert f.estado == "en_revision"
    assert f.empresa_contratista == "Contratista SAS"
    assert len(f.pendientes) == 1


def test_put_no_sobreescribe_evidencia_arquitectura_al_guardar_checklist(db, monkeypatch):
    """Un PUT posterior que solo cambia checklist no debe perder la evidencia
    de arquitectura ya subida por otro endpoint."""
    _proyecto(db)
    monkeypatch.setattr(api, "_inversores_solenium", lambda p: [])
    monkeypatch.setattr(api, "_frontera_live", lambda p, db: {"principal": None, "respaldo": None})

    f = ProyectoInformeOM(proyecto_id=1, evidencia_arquitectura=[{"id": "x", "nombre": "diagrama.png", "url": "http://x"}])
    db.add(f)
    db.commit()

    body = InformeOMFicha(evidencia_arquitectura=[{"id": "x", "nombre": "diagrama.png", "url": "http://x"}])
    resultado = api.guardar(proyecto_id=1, body=body, db=db, _=None)
    assert len(resultado.ficha.evidencia_arquitectura) == 1


# ── Semáforos de checklist ───────────────────────────────────────────────────

def test_fusion_solar_aprueba_solo_con_starlink_datos_coherentes_evidencia_y_sin_limitados():
    ok = {
        "starlink": {"estado": "aprobado"},
        "datos_coherentes": {"estado": "aprobado"},
        "evidencia": ["foto.jpg"],
        "inversores": [{"id": 1, "limitado": False}],
    }
    assert api._fusion_solar_estado(ok) == "aprobado"


def test_fusion_solar_pendiente_si_algun_inversor_limitado():
    c = {
        "starlink": {"estado": "aprobado"},
        "datos_coherentes": {"estado": "aprobado"},
        "evidencia": ["foto.jpg"],
        "inversores": [{"id": 1, "limitado": True, "motivo_limitacion": "Sombra"}],
    }
    assert api._fusion_solar_estado(c) == "pendiente"


def test_fusion_solar_pendiente_sin_checklist():
    assert api._fusion_solar_estado(None) == "pendiente"
    assert api._fusion_solar_estado({}) == "pendiente"


def test_frontera_aprueba_solo_con_ambos_medidores_y_evidencia():
    ok = {
        "principal": {"estado": "aprobado", "evidencia": ["a.jpg"]},
        "respaldo": {"estado": "aprobado", "evidencia": ["b.jpg"]},
    }
    assert api._frontera_estado(ok) == "aprobado"

    sin_evidencia = {
        "principal": {"estado": "aprobado", "evidencia": []},
        "respaldo": {"estado": "aprobado", "evidencia": ["b.jpg"]},
    }
    assert api._frontera_estado(sin_evidencia) == "pendiente"


def test_estacion_meteo_aprueba_solo_si_todos_los_items_estan_aprobados():
    todos_aprobados = {k: {"estado": "aprobado"} for k in api._METEO_KEYS}
    todos_aprobados["reporta_datos"]["evidencia"] = ["x.jpg"]
    assert api._estacion_meteo_estado(todos_aprobados) == "aprobado"

    falta_uno = dict(todos_aprobados)
    falta_uno["poa"] = {"estado": "pendiente"}
    assert api._estacion_meteo_estado(falta_uno) == "pendiente"


def test_reconectador_pendiente_si_no_tiene():
    assert api._reconectador_estado({"tiene": False}) == "pendiente"
    assert api._reconectador_estado(None) == "pendiente"


def test_reconectador_aprueba_con_ambos_items_y_evidencia():
    c = {
        "tiene": True,
        "en_plataforma": {"estado": "aprobado"},
        "calidad_datos": {"estado": "aprobado"},
        "evidencia": ["x.jpg"],
    }
    assert api._reconectador_estado(c) == "aprobado"


# ── KPIs ──────────────────────────────────────────────────────────────────

def test_kpis_cuenta_checklist_aprobados_ademas_de_pruebas_y_eventos():
    f = ProyectoInformeOM(
        proyecto_id=1,
        protocolo_pruebas=[{"resultado": "conforme"}, {"resultado": "no_conforme"}],
        eventos_operativos=[{"estado": "cerrada"}],
        checklist_frontera={
            "principal": {"estado": "aprobado", "evidencia": ["a"]},
            "respaldo": {"estado": "aprobado", "evidencia": ["b"]},
        },
        checklist_reconectador={"tiene": False},
    )
    kpis = api._kpis(f)
    assert kpis.checklist_total == 4
    assert kpis.checklist_aprobados == 1  # solo frontera


def test_kpis_ficha_none_da_checklist_en_cero():
    kpis = api._kpis(None)
    assert kpis.checklist_aprobados == 0
    assert kpis.checklist_total == 4


# ── Evidencia por sección ────────────────────────────────────────────────────
# EvidenciaUploader.vue sube a POST /{basePath}/{id}/archivos/{seccion} con un
# `seccion` arbitrario -- estas rutas generalizadas reemplazan la vieja
# "/archivos/arquitectura" fija, una por cada uno de los 4 checklist.

import asyncio


def test_subir_evidencia_seccion_no_reconocida_da_404(db):
    _proyecto(db)

    class _ArchivoFalso:
        filename = "x.jpg"

    with pytest.raises(Exception) as exc:
        asyncio.run(api.subir_evidencia(proyecto_id=1, seccion="no-existe", archivo=_ArchivoFalso(), db=db, _=None))
    assert exc.value.status_code == 404


def test_eliminar_evidencia_seccion_no_reconocida_da_404(db):
    _proyecto(db)
    with pytest.raises(Exception) as exc:
        api.eliminar_evidencia(proyecto_id=1, seccion="no-existe", archivo_id="x", db=db, _=None)
    assert exc.value.status_code == 404


def test_subir_evidencia_checklist_frontera_principal_no_pisa_respaldo(db, monkeypatch):
    _proyecto(db)
    db.add(ProyectoInformeOM(
        proyecto_id=1,
        checklist_frontera={"principal": {"estado": "pendiente"}, "respaldo": {"estado": "aprobado", "evidencia": [{"id": "r1", "nombre": "b.jpg", "url": "http://x"}]}},
    ))
    db.commit()

    async def _fake_subir(archivo, carpetas):
        return {"id": "p1", "nombre": "a.jpg", "url": "http://x/a.jpg"}
    monkeypatch.setattr(api, "subir_archivo", _fake_subir)

    class _ArchivoFalso:
        filename = "a.jpg"

    resultado = asyncio.run(api.subir_evidencia(proyecto_id=1, seccion="checklist-frontera-principal", archivo=_ArchivoFalso(), db=db, _=None))
    assert resultado["id"] == "p1"

    f = db.query(ProyectoInformeOM).filter_by(proyecto_id=1).first()
    assert f.checklist_frontera["principal"]["evidencia"] == [{"id": "p1", "nombre": "a.jpg", "url": "http://x/a.jpg"}]
    assert f.checklist_frontera["respaldo"]["evidencia"] == [{"id": "r1", "nombre": "b.jpg", "url": "http://x"}]  # intacto


def test_eliminar_evidencia_checklist_reconectador(db):
    _proyecto(db)
    db.add(ProyectoInformeOM(
        proyecto_id=1,
        checklist_reconectador={"tiene": True, "evidencia": [{"id": "e1", "nombre": "x.jpg", "url": "http://x"}]},
    ))
    db.commit()

    resultado = api.eliminar_evidencia(proyecto_id=1, seccion="checklist-reconectador", archivo_id="e1", db=db, _=None)
    assert resultado == {"status": "ok"}

    f = db.query(ProyectoInformeOM).filter_by(proyecto_id=1).first()
    assert f.checklist_reconectador["evidencia"] == []
