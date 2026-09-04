from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("alertas", views.AlertaViewSet, basename="alertas")

urlpatterns = [path("", include(router.urls))]
