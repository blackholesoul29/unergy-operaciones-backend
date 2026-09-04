"""Rutas de autenticación y usuarios.

Son dos recursos en FastAPI (`router` y `usuarios_router`) y se conservan así:
`/auth` no lleva prefijo de usuarios y viceversa.
"""

from django.urls import include, path
from rest_framework import routers

from . import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("auth", views.AuthViewSet, basename="auth")
router.register("usuarios", views.UsuarioViewSet, basename="usuarios")

urlpatterns = [path("", include(router.urls))]
