"""Configuración de tests del ops backend.

Inserta la raíz del repo en sys.path y stubea `app.api.v1.auth` — el endpoint
solo lo usa como dependencia FastAPI (`get_current_user`), que no se invoca en
los tests de funciones puras. Evita la cadena de imports de seguridad (bcrypt,
python-jose) innecesaria aquí; en el CI del repo esas deps sí están instaladas.
"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("SECRET_KEY", "test-secret-key-qa-0123456789")

from fastapi import APIRouter

_auth_stub = types.ModuleType("app.api.v1.auth")
_auth_stub.get_current_user = lambda: None
# Las rutas de escritura (p.ej. garantías) dependen además de `_require_admin`; sin él,
# importar esos routers desde un test revienta con un ImportError críptico.
_auth_stub._require_admin = lambda *a, **k: None
_auth_stub.router = APIRouter()
_auth_stub.usuarios_router = APIRouter()
sys.modules["app.api.v1.auth"] = _auth_stub
