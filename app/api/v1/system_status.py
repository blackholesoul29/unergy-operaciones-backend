"""Estado del sistema y salud de las dependencias externas.

Expone el estado agregado que mantiene `health_monitor` (ver
`app/services/health_monitor.py`). Público — como `/health` — para que
herramientas de monitoreo externas puedan consultarlo sin token.
"""
from fastapi import APIRouter

from app.services.health_monitor import health_monitor

router = APIRouter(tags=["System Status"])


@router.get("/system-status")
def system_status():
    """Salud agregada del backend y sus dependencias externas."""
    return health_monitor.get_overall_status()


@router.post("/system-status/refresh")
async def system_status_refresh():
    """Fuerza un health check inmediato de todas las dependencias."""
    await health_monitor.check_all()
    return health_monitor.get_overall_status()
