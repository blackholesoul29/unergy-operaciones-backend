from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "generacion-solar", views.GeneracionSolarViewSet,
    basename="generacion-solar",
)

urlpatterns = [path("", include(router.urls))]
