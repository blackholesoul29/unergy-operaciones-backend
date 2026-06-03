import os, sys, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path: sys.path.insert(0, ROOT)
os.environ.setdefault("SECRET_KEY", "test-secret-key-ci-0123456789")
_auth = types.ModuleType("app.api.v1.auth"); _auth.get_current_user = lambda: None
sys.modules["app.api.v1.auth"] = _auth
