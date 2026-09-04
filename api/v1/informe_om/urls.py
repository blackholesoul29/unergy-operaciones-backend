from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("informe-om", views.InformeOmViewSet, basename="informe-om")

urlpatterns = [path("", include(router.urls))]
