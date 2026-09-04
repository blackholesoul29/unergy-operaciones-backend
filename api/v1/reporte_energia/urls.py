from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "reporte-energia", views.ReporteEnergiaViewSet, basename="reporte-energia",
)

urlpatterns = [path("", include(router.urls))]
