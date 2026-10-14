import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from core.config import settings
from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

_ENCRYPTED_VALUE_PREFIX = "enc::"
_LEGACY_FERNET_PREFIX = "gAAAA"
_UNSAFE_ENCRYPTION_SECRETS = {
    "",
    "dev-secret",
    "changeme",
    "dev_oauth_token_encryption_key_change_me",
}


def _normalize_secret(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _resolve_encryption_secret() -> str:
    dedicated_secret = _normalize_secret(settings.OAUTH_TOKEN_ENCRYPTION_KEY)
    jwt_secret = _normalize_secret(settings.JWT_SECRET_KEY)
    legacy_jwt_secret = _normalize_secret(settings.JWT_SECRET)

    if dedicated_secret and dedicated_secret not in _UNSAFE_ENCRYPTION_SECRETS:
        if settings.is_production and dedicated_secret in {jwt_secret, legacy_jwt_secret}:
            raise ValueError(
                "OAUTH_TOKEN_ENCRYPTION_KEY must be distinct from JWT signing secrets in production."
            )
        return dedicated_secret

    if settings.is_production:
        raise ValueError(
            "OAUTH_TOKEN_ENCRYPTION_KEY must be set to a dedicated secret in production."
        )

    for fallback_secret in (jwt_secret, legacy_jwt_secret):
        if fallback_secret and fallback_secret not in _UNSAFE_ENCRYPTION_SECRETS:
            return fallback_secret

    raise ValueError("Set OAUTH_TOKEN_ENCRYPTION_KEY before using encrypted columns.")


def _allow_legacy_plaintext_secrets() -> bool:
    return bool(getattr(settings, "ALLOW_LEGACY_PLAINTEXT_SECRETS", False))


def reset_encryption_state() -> None:
    _get_fernet.cache_clear()


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    secret = _resolve_encryption_secret()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


class EncryptedText(TypeDecorator):
    """Encrypt/decrypt text payloads at rest using Fernet."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        token = _get_fernet().encrypt(value.encode("utf-8"))
        return f"{_ENCRYPTED_VALUE_PREFIX}{token.decode('utf-8')}"

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        token_value = value
        if value.startswith(_ENCRYPTED_VALUE_PREFIX):
            token_value = value[len(_ENCRYPTED_VALUE_PREFIX) :]
        elif not value.startswith(_LEGACY_FERNET_PREFIX):
            if _allow_legacy_plaintext_secrets():
                return value
            raise ValueError(
                "Encountered legacy plaintext secret data. "
                "Migrate encrypted rows or temporarily enable ALLOW_LEGACY_PLAINTEXT_SECRETS."
            )
        try:
            return _get_fernet().decrypt(token_value.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            raise ValueError("Stored encrypted secret could not be decrypted.") from None
