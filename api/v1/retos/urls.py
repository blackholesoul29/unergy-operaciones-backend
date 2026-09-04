"""Rutas del tablero de retos.

Dos detalles que hacen que las URLs queden IDENTICAS a las de FastAPI:

1. **`trailing_slash=False`.** FastAPI sirve `/api/v1/retos`; el router de DRF
   generaria `/api/v1/retos/` y Django redirigiria con un 301 que en un POST
   pierde el cuerpo. Va junto con `APPEND_SLASH = False` en settings.

2. **`retos/metricas` se registra ANTES que `retos`.** Django resuelve en orden
   y el lookup por defecto (`[^/.]+`) hace que `retos/{pk}` capture la palabra
   "metricas" como si fuera un id. Invertir estas dos lineas rompe los tres
   endpoints de metricas con un 404 dificil de leer.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("retos/metricas", views.MetricaViewSet, basename="retos-metricas")
router.register("retos", views.RetoViewSet, basename="retos")

urlpatterns = [path("", include(router.urls))]
