"""confirmar_proyecto_pendiente() (POST /proyectos/pendientes/{clave}/confirmar)
-- debe espejar potencia_ac_kw hacia proyectos.potencia_instalada_kwp, mismo
criterio que upsert_info_tecnica() (fix 2026-08-19: pese al nombre, ese campo
guarda la potencia AC, no la DC).

Bug real (auditoría de Proyectos 2026-08-27, hallazgo #3): este endpoint
guardaba potencia_ac_kw en ProyectoInfoTecnica pero nunca lo espejaba --
un proyecto creado o vinculado desde acá (el camino más común de creación,
vía candidatos de Sun Factory) quedaba con potencia_instalada_kwp en NULL
para siempre, salvo que alguien volviera a editar Información técnica a
mano. 35 proyectos en producción con este vacío, la mayoría creados así."""
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401
from app.models import Proyecto
from app.models.proyectos import ProyectoInfoTecnica
from app.schemas.proyectos import ProyectoPendienteConfirmar
from app.api.v1 import proyectos as proyectos_api


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


@pytest.fixture(autouse=True)
def _sin_syncs_externos(monkeypatch):
    """sincronizar_datos_unergy_si_aplica/ubicacion_tsf/info_tecnica_solenium
    hacen llamadas de red reales -- no son lo que este test cubre."""
    monkeypatch.setattr(proyectos_api, "sincronizar_datos_unergy_si_aplica", lambda p, db: None)
    monkeypatch.setattr(proyectos_api, "sincronizar_ubicacion_tsf_si_aplica", lambda p, db: None)
    monkeypatch.setattr(proyectos_api, "sincronizar_info_tecnica_solenium_si_aplica", lambda p, db: None)


CANDIDATO_CREAR = {
    "clave": "sf-123", "tipo_sugerencia": "crear",
    "nombre_sugerido": "GD Prueba", "tipo_proyecto_sugerido": "gd",
    "estado_sugerido": "en_desarrollo", "potencia_ac_kw": 990.0,
}


def test_crear_desde_pendiente_espeja_potencia_ac_a_potencia_instalada(db, monkeypatch):
    monkeypatch.setattr(proyectos_api, "resolver_pendientes", lambda db: [CANDIDATO_CREAR])

    resultado = proyectos_api.confirmar_proyecto_pendiente(
        clave="sf-123", body=ProyectoPendienteConfirmar(), forzar=False, db=db, _=None,
    )

    proyecto = db.get(Proyecto, resultado.id)
    it = db.query(ProyectoInfoTecnica).filter_by(proyecto_id=proyecto.id).first()
    assert it.potencia_ac_kw == 990.0
    assert proyecto.potencia_instalada_kwp == 990.0, (
        "potencia_instalada_kwp no debe quedar en NULL cuando sí hay potencia_ac_kw disponible"
    )


def test_no_pisa_potencia_instalada_ya_diligenciada_a_mano(db, monkeypatch):
    """Si alguien ya cargó potencia_instalada_kwp a mano (valor distinto al
    que trae el candidato), confirmar el pendiente no debe pisarlo."""
    candidato = {**CANDIDATO_CREAR, "clave": "sf-456", "tipo_sugerencia": "vincular", "proyecto_id": 1}
    monkeypatch.setattr(proyectos_api, "resolver_pendientes", lambda db: [candidato])

    p = Proyecto(id=1, nombre_comercial="Ya existente", potencia_instalada_kwp=500.0)
    db.add(p)
    db.commit()

    resultado = proyectos_api.confirmar_proyecto_pendiente(
        clave="sf-456", body=ProyectoPendienteConfirmar(), forzar=False, db=db, _=None,
    )

    assert resultado.potencia_instalada_kwp == 500.0
