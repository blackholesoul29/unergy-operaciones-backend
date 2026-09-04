from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "mantenimiento-impacto", views.MantenimientoImpactoViewSet,
    basename="mantenimiento-impacto",
)

urlpatterns = [path("", include(router.urls))]
