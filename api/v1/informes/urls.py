"""Rutas de informes.

**El prefijo lleva barra final** (`informes/`): el router de FastAPI declara las
rutas como `/informes/` y `/informes/{id}`, con barra, y hay que conservarlas
tal cual.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("informes", views.InformeViewSet, basename="informes")

urlpatterns = [path("", include(router.urls))]
