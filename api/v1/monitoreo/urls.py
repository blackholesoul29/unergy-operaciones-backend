from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("monitoreo", views.MonitoreoViewSet, basename="monitoreo")

urlpatterns = [path("", include(router.urls))]
