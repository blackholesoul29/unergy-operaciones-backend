"""Rutas de portafolios.

`asignar` es una acción de lista, y `DefaultRouter` registra las acciones de
lista ANTES de la ruta de detalle — por eso `PATCH /portafolios/asignar` no lo
captura el `{pk}`. No hace falta invertir nada a mano, pero conviene saber por
qué funciona antes de reordenar el archivo.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("portafolios", views.PortafolioViewSet, basename="portafolios")

urlpatterns = [path("", include(router.urls))]
