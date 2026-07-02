import time
from app.services.xm import jobs


def test_crear_job_estado_inicial():
    job_id = jobs.crear_job()
    job = jobs.obtener_job(job_id)
    assert job["estado"] == "descargando"
    assert job["archivos_procesados"] == 0
    assert job["archivos_faltantes"] == []


def test_actualizar_job():
    job_id = jobs.crear_job()
    jobs.actualizar_job(job_id, estado="listo", archivos_procesados=10)
    job = jobs.obtener_job(job_id)
    assert job["estado"] == "listo"
    assert job["archivos_procesados"] == 10


def test_obtener_job_inexistente_devuelve_none():
    assert jobs.obtener_job("no-existe") is None


def test_job_expirado_se_limpia_al_crear_otro():
    job_id = jobs.crear_job()
    jobs._JOBS[job_id]["creado_en"] = time.time() - jobs._TTL_SEGUNDOS - 1
    jobs.crear_job()
    assert jobs.obtener_job(job_id) is None
