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
from sqlalchemy.exc import IntegrityError


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


def test_resucitar_una_borrada_tambien_rechaza_nombre_parecido(db):
    """Antes esta rama (codigo_frontera coincide con una fila -- viva o
    borrada -- que ya existe) se saltaba por completo el chequeo de nombre
    parecido que sí tenían crear y confirmar-desde-Quoia: se podía
    'resucitar' un código con un nombre que colisiona con otra frontera
    activa, sin aviso ni forzar."""
    proy = _proyecto(db)
    db.add(Frontera(
        id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Planta Catedral",
        codigo_frontera="Frt00050", tipo_frontera="generacion", estado="activa",
    ))
    db.add(Frontera(
        id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Vieja",
        codigo_frontera="Frt00123", tipo_frontera="generacion",
        deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    ))
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.create_frontera(
            FronteraCreate(nombre_frontera="Planta Catedral", tipo_frontera="generacion",
                            codigo_frontera="Frt00123"),
            forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True

    # La fila borrada sigue borrada -- el rechazo fue antes de tocarla.
    borrada = db.query(Frontera).filter(Frontera.codigo_frontera == "Frt00123").first()
    assert borrada.deleted_at is not None


def test_resucitar_con_forzar_ignora_el_nombre_parecido(db):
    proy = _proyecto(db)
    db.add(Frontera(
        id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Planta Catedral",
        codigo_frontera="Frt00050", tipo_frontera="generacion", estado="activa",
    ))
    f_id = next(_next_id)
    db.add(Frontera(
        id=f_id, proyecto_id=proy.id, nombre_frontera="Vieja",
        codigo_frontera="Frt00123", tipo_frontera="generacion",
        deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    ))
    db.commit()

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Planta Catedral", tipo_frontera="generacion",
                        codigo_frontera="Frt00123"),
        forzar=True, db=db, _=ADMIN,
    )
    assert out.id == f_id
    assert db.query(Frontera).filter(Frontera.id == f_id).first().deleted_at is None


def test_resucitar_convierte_choque_de_integridad_en_409(db, monkeypatch):
    """La rama de resucitar no tenia try/except alrededor de su propio
    commit (a diferencia de crear nueva y de confirmar-desde-Quoia) -- un
    choque real de una constraint distinta a codigo_frontera reventaba como
    500 en vez de un 409 limpio."""
    proy = _proyecto(db)
    db.add(Frontera(
        id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Vieja",
        codigo_frontera="Frt00123", tipo_frontera="generacion",
        deleted_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    ))
    db.commit()

    def _commit_falla():
        raise IntegrityError("insert", {}, Exception("choque"))
    monkeypatch.setattr(db, "commit", _commit_falla)

    with pytest.raises(HTTPException) as exc:
        api.create_frontera(
            FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion",
                            codigo_frontera="Frt00123"),
            forzar=True, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 409


