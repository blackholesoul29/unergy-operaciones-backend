from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("fallas", views.FallaViewSet, basename="fallas")

urlpatterns = [path("", include(router.urls))]
