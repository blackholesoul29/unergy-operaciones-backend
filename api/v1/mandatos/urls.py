"""Rutas de mandatos: dos prefijos, un módulo.

`mandato-inversionistas` es su propio recurso en FastAPI (`maestra_router`) y se
conserva así.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("mandatos", views.MandatoViewSet, basename="mandatos")
router.register(
    "mandato-inversionistas", views.MandatoInversionistaViewSet,
    basename="mandato-inversionistas",
)

urlpatterns = [path("", include(router.urls))]
