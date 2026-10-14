"""SIGV2-1245: JWT signing secrets must come from ``core.config.settings``.

Several modules re-read ``os.getenv("JWT_SECRET_KEY", "dev-secret")`` at import
time, bypassing the strong-secret validation in ``core/config.py`` and silently
falling back to the publicly known literal ``"dev-secret"`` when the env var is
not exported into a worker process. These tests pin the contract: every module
uses the settings value, and nothing produces ``"dev-secret"``.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings

# Modules that must source JWT_SECRET_KEY exclusively from settings.
_SECRET_MODULES = [
    "routers.api_router",
    "middleware.session_checker",
    "services.auth_service",
    "auth.token_verifier",
    "services.guest_audit_service",
]


@pytest.mark.parametrize("module_name", _SECRET_MODULES)
def test_module_jwt_secret_key_matches_settings(module_name):
    module = importlib.import_module(module_name)
    assert module.JWT_SECRET_KEY == settings.JWT_SECRET_KEY
    assert module.JWT_SECRET_KEY != "dev-secret"


def test_session_checker_tracks_settings_value(monkeypatch):
    """Reloading the module under a rotated settings secret picks it up."""
    import middleware.session_checker as session_checker

    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "rotated-settings-secret-value")
    importlib.reload(session_checker)
    try:
        assert session_checker.JWT_SECRET_KEY == "rotated-settings-secret-value"
    finally:
        monkeypatch.undo()
        importlib.reload(session_checker)


@pytest.mark.parametrize(
    "module_name,os_environ_cleared",
    [
        ("routers.api_router", ["JWT_SECRET_KEY"]),
        ("middleware.session_checker", ["JWT_SECRET_KEY"]),
        ("services.guest_audit_service", ["JWT_SECRET_KEY"]),
    ],
)
def test_missing_env_secret_does_not_fall_back_to_dev_secret(
    monkeypatch, module_name, os_environ_cleared
):
    """With the env var absent, the module never resolves to "dev-secret"."""
    for var in os_environ_cleared:
        monkeypatch.delenv(var, raising=False)
    module = importlib.import_module(module_name)
    importlib.reload(module)
    try:
        assert module.JWT_SECRET_KEY == settings.JWT_SECRET_KEY
        assert module.JWT_SECRET_KEY != "dev-secret"
    finally:
        monkeypatch.undo()
        importlib.reload(module)


def test_cms_fix_delivery_token_secret_uses_settings(monkeypatch):
    from services import cms_fix_delivery_service as svc

    monkeypatch.delenv("CMS_CONFIRMATION_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "settings-jwt-secret")
    assert svc._token_secret() == "settings-jwt-secret"


def test_cms_fix_delivery_token_secret_prefers_dedicated_secret(monkeypatch):
    from services import cms_fix_delivery_service as svc

    monkeypatch.setenv("CMS_CONFIRMATION_TOKEN_SECRET", "dedicated-secret")
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "settings-jwt-secret")
    assert svc._token_secret() == "dedicated-secret"


def test_cms_fix_delivery_token_secret_never_returns_dev_secret(monkeypatch):
    from services import cms_fix_delivery_service as svc

    monkeypatch.delenv("CMS_CONFIRMATION_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
    monkeypatch.setattr(settings, "JWT_SECRET", None)
    with pytest.raises(ValueError):
        svc._token_secret()
