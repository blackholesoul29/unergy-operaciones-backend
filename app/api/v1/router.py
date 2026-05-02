from fastapi import APIRouter
from app.api.v1 import auth, clientes, proyectos, fallas, generacion, monitoreo, liquidaciones, ppa, asic

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(auth.usuarios_router)
api_router.include_router(clientes.router)
api_router.include_router(proyectos.router)
api_router.include_router(fallas.router)
api_router.include_router(generacion.router)
api_router.include_router(monitoreo.router)
api_router.include_router(liquidaciones.router)
api_router.include_router(ppa.router)
api_router.include_router(asic.router)
