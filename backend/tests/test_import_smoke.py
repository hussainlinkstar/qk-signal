import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_main_and_auth_related_modules_import():
    main_module = importlib.import_module("main")
    assert getattr(main_module, "app", None) is not None

    importlib.import_module("routers.auth")
    importlib.import_module("routers.api_router")
    importlib.import_module("auth.security")
