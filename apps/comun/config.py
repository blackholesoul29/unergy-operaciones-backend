"""Configuración del entorno con acceso por atributo.

Los servicios portados desde FastAPI usan `settings.UNERGY_API_URL` y no
`os.environ["UNERGY_API_URL"]`. Este objeto conserva esa forma para que el
código venga tal cual del original: cuanto menos se le toque a un cliente de una
API externa, menos hay que volver a verificar contra esa API.

No es `django.conf.settings` a propósito: son credenciales de terceros que solo
usan dos o tres módulos, y meterlas en `config/settings.py` obliga a declarar
cada variable nueva en dos sitios.

`apps/liquidaciones/services/api_externa.py` y
`apps/energia/services/unergy_api.py` tienen su propia copia de esto, anterior a
este módulo; deberían converger acá.
"""

import os


class _Entorno:
    def __getattr__(self, nombre: str) -> str:
        return os.environ.get(nombre, "")


settings = _Entorno()
