from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register(
    "panel-contable", views.PanelContableViewSet, basename="panel-contable",
)

urlpatterns = [path("", include(router.urls))]
