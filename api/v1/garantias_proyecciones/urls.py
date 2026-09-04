"""Rutas de proyecciones de garantía.

El prefijo tiene DOS segmentos (`garantias/proyecciones`), igual que en FastAPI.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "garantias/proyecciones", views.GarantiaProyeccionViewSet,
    basename="garantias-proyecciones",
)

urlpatterns = [path("", include(router.urls))]
