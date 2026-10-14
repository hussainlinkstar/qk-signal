from types import SimpleNamespace

import pytest

from core.config import Settings
from core.encrypted_types import (
    EncryptedText,
    _get_fernet,
    _resolve_encryption_secret,
    reset_encryption_state,
)
import core.encrypted_types as encrypted_types


def _set_fake_settings(monkeypatch, **overrides) -> None:
    defaults = {
        "OAUTH_TOKEN_ENCRYPTION_KEY": "dedicated-encryption-secret",
        "JWT_SECRET_KEY": "jwt-signing-secret",
        "JWT_SECRET": None,
        "is_production": False,
        "ALLOW_LEGACY_PLAINTEXT_SECRETS": False,
    }
    defaults.update(overrides)
    monkeypatch.setattr(encrypted_types, "settings", SimpleNamespace(**defaults))
    reset_encryption_state()


def test_encrypted_text_round_trip_uses_prefixed_ciphertext(monkeypatch) -> None:
    _set_fake_settings(monkeypatch, is_production=True)
    field = EncryptedText()

    stored_value = field.process_bind_param("top-secret", None)

    assert stored_value.startswith("enc::")
    assert stored_value != "top-secret"
    assert field.process_result_value(stored_value, None) == "top-secret"


def test_encrypted_text_reads_legacy_fernet_tokens(monkeypatch) -> None:
    _set_fake_settings(monkeypatch)
    field = EncryptedText()
    legacy_token = _get_fernet().encrypt(b"legacy-secret").decode("utf-8")

    assert field.process_result_value(legacy_token, None) == "legacy-secret"


def test_encrypted_text_rejects_plaintext_values_by_default(monkeypatch) -> None:
    _set_fake_settings(monkeypatch, ALLOW_LEGACY_PLAINTEXT_SECRETS=False)
    field = EncryptedText()

    with pytest.raises(ValueError, match="legacy plaintext secret data"):
        field.process_result_value("plaintext-secret", None)


def test_encrypted_text_can_temporarily_allow_legacy_plaintext(monkeypatch) -> None:
    _set_fake_settings(monkeypatch, ALLOW_LEGACY_PLAINTEXT_SECRETS=True)
    field = EncryptedText()

    assert field.process_result_value("plaintext-secret", None) == "plaintext-secret"


def test_production_requires_dedicated_encryption_secret(monkeypatch) -> None:
    _set_fake_settings(
        monkeypatch,
        OAUTH_TOKEN_ENCRYPTION_KEY=None,
        JWT_SECRET_KEY="jwt-signing-secret",
        is_production=True,
    )

    with pytest.raises(ValueError, match="dedicated secret"):
        _resolve_encryption_secret()


def test_production_rejects_reusing_jwt_secret_for_encryption(monkeypatch) -> None:
    _set_fake_settings(
        monkeypatch,
        OAUTH_TOKEN_ENCRYPTION_KEY="shared-secret",
        JWT_SECRET_KEY="shared-secret",
        is_production=True,
    )

    with pytest.raises(ValueError, match="distinct from JWT signing secrets"):
        _resolve_encryption_secret()


def test_settings_validate_oauth_encryption_secret_in_production() -> None:
    with pytest.raises(ValueError, match="OAUTH_TOKEN_ENCRYPTION_KEY"):
        Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="jwt-secret",
            JWT_REFRESH_SECRET_KEY="refresh-secret",
            SESSION_SECRET_KEY="session-secret",
            OAUTH_TOKEN_ENCRYPTION_KEY="jwt-secret",
        )
