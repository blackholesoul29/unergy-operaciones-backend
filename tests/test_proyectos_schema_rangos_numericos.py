"""ProyectoCreate/Update -- rangos numericos de latitud/longitud/altitud_msnm,
para atrapar typos de digitacion antes de llegar a la BD.

Se agregaron 2026-08-25 al consolidar Frontera.latitud/longitud/altitud_msnm
en Proyecto (migracion 094, auditoria de integridad de Fronteras): Frontera
ya tenia esta proteccion (migracion 084) y Proyecto nunca la tuvo pese a
tener sus propios latitud/longitud desde antes -- se traslada/agrega ahora
que Proyecto es la fuente unica. Respaldados por CHECK constraints en la BD
(ck_proyectos_latitud_rango/longitud_rango/altitud_msnm_rango, migracion 094)
para el caso de que un dato entre por otro camino."""
import pytest
from pydantic import ValidationError

from app.schemas.proyectos import ProyectoCreate, ProyectoUpdate


def test_latitud_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        ProyectoCreate(nombre_comercial="Test", latitud=950)


def test_longitud_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        ProyectoCreate(nombre_comercial="Test", longitud=-1800)


def test_latitud_longitud_validas_se_aceptan():
    p = ProyectoCreate(nombre_comercial="Test", latitud=8.5, longitud=-73.2)
    assert p.latitud == 8.5
    assert p.longitud == -73.2


def test_altitud_msnm_fuera_de_rango_se_rechaza():
    with pytest.raises(ValidationError):
        ProyectoCreate(nombre_comercial="Test", altitud_msnm=9000)


def test_altitud_msnm_valida_se_acepta():
    p = ProyectoCreate(nombre_comercial="Test", altitud_msnm=250)
    assert p.altitud_msnm == 250


def test_update_tambien_valida_rangos():
    with pytest.raises(ValidationError):
        ProyectoUpdate(nombre_comercial="Test", latitud=100)
    with pytest.raises(ValidationError):
        ProyectoUpdate(nombre_comercial="Test", altitud_msnm=-500)
