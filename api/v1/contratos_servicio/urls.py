from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "contratos-servicio", views.ContratoServicioViewSet,
    basename="contratos-servicio",
)

urlpatterns = [path("", include(router.urls))]
