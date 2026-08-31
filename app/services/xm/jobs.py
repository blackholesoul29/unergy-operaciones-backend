"""Job store en memoria para la Descarga de XM.

El backend corre en un solo proceso uvicorn (WORKERS=1 en el
docker-compose.yml), así que un dict en memoria protegido por un lock basta —
no hace falta Redis ni tabla en BD para esto.
"""
import threading
import time
import uuid

_LOCK = threading.Lock()
_JOBS: dict[str, dict] = {}
_TTL_SEGUNDOS = 3600


def crear_job() -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _limpiar_expirados()
        _JOBS[job_id] = {
            "estado": "descargando",
            "creado_en": time.time(),
            "archivos_procesados": 0,
            "archivos_totales": 0,
            "archivos_faltantes": [],
            "codigos_sin_match": [],
            "meses_fronteras_usados": {},
            "resultado": None,
            "error_code": None,
            "error_message": None,
        }
    return job_id


def actualizar_job(job_id: str, **campos) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(campos)


def obtener_job(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def _limpiar_expirados() -> None:
    ahora = time.time()
    expirados = [jid for jid, j in _JOBS.items() if ahora - j["creado_en"] > _TTL_SEGUNDOS]
    for jid in expirados:
        del _JOBS[jid]
