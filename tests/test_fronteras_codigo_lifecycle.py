"""Ciclo de vida de Frontera.codigo_frontera -- indice unico case-insensitive
que ignora fronteras borradas (migracion 077).

Antes: una frontera borrada quedaba con su codigo "atrapado" para siempre
(POST /fronteras la sobrescribia sin levantarle deleted_at, y confirmar
desde Quoia rechazaba con 409 aunque la fila real estuviera borrada). Y el
chequeo de POST /fronteras era sensible a mayusculas mientras el de
confirmar-desde-Quoia no, arriesgando dos filas para el mismo punto fisico.
"""
import datetime as dt
import types

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
import app.models  # noqa: F401 -- registra todos los modelos en Base.metadata
from app.models.proyectos import Proyecto
from app.models.fronteras import Frontera, FronteraQuoiaIgnorada
from app.schemas.fronteras import FronteraCreate, FronteraUpdate, FronteraQuoiaConfirmar, FronteraQuoiaIgnorar
from app.api.v1 import fronteras as api
from fastapi import HTTPException


@compiles(JSONB, "sqlite")
def _jsonb_as_text(element, compiler, **kw):
    return "TEXT"


@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):
    # SQLite solo autoincrementa PK declaradas como INTEGER (no BIGINT) --
    # sin esto, cualquier insert que dependa de un id autogenerado (como el
    # que hace ignorar_frontera_quoia internamente) falla con NOT NULL.
    return "INTEGER"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


ADMIN = types.SimpleNamespace(id=1, rol=types.SimpleNamespace(value="admin"))

# SQLite no autoincrementa BigInteger (solo Integer) -- ids explícitos, mismo
# criterio que el resto de tests de este módulo (ver test_reporte_energia_
# rellenar_horario_reconectador_ref.py).
_next_id = iter(range(1, 100000))


def _proyecto(db, **kw):
    kw.setdefault("id", next(_next_id))
    kw.setdefault("nombre_comercial", "Proyecto de prueba")
    p = Proyecto(**kw)
    db.add(p)
    db.flush()
    return p


class _GaiaFalso:
    """Un solo border de Quoia, controlado por el test."""
    def __init__(self, borders, fallo=False):
        self._borders = borders
        self.ultima_llamada_fallo = False
        self._fallo = fallo

    def get_all_borders(self):
        self.ultima_llamada_fallo = self._fallo
        return [] if self._fallo else self._borders


def _border(frt_code, categoria="frt_generation", nombre="Planta X", init_date=None):
    return [{
        "name": nombre,
        categoria: {"frt_code": frt_code, "id": 999, "init_date": init_date},
    }]


def test_crear_reactiva_una_frontera_borrada_en_vez_de_dejarla_atrapada(db, monkeypatch):
    proy = _proyecto(db)
    f = Frontera(
        id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Vieja", codigo_frontera="Frt00123",
        tipo_frontera="generacion", estado="activa",
        deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    db.add(f)
    db.commit()

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion", codigo_frontera="Frt00123"),
        forzar=False, db=db, _=ADMIN,
    )

    assert out.id == f.id  # misma fila, no una nueva
    db.refresh(f)
    assert f.deleted_at is None
    assert f.nombre_frontera == "Nueva"


def test_crear_es_case_insensitive_actualiza_la_activa_sin_duplicar(db):
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Original", codigo_frontera="frt00123",
                 tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Actualizada", tipo_frontera="generacion", codigo_frontera="FRT00123"),
        forzar=False, db=db, _=ADMIN,
    )

    assert out.id == f.id
    assert db.query(Frontera).count() == 1


def test_pendientes_de_quoia_no_cuenta_una_frontera_borrada_como_existente(db, monkeypatch):
    proy = _proyecto(db)
    db.add(Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Vieja", codigo_frontera="Frt00123",
                     tipo_frontera="generacion",
                     deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)))
    db.commit()

    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso(_border("frt00123")))

    pendientes = api.fronteras_quoia_pendientes(db=db, _=ADMIN)

    assert [p.frt_code for p in pendientes] == ["frt00123"]


def test_confirmar_resucita_la_borrada_en_vez_de_rechazar(db, monkeypatch):
    proy_vieja = _proyecto(db, nombre_comercial="Proyecto viejo")
    proy_nuevo = _proyecto(db, nombre_comercial="Proyecto nuevo")
    f = Frontera(id=next(_next_id), proyecto_id=proy_vieja.id, nombre_frontera="Vieja", codigo_frontera="frt00123",
                 tipo_frontera="generacion",
                 deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    db.add(f)
    db.commit()
    f_id = f.id

    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso(_border("frt00123", nombre="Planta Y")))
    monkeypatch.setattr(api, "get_frt_meter_info", lambda gaia, code: (None, None))

    out = api.confirmar_frontera_quoia(
        "frt00123", FronteraQuoiaConfirmar(proyecto_id=proy_nuevo.id), db=db, _=ADMIN,
    )

    assert out.id == f_id  # misma fila resucitada
    db.refresh(f)
    assert f.deleted_at is None
    assert f.proyecto_id == proy_nuevo.id
    assert db.query(Frontera).count() == 1


