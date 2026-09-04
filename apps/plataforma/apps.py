from django.apps import AppConfig


class PlataformaConfig(AppConfig):
    # `name` lleva la ruta completa porque las apps viven bajo `apps/`; `label`
    # se fija a mano para que el app_label (y por tanto el nombre de las
    # migraciones y las tablas de Django) no quede como "apps_plataforma".
    name = "apps.plataforma"
    label = "plataforma"
    verbose_name = "Plataforma"