def test_crear_frontera_con_proyecto_inexistente_da_404_no_409_enganoso(db):
    """proyecto_id/operador_red_id nunca se validaban antes del commit -- un
    id invalido reventaba como IntegrityError, y el except generico de
    create/update lo reportaba como '''ya existe ese codigo''' (409), un
    mensaje que no tiene nada que ver con la causa real."""
    with pytest.raises(HTTPException) as exc:
        api.create_frontera(
            FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion", proyecto_id=999999),
            forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 404
    assert "Proyecto" in exc.value.detail


def test_crear_frontera_con_operador_red_inexistente_da_404(db):
    with pytest.raises(HTTPException) as exc:
        api.create_frontera(
            FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion", operador_red_id=999999),
            forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 404
    assert "Operador" in exc.value.detail


def test_editar_frontera_con_proyecto_inexistente_da_404(db):
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Original",
                 codigo_frontera="frt00300", tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.update_frontera(
            f.id, FronteraUpdate(proyecto_id=999999), forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 404
    assert "Proyecto" in exc.value.detail


def test_editar_frontera_con_operador_red_inexistente_da_404(db):
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Original",
                 codigo_frontera="frt00301", tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.update_frontera(
            f.id, FronteraUpdate(operador_red_id=999999), forzar=False, db=db, _=ADMIN,
        )
    assert exc.value.status_code == 404
    assert "Operador" in exc.value.detail


def test_delete_frontera_marca_deleted_at_y_desaparece_de_list_y_pendientes(db, monkeypatch):
    """delete_frontera() (soft-delete) no tenia ningun test -- nada verificaba
    que deleted_at se seteara ni que la fila desapareciera de GET /fronteras
    ni de /quoia/pendientes despues de borrarla."""
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="A borrar",
                 codigo_frontera="frt00123", tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()
    f_id = f.id

    assert any(x.id == f_id for x in api.list_fronteras(
        proyecto_id=None, tipo_frontera=None, estado=None, skip=0, limit=100, db=db, _=ADMIN,
    ))

    api.delete_frontera(f_id, db=db, _=ADMIN)

    db.refresh(f)
    assert f.deleted_at is not None
    assert not any(x.id == f_id for x in api.list_fronteras(
        proyecto_id=None, tipo_frontera=None, estado=None, skip=0, limit=100, db=db, _=ADMIN,
    ))

    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso(_border("frt00123")))
    pendientes = api.fronteras_quoia_pendientes(db=db, _=ADMIN)
    assert [p.frt_code for p in pendientes] == ["frt00123"]  # vuelve a aparecer como pendiente


def test_delete_frontera_inexistente_da_404(db):
    with pytest.raises(HTTPException) as exc:
        api.delete_frontera(999999, db=db, _=ADMIN)
    assert exc.value.status_code == 404


def test_confirmar_limpia_una_ignorada_colada_durante_la_llamada_a_quoia(db, monkeypatch):
    """confirmar_frontera_quoia() borra la fila 'ignorada' ANTES de llamar a
    Quoia (para no dejarla en medio de un round-trip lento) y otra vez justo
    antes del commit final -- simula que un 'ignorar' concurrente se cuela en
    esa ventana y confirma que el segundo borrado la limpia igual."""
    proy = _proyecto(db)
    gaia = _GaiaFalso(_border("frt00123"))

    def _borders_con_ignorar_concurrente():
        db.add(FronteraQuoiaIgnorada(frt_code="frt00123", motivo="concurrente"))
        db.commit()
        return gaia._borders

    monkeypatch.setattr(gaia, "get_all_borders", _borders_con_ignorar_concurrente)
    monkeypatch.setattr(api, "_get_gaia", lambda: gaia)
    monkeypatch.setattr(api, "get_frt_meter_info", lambda g, code: (None, None))

    api.confirmar_frontera_quoia(
        "frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id), forzar=False, db=db, _=ADMIN,
    )

    assert db.query(FronteraQuoiaIgnorada).filter(FronteraQuoiaIgnorada.frt_code == "frt00123").first() is None
    assert db.query(Frontera).filter(Frontera.codigo_frontera == "frt00123").first() is not None


def test_ignorar_dos_veces_seguidas_no_revienta_con_500(db, monkeypatch):
    """frt_code es unico en FronteraQuoiaIgnorada -- un choque de esa
    constraint (ej. doble clic rapido, dos requests casi simultaneas que
    ambas pasan el chequeo previo) debe absorberse en vez de propagar un
    IntegrityError sin capturar."""
    def _commit_falla():
        raise IntegrityError("insert", {}, Exception("uq_frt_code"))
    monkeypatch.setattr(db, "commit", _commit_falla)

    # No debe lanzar -- el resultado esperado es que quede "ignorado" sin
    # excepcion, igual que si ya existiera (el chequeo previo simplemente no
    # alcanzo a verla por la carrera).
    api.ignorar_frontera_quoia("frt00123", FronteraQuoiaIgnorar(motivo="prueba"), db=db, usuario=ADMIN)


def test_editar_agregando_codigo_frontera_completa_medidor_desde_quoia(db, monkeypatch):
    """Antes solo create_frontera()/confirmar_frontera_quoia() rellenaban el
    medidor desde Quoia -- una frontera creada sin codigo y completada
    despues via PATCH se quedaba sin este dato para siempre."""
    proy = _proyecto(db)
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Sin codigo aun",
                 tipo_frontera="generacion", estado="activa")
    db.add(f)
    db.commit()

    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso([]))
    monkeypatch.setattr(
        api, "get_frt_meter_info",
        lambda gaia, code: ({"marca": "ISKRA", "modelo": "MT880", "serie": "555"}, None),
    )

    out = api.update_frontera(f.id, FronteraUpdate(codigo_frontera="Frt00500"), forzar=False, db=db, _=ADMIN)

    assert out.marca_med_ppal == "ISKRA"
    assert out.nro_serie_med_ppal == "555"


