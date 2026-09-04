"""Rutas de operadores de red.

`operadores-red/contactos` se registra ANTES que `operadores-red`: el lookup de
detalle (`[^/.]+`) capturaría la palabra "contactos" como si fuera un id.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "operadores-red/contactos", views.OperadorRedContactoViewSet,
    basename="operadores-red-contactos",
)
router.register("operadores-red", views.OperadorRedViewSet, basename="operadores-red")

urlpatterns = [path("", include(router.urls))]
