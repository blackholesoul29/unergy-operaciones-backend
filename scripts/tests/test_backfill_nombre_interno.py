"""Tests standalone: `python scripts/tests/test_backfill_nombre_interno.py`.

Prueba el endpoint /asic/backfill-nombre-interno contra SQLite en memoria (solo las
tablas asic_solicitudes y ppa_contratos). Verifica: relleno desde PPA por FK y por
código, registros sin resolver se reportan sin tocar, idempotencia, y vínculo de
contrato_ppa_id cuando faltaba.
"""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import AsicSolicitud, PPAContrato
from app.models.base import Base
from app.api.v1.asic import backfill_nombre_interno


def _setup():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e, tables=[AsicSolicitud.__table__, PPAContrato.__table__])
    db = Session(e)
    # PPAs canónicos
    db.add(PPAContrato(id=1, numero_codigo_contrato="UNERGY 001-2024", nombre_interno="Terpel 1"))
    db.add(PPAContrato(id=2, numero_codigo_contrato="UNERGY 002-2024", nombre_interno="Bavaria Norte"))
    db.add(PPAContrato(id=3, numero_codigo_contrato="UNERGY 003-2024", nombre_interno=None))  # PPA sin nombre
    # GESCON sin nombre_interno
    db.add(AsicSolicitud(id=10, tipo_solicitud="registro", estado_solicitud="publicado",
                         contrato_ppa_id=1, nombre_interno=None))                       # por FK
    db.add(AsicSolicitud(id=11, tipo_solicitud="registro", estado_solicitud="publicado",
                         contrato_interno="UNERGY 002-2024", nombre_interno=""))         # por código
    db.add(AsicSolicitud(id=12, tipo_solicitud="registro", estado_solicitud="publicado",
                         contrato_interno="UNERGY 003-2024", nombre_interno=None))       # PPA sin nombre -> no resuelve
    db.add(AsicSolicitud(id=13, tipo_solicitud="registro", estado_solicitud="publicado",
                         contrato_interno="NO-EXISTE-999", nombre_interno=None))         # sin match -> no resuelve
    db.add(AsicSolicitud(id=14, tipo_solicitud="registro", estado_solicitud="publicado",
                         contrato_interno="UNERGY 001-2024", nombre_interno="Ya tiene")) # no entra (ya tiene nombre)
    db.commit()
    return db


def test_dry_run_reporta_sin_modificar():
    db = _setup()
    rep = backfill_nombre_interno(dry_run=True, db=db, _=None)
    assert rep["total_sin_nombre"] == 4, rep["total_sin_nombre"]   # 10,11,12,13
    assert rep["a_actualizar"] == 2, rep["a_actualizar"]           # 10,11
    assert rep["sin_resolver"] == 2, rep["sin_resolver"]           # 12,13
    # nada cambió
    assert db.query(AsicSolicitud).filter_by(id=10).first().nombre_interno is None
    ids_resueltos = sorted(r["id"] for r in rep["resueltos"])
    assert ids_resueltos == [10, 11]
    assert {r["id"] for r in rep["no_resueltos"]} == {12, 13}


def test_ejecucion_rellena_y_vincula():
    db = _setup()
    rep = backfill_nombre_interno(dry_run=False, db=db, _=None)
    assert rep.get("ejecutado") is True and rep["a_actualizar"] == 2
    s10 = db.query(AsicSolicitud).filter_by(id=10).first()
    s11 = db.query(AsicSolicitud).filter_by(id=11).first()
    assert s10.nombre_interno == "Terpel 1"
    assert s11.nombre_interno == "Bavaria Norte"
    assert s11.contrato_ppa_id == 2          # vinculó la FK que faltaba
    # los no resueltos siguen vacíos; el que ya tenía no se tocó
    assert db.query(AsicSolicitud).filter_by(id=12).first().nombre_interno is None
    assert db.query(AsicSolicitud).filter_by(id=14).first().nombre_interno == "Ya tiene"


def test_idempotente():
    db = _setup()
    backfill_nombre_interno(dry_run=False, db=db, _=None)
    rep2 = backfill_nombre_interno(dry_run=False, db=db, _=None)
    assert rep2["a_actualizar"] == 0          # ya nada que rellenar de los resolubles
    assert rep2["total_sin_nombre"] == 2      # solo quedan los irresolubles (12,13)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(fns)} tests pasaron.")
