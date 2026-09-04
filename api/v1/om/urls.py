"""Rutas del panel O&M.

Las acciones más específicas van declaradas primero en el ViewSet, y
`DefaultRouter` conserva ese orden: `factura/{periodo}/file` tiene que
resolverse antes que `factura/{periodo}`, o el `[\\w-]+` del período se comería
la palabra «file».
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("om", views.OmViewSet, basename="om")

urlpatterns = [path("", include(router.urls))]
