from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("solar", views.SolarViewSet, basename="solar")

urlpatterns = [path("", include(router.urls))]