def test_editar_solo_tipo_frontera_tambien_revalida_nombre_parecido(db):
    """Antes el chequeo de nombre parecido solo corria si 'nombre_frontera'
    estaba en los cambios -- cambiar SOLO tipo_frontera se saltaba la
    validacion, aunque el nuevo tipo pueda chocar con otra frontera que antes
    no competia (_buscar_duplicado_frontera compara dentro del mismo tipo)."""
    proy = _proyecto(db)
    db.add(Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Planta Uruaco",
                     tipo_frontera="generacion", estado="activa"))
    f = Frontera(id=next(_next_id), proyecto_id=proy.id, nombre_frontera="Planta Uruaco",
                 tipo_frontera="consumo", estado="activa")
    db.add(f)
    db.commit()

    with pytest.raises(HTTPException) as exc:
        api.update_frontera(f.id, FronteraUpdate(tipo_frontera="generacion"), forzar=False, db=db, _=ADMIN)
    assert exc.value.status_code == 409
    assert exc.value.detail["duplicado_nombre"] is True


def test_crear_frontera_completa_medidor_desde_quoia_si_esta_disponible(db, monkeypatch):
    """create_frontera() (POST manual, ej. el boton 'Nueva Frontera') antes
    nunca consultaba Quoia -- solo confirmar_frontera_quoia() lo hacia. Una
    frontera creada a mano se quedaba sin marca/modelo/serie de medidor para
    siempre (dependia del backfill manual, ya retirado). Ahora hace el mismo
    relleno best-effort al crear."""
    proy = _proyecto(db)
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso([]))
    monkeypatch.setattr(
        api, "get_frt_meter_info",
        lambda gaia, code: (
            {"marca": "ISKRA", "modelo": "MT880", "serie": "12345"},
            {"marca": "ISKRA", "modelo": "MT880", "serie": "67890"},
        ),
    )

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion",
                        codigo_frontera="Frt00200", proyecto_id=proy.id),
        forzar=False, db=db, _=ADMIN,
    )

    assert out.marca_med_ppal == "ISKRA"
    assert out.modelo_med_ppal == "MT880"
    assert out.nro_serie_med_ppal == "12345"
    assert out.marca_med_resp == "ISKRA"
    assert out.nro_serie_med_resp == "67890"


def test_crear_frontera_no_pisa_medidor_si_ya_viene_en_el_body(db, monkeypatch):
    proy = _proyecto(db)
    monkeypatch.setattr(api, "_get_gaia", lambda: _GaiaFalso([]))
    monkeypatch.setattr(
        api, "get_frt_meter_info",
        lambda gaia, code: ({"marca": "DE QUOIA", "modelo": "X", "serie": "999"}, None),
    )

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Nueva", tipo_frontera="generacion",
                        codigo_frontera="Frt00201", proyecto_id=proy.id,
                        marca_med_ppal="MANUAL"),
        forzar=False, db=db, _=ADMIN,
    )

    assert out.marca_med_ppal == "MANUAL"


def test_crear_frontera_sin_codigo_no_consulta_quoia(db, monkeypatch):
    llamadas = []
    monkeypatch.setattr(api, "_get_gaia", lambda: llamadas.append(1) or _GaiaFalso([]))

    out = api.create_frontera(
        FronteraCreate(nombre_frontera="Sin codigo", tipo_frontera="generacion"),
        forzar=False, db=db, _=ADMIN,
    )

    assert out.codigo_frontera is None
    assert llamadas == []


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


def test_editar_permite_guardar_el_mismo_codigo_frontera_sin_cambios(db):
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


# ── Default de tipo_frontera al confirmar un border de consumo (2026-08-25) ────

def test_confirmar_border_de_consumo_sin_tipo_explicito_cae_en_consumo_generico(db, monkeypatch):
    """Antes caía en 'consumo_auxiliar' -- un subtipo que nadie pidió."""
    proy = _proyecto(db)
    monkeypatch.setattr(
        api, "_get_gaia",
        lambda: _GaiaFalso(_border("frt00123", categoria="frt_consumption", nombre="Planta X")),
    )
    monkeypatch.setattr(api, "get_frt_meter_info", lambda gaia, code: (None, None))

    out = api.confirmar_frontera_quoia(
        "frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id), db=db, _=ADMIN,
    )

    assert out.tipo_frontera == "consumo"


def test_confirmar_respeta_el_tipo_explicito_del_body(db, monkeypatch):
    proy = _proyecto(db)
    monkeypatch.setattr(
        api, "_get_gaia",
        lambda: _GaiaFalso(_border("frt00123", categoria="frt_consumption", nombre="Planta X")),
    )
    monkeypatch.setattr(api, "get_frt_meter_info", lambda gaia, code: (None, None))

    out = api.confirmar_frontera_quoia(
        "frt00123", FronteraQuoiaConfirmar(proyecto_id=proy.id, tipo_frontera="consumo_auxiliar"),
        db=db, _=ADMIN,
    )

    assert out.tipo_frontera == "consumo_auxiliar"
