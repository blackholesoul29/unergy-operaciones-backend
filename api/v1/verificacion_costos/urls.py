from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
# El prefijo va con guion, como la ruta de FastAPI: /api/v1/verificacion-costos
router.register(
    "verificacion-costos", views.VerificacionCostoViewSet,
    basename="verificacion-costos",
)

urlpatterns = [path("", include(router.urls))]