def test_confirmar_rechaza_si_ya_existe_una_activa_con_ese_codigo(db, monkeypatch):
    proy = _proyecto(db)
    db.add(Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Activa", codigo_frontera="frt00123",
                     tipo_frontera="generacion", estado="activa"))
    db.commit()
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso(_border("frt00123")))

    with pytest.raises(HTTPException) as exc:
        api.confirmar_frontera_quoia("frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id), db=db, _=ADMIN)
    assert exc.value.status_code == 409


def test_confirmar_limpia_un_ignorar_anterior_del_mismo_codigo(db, monkeypatch):
    proy = _proyecto(db)
    db.add(FronteraQuoiaIgnorada(id=next(_next_id), frt_code="frt00123", ignorado_por_usuario_id=ADMIN.id))
    db.commit()
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso(_border("frt00123")))
    monkeypatch.setattr(api, "get_frt_meter_info", lambda gaia, code: (None, None))

    api.confirmar_frontera_quoia("frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id), db=db, _=ADMIN)

    assert db.query(FronteraQuoiaIgnorada).filter(FronteraQuoiaIgnorada.frt_code == "frt00123").first() is None


def test_ignorar_rechaza_si_ya_existe_una_frontera_activa_con_ese_codigo(db):
    proy = _proyecto(db)
    db.add(Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Activa", codigo_frontera="frt00123",
                     tipo_frontera="generacion", estado="activa"))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.ignorar_frontera_quoia("frt00123", FronteraQuoiaIgnorar(motivo="prueba"), db=db, usuario=ADMIN)
    assert exc.value.status_code == 409
    assert db.query(FronteraQuoiaIgnorada).count() == 0


def test_ignorar_funciona_igual_si_el_codigo_esta_libre(db):
    api.ignorar_frontera_quoia("frt00123", FronteraQuoiaIgnorar(motivo="medidor de prueba"), db=db, usuario=ADMIN)

    ignorada = db.query(FronteraQuoiaIgnorada).filter(FronteraQuoiaIgnorada.frt_code == "frt00123").first()
    assert ignorada is not None
    assert ignorada.motivo == "medidor de prueba"


# ── PATCH /fronteras/{id}: mismos chequeos que crear (2026-08-24) ──────────────

def test_editar_rechaza_codigo_que_choca_con_otra_frontera_activa(db):
    proy = _proyecto(db)
    a = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="A", codigo_frontera="frt00001",
                 tipo_frontera="generacion", estado="activa")
    b = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="B", codigo_frontera="frt00002",
                 tipo_frontera="generacion", estado="activa")
    db.add_all([a, b])
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.update_frontera(b.id, FronteraUpdate(codigo_frontera="FRT00001"), forzar=False, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    db.refresh(b)
    assert b.codigo_frontera == "frt00002"  # no se guardó el cambio


def test_editar_permite_guardar_el_mismo_codigo_propio_sin_cambios(db):
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="A", codigo_frontera="frt00001",
                 tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    out = api.update_frontera(f.id, FronteraUpdate(codigo_frontera="FRT00001", municipio="Corozal"),
                               forzar=False, db=db, _=ADMIN)
    assert out.municipio == "Corozal"


def test_editar_rechaza_nombre_muy_parecido_a_otra_frontera(db):
    proy = _proyecto(db)
    a = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="AGGE Extractora Monterrey",
                 codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    b = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="La Catedral",
                 codigo_frontera="frt00002", tipo_frontera="generacion", estado="activa")
    db.add_all([a, b])
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.update_frontera(b.id, FronteraUpdate(nombre_frontera="AGGE Frontera Monterrey"),
                             forzar=False, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    db.refresh(b)
    assert b.nombre_frontera == "La Catedral"


def test_editar_no_se_compara_consigo_misma(db):
    """Cambiar un campo sin tocar el nombre no debe disparar el chequeo de
    'parecido a sí misma'."""
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="La Catedral",
                 codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    out = api.update_frontera(f.id, FronteraUpdate(nombre_frontera="La Catedral", municipio="Corozal"),
                               forzar=False, db=db, _=ADMIN)
    assert out.municipio == "Corozal"


def test_editar_con_forzar_ignora_el_nombre_parecido(db):
    proy = _proyecto(db)
    a = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="AGGE Extractora Monterrey",
                 codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa")
    b = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="La Catedral",
                 codigo_frontera="frt00002", tipo_frontera="generacion", estado="activa")
    db.add_all([a, b])
    db.commit()

    out = api.update_frontera(b.id, FronteraUpdate(nombre_frontera="AGGE Frontera Monterrey"),
                               forzar=True, db=db, _=ADMIN)
    assert out.nombre_frontera == "AGGE Frontera Monterrey"


def test_confirmar_rechaza_nombre_muy_parecido_a_otra_frontera(db, monkeypatch):
    proy = _proyecto(db)
    db.add(Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="AGGE Extractora Monterrey",
                     codigo_frontera="frt00001", tipo_frontera="generacion", estado="activa"))
    db.commit()
    monkeypatch.setattr(
        api, "_get_gaia",
        lambda: _GaiaFalso(_border("frt00002", nombre="AGGE Frontera Monterrey")),
    )

    with pytest.raises(HTTPException) as exc:
        api.confirmar_frontera_quoia(
            "frt00002", FronteraQuoiaConfirmar(proyecto_id=proy.id), forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 409
    assert db.query(Frontera).count() == 1


# ── Falla de Quoia no debe verse como "todo en orden" (2026-08-24) ─────────────

def test_pendientes_devuelve_503_si_quoia_esta_caido_en_vez_de_lista_vacia(db, monkeypatch):
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso([], fallo=True))

    with pytest.raises(HTTPException) as exc:
        api.fronteras_quoia_pendientes(db=db, _=ADMIN)
    assert exc.value.status_code == 503


def test_confirmar_devuelve_503_si_quoia_esta_caido_en_vez_de_404(db, monkeypatch):
    proy = _proyecto(db)
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso([], fallo=True))

    with pytest.raises(HTTPException) as exc:
        api.confirmar_frontera_quoia("frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id), db=db, _=ADMIN)
    assert exc.value.status_code == 503
