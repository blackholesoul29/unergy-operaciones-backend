from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("clientes", views.ClienteViewSet, basename="clientes")

urlpatterns = [path("", include(router.urls))]
