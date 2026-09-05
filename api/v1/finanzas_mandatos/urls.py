"""Rutas de mandatos de Finanzas. El prefijo tiene dos segmentos."""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "finanzas/mandatos", views.FinanzasMandatoViewSet,
    basename="finanzas-mandatos",
)

urlpatterns = [path("", include(router.urls))]
