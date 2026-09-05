"""Rutas de GESCON/ASIC.

`gescon/diccionario` es una acción de LISTA, así que `DefaultRouter` la registra
antes de la ruta de detalle y el `{pk}` no la captura.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("asic", views.AsicViewSet, basename="asic")

urlpatterns = [path("", include(router.urls))]
