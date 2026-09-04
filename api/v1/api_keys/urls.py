from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("api-keys", views.ApiKeyViewSet, basename="api-keys")

urlpatterns = [path("", include(router.urls))]
