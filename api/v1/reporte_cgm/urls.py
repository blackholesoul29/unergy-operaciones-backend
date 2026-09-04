from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("reporte-cgm", views.ReporteCGMViewSet, basename="reporte-cgm")

urlpatterns = [path("", include(router.urls))]
