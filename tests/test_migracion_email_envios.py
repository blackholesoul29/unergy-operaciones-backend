"""Migracion 137 -- normalizar email_envios en tabla padre (evento) + tabla
hija (email_envio_destinatarios). `_migrar_destinatarios()` (la logica de
datos real, ver alembic/versions/137_normalizar_email_envios.py) esta escrita
en Python puro a proposito para poder probarla de verdad contra SQLite --
no hay Postgres local disponible para correr la migracion completa.

Reproduce el patron real visto en produccion 2026-09-01: un operador (CENS)
con 6 contactos genera 6 filas identicas en email_envios para el mismo
envio -- se verifica que colapsan en 1 solo evento sin perder ningun
destinatario."""
import importlib.util
import os

import pytest
from sqlalchemy import create_engine, text

_RUTA_MIGRACION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions", "137_normalizar_email_envios.py",
)


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location("migracion_137", _RUTA_MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


migracion = _cargar_migracion()


@pytest.fixture
def db():
    # Connection cruda, no Session ORM -- op.get_bind() en la migracion real
    # devuelve una Connection, y sqlalchemy.inspect() no soporta Session.
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    conn.execute(text("""
        CREATE TABLE email_envios (
            id INTEGER PRIMARY KEY,
            destinatario VARCHAR(500),
            cc TEXT,
            asunto VARCHAR(500) NOT NULL,
            tipo VARCHAR(50) NOT NULL,
            exitoso BOOLEAN NOT NULL DEFAULT 1,
            error TEXT,
            enviado_at TEXT NOT NULL,
            proyectos TEXT,
            proyectos_total INTEGER
        )
    """))
    conn.execute(text("""
        CREATE TABLE email_envio_destinatarios (
            id INTEGER PRIMARY KEY,
            envio_id INTEGER NOT NULL,
            email VARCHAR(500) NOT NULL,
            tipo_destinatario VARCHAR(10) NOT NULL DEFAULT 'to',
            exitoso BOOLEAN NOT NULL,
            error TEXT
        )
    """))
    conn.commit()
    yield conn
    conn.close()


def _insertar(db, id_, destinatario, cc, asunto, tipo, enviado_at, exitoso=True, error=None):
    db.execute(text("""
        INSERT INTO email_envios (id, destinatario, cc, asunto, tipo, exitoso, error, enviado_at)
        VALUES (:id, :dest, :cc, :asunto, :tipo, :ok, :err, :ts)
    """), {"id": id_, "dest": destinatario, "cc": cc, "asunto": asunto, "tipo": tipo,
            "ok": exitoso, "err": error, "ts": enviado_at})


def test_colapsa_6_filas_duplicadas_en_1_evento_sin_perder_destinatarios(db):
    """Patron real de CENS visto en produccion: 6 contactos, mismo asunto,
    timestamps a milisegundos de diferencia."""
    contactos = [
        "landis.camargo@cens.com.co", "darwin.orduz@cens.com.co", "grupo.telemedida@cens.com.co",
        "ruben.tarazona@cens.com.co", "anderson.pena@cens.com.co", "edgar.mojica@cens.com.co",
    ]
    for i, email in enumerate(contactos):
        _insertar(db, i + 1, email, "danielg@unergy.io", "Reporte CGM — 2026-08-26 — CENS",
                  "reporte_cgm", f"2026-08-27T11:20:04.{750000 + i * 40000}")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    eventos = db.execute(text("SELECT id FROM email_envios")).fetchall()
    assert len(eventos) == 1
    envio_id = eventos[0][0]

    hijos = db.execute(text(
        "SELECT email, tipo_destinatario FROM email_envio_destinatarios WHERE envio_id = :id"
    ), {"id": envio_id}).fetchall()
    assert {h[0] for h in hijos if h[1] == "to"} == set(contactos)
    assert {h[0] for h in hijos if h[1] == "cc"} == {"danielg@unergy.io"}


def test_no_colapsa_eventos_de_operadores_distintos_en_el_mismo_minuto(db):
    """Afinia y CENS mandados en el mismo click (mismo minuto) NO deben
    fusionarse -- son destinatarios distintos, agrupa por asunto tambien."""
    _insertar(db, 1, "a@afinia.com", None, "Reporte CGM — 2026-08-31 — Afinia", "reporte_cgm", "2026-08-31T08:22:00")
    _insertar(db, 2, "b@afinia.com", None, "Reporte CGM — 2026-08-31 — Afinia", "reporte_cgm", "2026-08-31T08:22:01")
    _insertar(db, 3, "c@cens.com", None, "Reporte CGM — 2026-08-31 — CENS", "reporte_cgm", "2026-08-31T08:22:02")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    eventos = db.execute(text("SELECT id, asunto FROM email_envios ORDER BY id")).fetchall()
    assert len(eventos) == 2  # Afinia colapsa a 1, CENS queda en 1 propio

    afinia_id = next(e[0] for e in eventos if "Afinia" in e[1])
    hijos_afinia = db.execute(text(
        "SELECT email FROM email_envio_destinatarios WHERE envio_id = :id"
    ), {"id": afinia_id}).fetchall()
    assert {h[0] for h in hijos_afinia} == {"a@afinia.com", "b@afinia.com"}


def test_no_colapsa_mismo_destinatario_en_minutos_distintos(db):
    """Dos corridas reales distintas del mismo dia (ej. un reenvio manual mas
    tarde) no deben fusionarse -- son dos eventos de verdad."""
    _insertar(db, 1, "a@afinia.com", None, "Reporte CGM — 2026-08-31 — Afinia", "reporte_cgm", "2026-08-31T08:22:00")
    _insertar(db, 2, "a@afinia.com", None, "Reporte CGM — 2026-08-31 — Afinia", "reporte_cgm", "2026-08-31T09:45:00")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    eventos = db.execute(text("SELECT count(*) FROM email_envios")).scalar()
    assert eventos == 2


def test_conserva_exitoso_y_error_por_fila_original(db):
    _insertar(db, 1, "a@test.com", None, "Asunto", "falla", "2026-08-31T08:22:00", exitoso=True)
    _insertar(db, 2, "b@test.com", None, "Asunto", "falla", "2026-08-31T08:22:00", exitoso=False, error="buzón lleno")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    hijos = {h[0]: (h[1], h[2]) for h in db.execute(text(
        "SELECT email, exitoso, error FROM email_envio_destinatarios"
    )).fetchall()}
    assert hijos["a@test.com"][0] == 1  # SQLite booleano -> 1/0
    assert hijos["b@test.com"][0] == 0
    assert hijos["b@test.com"][1] == "buzón lleno"


def test_destinatario_y_cc_se_eliminan_de_email_envios(db):
    _insertar(db, 1, "a@test.com", "cc@test.com", "Asunto", "informe", "2026-08-31T08:22:00")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    columnas = {c[1] for c in db.execute(text("PRAGMA table_info(email_envios)")).fetchall()}
    assert "destinatario" not in columnas
    assert "cc" not in columnas


def test_es_idempotente_si_ya_se_corrio_antes(db):
    """Un segundo deploy que reintente la migracion (destinatario/cc ya no
    existen) no debe fallar ni duplicar nada."""
    _insertar(db, 1, "a@test.com", None, "Asunto", "informe", "2026-08-31T08:22:00")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()
    n_hijos_antes = db.execute(text("SELECT count(*) FROM email_envio_destinatarios")).scalar()

    migracion._migrar_destinatarios(db)  # no debe lanzar ni cambiar nada
    db.commit()
    n_hijos_despues = db.execute(text("SELECT count(*) FROM email_envio_destinatarios")).scalar()

    assert n_hijos_antes == n_hijos_despues == 1


def test_ningun_cc_vacio_o_solo_espacios_genera_fila_hija(db):
    _insertar(db, 1, "a@test.com", " , ,b@test.com, ", "Asunto", "informe", "2026-08-31T08:22:00")
    db.commit()

    migracion._migrar_destinatarios(db)
    db.commit()

    correos = {h[0] for h in db.execute(text("SELECT email FROM email_envio_destinatarios")).fetchall()}
    assert correos == {"a@test.com", "b@test.com"}
