from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "estados-resultados", views.EstadoResultadoViewSet,
    basename="estados-resultados",
)

urlpatterns = [path("", include(router.urls))]
