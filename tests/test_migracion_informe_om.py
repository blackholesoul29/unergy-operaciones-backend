"""Migracion 133 -- fusionar proyecto_inicio_operacion en proyecto_informe_om.
`_migrar_checklist()` es la logica de datos real (ver alembic/versions/
133_unificar_informe_om.py), en Python puro + SQL portable a proposito para
poder probarla contra SQLite -- no hay Postgres local disponible.

Bug real 2026-09-01: el guard original `if any(checklist.values())` bloqueo
3 deploys seguidos en produccion porque un sub-diccionario placeholder no
vacio (ej. {"estado": None, "nota": ""}, la forma que trae CADA item del
checklist viejo, con o sin datos reales) ya lo disparaba. Revisando a mano
los 2 unicos proyectos de la tabla, resulto que SI habia contenido real:
`estacion_meteo.temperatura_ambiente.estado='pendiente'` en uno (categoria
que SI se conserva) y `cctv='rechazado'` en el otro (categoria descartada
por decision explicita). Estos tests reproducen exactamente esa forma."""
import importlib.util
import json
import os

import pytest
from sqlalchemy import create_engine, text

_RUTA_MIGRACION = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alembic", "versions", "133_unificar_informe_om.py",
)


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location("migracion_133", _RUTA_MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


migracion = _cargar_migracion()

# Forma real de un item vacio del checklist viejo -- SIEMPRE presente,
# con o sin datos cargados. Es justo lo que rompia el guard original.
_ITEM_VACIO = {"nota": "", "estado": None}
_ITEM_VACIO_CON_EVIDENCIA = {"nota": "", "estado": None, "evidencia": []}


def _checklist_base() -> dict:
    """El esqueleto que trae CUALQUIER fila del checklist viejo, sin ningun
    dato real cargado -- ver InicioOperacionView.vue (borrado 2026-08-21)."""
    return {
        "cctv": None, "cable_solar": None, "cableado_mt_bt": None,
        "transformadores": None, "tableros": None, "shelter_skid": None,
        "obras_civiles": None, "doc_om": None,
        "paneles": {"nota": "", "estado": None, "cantidad": None},
        "tracker": dict(_ITEM_VACIO),
        "frontera": {"principal": dict(_ITEM_VACIO_CON_EVIDENCIA), "respaldo": dict(_ITEM_VACIO_CON_EVIDENCIA)},
        "estacion_meteo": {
            "instalacion": dict(_ITEM_VACIO), "en_plataforma": dict(_ITEM_VACIO),
            "reporta_datos": dict(_ITEM_VACIO_CON_EVIDENCIA), "poa": dict(_ITEM_VACIO),
            "temperatura_ambiente": dict(_ITEM_VACIO), "velocidad_viento": dict(_ITEM_VACIO),
            "direccion_viento": dict(_ITEM_VACIO),
        },
        "monitoreo": {
            "starlink": dict(_ITEM_VACIO_CON_EVIDENCIA),
            "fusion_solar": {"nota": "", "evidencia": [], "datos_coherentes": dict(_ITEM_VACIO)},
        },
        "reconectador": {"tiene": None, "en_plataforma": dict(_ITEM_VACIO), "calidad_datos": dict(_ITEM_VACIO),
                          "evidencia": [], "nota": ""},
    }


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    conn.execute(text("""
        CREATE TABLE proyecto_inicio_operacion (
            id INTEGER PRIMARY KEY,
            proyecto_id INTEGER NOT NULL,
            empresa_contratista VARCHAR(255),
            fecha_energizacion TEXT,
            fecha_inicio_operacion TEXT,
            checklist TEXT NOT NULL DEFAULT '{}',
            pendientes TEXT NOT NULL DEFAULT '[]'
        )
    """))
    conn.execute(text("""
        CREATE TABLE proyecto_informe_om (
            id INTEGER PRIMARY KEY,
            proyecto_id INTEGER NOT NULL UNIQUE,
            empresa_contratista VARCHAR(255),
            fecha_energizacion TEXT,
            fecha_inicio_operacion TEXT,
            pendientes TEXT NOT NULL DEFAULT '[]',
            checklist_fusion_solar TEXT NOT NULL DEFAULT '{}',
            checklist_frontera TEXT NOT NULL DEFAULT '{}',
            checklist_estacion_meteo TEXT NOT NULL DEFAULT '{}',
            checklist_reconectador TEXT NOT NULL DEFAULT '{}'
        )
    """))
    conn.commit()
    yield conn
    conn.close()


def _insertar_io(db, id_, proyecto_id, checklist, empresa_contratista=None,
                  fecha_energizacion=None, fecha_inicio_operacion=None, pendientes=None):
    db.execute(text("""
        INSERT INTO proyecto_inicio_operacion
            (id, proyecto_id, empresa_contratista, fecha_energizacion, fecha_inicio_operacion, checklist, pendientes)
        VALUES (:id, :pid, :ec, :fe, :fio, :chk, :pend)
    """), {"id": id_, "pid": proyecto_id, "ec": empresa_contratista, "fe": fecha_energizacion,
            "fio": fecha_inicio_operacion, "chk": json.dumps(checklist), "pend": json.dumps(pendientes or [])})


def _fila_informe_om(db, proyecto_id):
    return db.execute(text(
        "SELECT * FROM proyecto_informe_om WHERE proyecto_id = :pid"
    ), {"pid": proyecto_id}).mappings().first()


# ── Regresion exacta del bug real ───────────────────────────────────────────

def test_checklist_completamente_vacio_no_bloquea_y_no_crea_fila(db):
    """El caso comun: ninguna categoria tiene contenido real -- no debe
    lanzar, y como tampoco hay fechas/empresa/pendientes, no crea fila."""
    _insertar_io(db, 1, 999, _checklist_base())
    db.commit()

    migracion._migrar_checklist(db)  # no debe lanzar
    db.commit()

    assert _fila_informe_om(db, 999) is None
    insp = __import__("sqlalchemy").inspect(db)
    assert "proyecto_inicio_operacion" not in insp.get_table_names()


def test_proyecto_230_temperatura_ambiente_pendiente_se_mapea_sin_bloquear(db):
    """Caso real que disparaba el guard viejo: estacion_meteo (categoria que
    SI se conserva) con un solo leaf real -- 'pendiente' -- entre puro relleno
    vacio. Antes se perdia sin avisar (ni bloqueaba ni se mapeaba); ahora se
    mapea a la columna nueva."""
    checklist = _checklist_base()
    checklist["estacion_meteo"]["temperatura_ambiente"] = {"nota": "", "estado": "pendiente"}
    _insertar_io(db, 1, 230, checklist)
    db.commit()

    migracion._migrar_checklist(db)
    db.commit()

    fila = _fila_informe_om(db, 230)
    assert fila is not None
    meteo = json.loads(fila["checklist_estacion_meteo"])
    assert meteo["temperatura_ambiente"]["estado"] == "pendiente"
    # el resto de estacion_meteo se mapeo tambien, todo vacio
    assert meteo["poa"]["estado"] is None


def test_proyecto_52_cctv_rechazado_no_bloquea_solo_avisa(db, capsys):
    """cctv es una categoria explicitamente descartada -- no debe lanzar, se
    descarta a proposito. Solo imprime un aviso informativo."""
    checklist = _checklist_base()
    checklist["cctv"] = "rechazado"
    _insertar_io(db, 1, 52, checklist, fecha_inicio_operacion="2024-08-13")
    db.commit()

    migracion._migrar_checklist(db)  # no debe lanzar
    db.commit()

    salida = capsys.readouterr().out
    assert "proyecto_id=52" in salida
    assert "cctv" in salida

    fila = _fila_informe_om(db, 52)
    assert fila is not None
    assert fila["fecha_inicio_operacion"] == "2024-08-13"
    # cctv no aparece en ninguna de las 4 columnas nuevas -- se descarto de verdad
    assert json.dumps(json.loads(fila["checklist_fusion_solar"])).find("rechazado") == -1


def test_contenido_real_en_frontera_se_mapea_completo(db):
    checklist = _checklist_base()
    checklist["frontera"]["principal"] = {"nota": "falta evidencia", "estado": "pendiente", "evidencia": []}
    checklist["frontera"]["respaldo"] = {"nota": "", "estado": "aprobado", "evidencia": [{"id": "1", "url": "x"}]}
    _insertar_io(db, 1, 77, checklist)
    db.commit()

    migracion._migrar_checklist(db)
    db.commit()

    fila = _fila_informe_om(db, 77)
    frontera = json.loads(fila["checklist_frontera"])
    assert frontera["principal"]["estado"] == "pendiente"
    assert frontera["principal"]["nota"] == "falta evidencia"
    assert frontera["respaldo"]["estado"] == "aprobado"
    assert frontera["respaldo"]["evidencia"] == [{"id": "1", "url": "x"}]


def test_fusion_solar_se_mapea_desde_monitoreo(db):
    checklist = _checklist_base()
    checklist["monitoreo"]["starlink"] = {"nota": "", "estado": "aprobado", "evidencia": [{"id": "s1", "url": "x"}]}
    checklist["monitoreo"]["fusion_solar"]["datos_coherentes"] = {"nota": "", "estado": "aprobado"}
    _insertar_io(db, 1, 88, checklist)
    db.commit()

    migracion._migrar_checklist(db)
    db.commit()

    fila = _fila_informe_om(db, 88)
    fs = json.loads(fila["checklist_fusion_solar"])
    assert fs["starlink"]["estado"] == "aprobado"
    assert fs["datos_coherentes"]["estado"] == "aprobado"


def test_reconectador_se_mapea_incluido_tiene(db):
    checklist = _checklist_base()
    checklist["reconectador"] = {"tiene": True, "en_plataforma": {"nota": "", "estado": "aprobado"},
                                  "calidad_datos": {"nota": "", "estado": "pendiente"}, "evidencia": [], "nota": ""}
    _insertar_io(db, 1, 99, checklist)
    db.commit()

    migracion._migrar_checklist(db)
    db.commit()

    fila = _fila_informe_om(db, 99)
    r = json.loads(fila["checklist_reconectador"])
    assert r["tiene"] is True
    assert r["en_plataforma"]["estado"] == "aprobado"
    assert r["calidad_datos"]["estado"] == "pendiente"


def test_no_sobreescribe_fila_ya_existente_en_informe_om(db):
    """Si ya hay una ficha de Informe OM guardada (aunque hoy sean 0 en
    produccion), el backfill no debe pisarla."""
    db.execute(text(
        "INSERT INTO proyecto_informe_om (proyecto_id, empresa_contratista) VALUES (55, 'Ya cargado')"
    ))
    _insertar_io(db, 1, 55, _checklist_base(), empresa_contratista="Del checklist viejo")
    db.commit()

    migracion._migrar_checklist(db)
    db.commit()

    fila = _fila_informe_om(db, 55)
    assert fila["empresa_contratista"] == "Ya cargado"


def test_dos_proyectos_reales_juntos_no_lanza(db, capsys):
    """Reproduce exactamente el estado de produccion antes de esta migracion:
    2 filas, cada una con su propio leaf real."""
    c230 = _checklist_base()
    c230["estacion_meteo"]["temperatura_ambiente"] = {"nota": "", "estado": "pendiente"}
    _insertar_io(db, 1, 230, c230)

    c52 = _checklist_base()
    c52["cctv"] = "rechazado"
    _insertar_io(db, 2, 52, c52, fecha_inicio_operacion="2024-08-13")
    db.commit()

    migracion._migrar_checklist(db)  # no debe lanzar -- esto es lo que bloqueaba el deploy
    db.commit()

    assert _fila_informe_om(db, 230) is not None
    assert _fila_informe_om(db, 52) is not None
    insp = __import__("sqlalchemy").inspect(db)
    assert "proyecto_inicio_operacion" not in insp.get_table_names()


def test_tabla_vieja_se_elimina(db):
    _insertar_io(db, 1, 1, _checklist_base())
    db.commit()
    migracion._migrar_checklist(db)
    db.commit()

    insp = __import__("sqlalchemy").inspect(db)
    assert "proyecto_inicio_operacion" not in insp.get_table_names()


def test_es_idempotente_si_ya_se_corrio_antes(db):
    """Segundo intento de deploy (tabla vieja ya no existe) no debe lanzar."""
    migracion._migrar_checklist(db)  # tabla nunca existio en este fixture -- no-op
    db.commit()
    assert db.execute(text("SELECT count(*) FROM proyecto_informe_om")).scalar() == 0
