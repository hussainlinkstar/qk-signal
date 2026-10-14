from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_BOOTSTRAP_LOCK = Lock()
_BOOTSTRAPPED = False


def _parse_bool(raw_value: str | None, *, default: bool = False) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_environment(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"prod", "production", "live"}:
        return "production"
    if normalized in {"dev", "development", "local", "test"}:
        return "development"
    return normalized or "development"


def _sync_environment_aliases(environment: str) -> None:
    os.environ["ENVIRONMENT"] = environment
    os.environ["APP_ENV"] = environment


def _dotenv_candidates(backend_dir: Path, root_dir: Path, environment: str) -> tuple[Path, ...]:
    if environment == "development":
        return (
            backend_dir / ".env.development",
            root_dir / ".env.development",
            backend_dir / ".env",
            root_dir / ".env",
        )
    return (
        backend_dir / ".env",
        root_dir / ".env",
    )


def _overlay_ssm_parameters() -> None:
    """Overlay secrets from AWS SSM Parameter Store using the instance role.

    Parameters under SSM_PARAM_PREFIX (default ``/qiko-signal/``) are loaded as
    environment variables. SecureString values are decrypted via KMS. When
    SSM_OVERRIDE is true (default), SSM is authoritative over values already
    present in the environment. If SSM is unreachable (e.g. local dev with no
    AWS credentials), the overlay is skipped silently and dotenv values are used.

    The default used to be ``/thothgraph/``, the namespace retired when the
    product was renamed, while the README, ``deploy/VPS_DEPLOYMENT_RO.md`` and
    ``scripts/seed_ssm.py`` all documented ``/qiko-signal/``. Which namespace an
    environment actually read therefore depended on whether anyone had
    remembered to set the variable, and the two namespaces had drifted apart:
    ``/qiko-signal/EMAIL_FROM_NAME`` was still "ThothGraph Intelligence
    Analyzer", so every alert from an environment following the documentation
    went out under the retired brand (SIGV2-1279).
    """
    if not _parse_bool(os.getenv("SSM_ENABLED"), default=True):
        return

    prefix = (os.getenv("SSM_PARAM_PREFIX") or "/qiko-signal/").strip()
    if not prefix.endswith("/"):
        prefix += "/"
    override = _parse_bool(os.getenv("SSM_OVERRIDE"), default=True)
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "eu-central-1").strip()

    try:
        import boto3
    except Exception:
        logger.debug("boto3 not available; skipping SSM overlay.")
        return

    try:
        client = boto3.client("ssm", region_name=region)
        loaded = 0
        paginator = client.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=prefix, Recursive=True, WithDecryption=True):
            for param in page.get("Parameters", []) or []:
                key = param["Name"].split("/")[-1]
                value = param.get("Value")
                if value is None:
                    continue
                if not override and (os.getenv(key) or "").strip():
                    continue
                os.environ[key] = value
                loaded += 1
        logger.info("Environment bootstrap completed with SSM (loaded_secrets=%s).", loaded)
    except Exception as exc:  # pragma: no cover - depends on AWS availability
        logger.warning("SSM overlay skipped (%s); using dotenv/env values.", type(exc).__name__)


def bootstrap_environment() -> None:
    """Load dotenv files, then overlay secrets from AWS SSM Parameter Store."""
    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return

        backend_dir = Path(__file__).resolve().parents[1]
        root_dir = backend_dir.parent

        initial_environment = _normalize_environment(
            os.getenv("ENVIRONMENT") or os.getenv("APP_ENV")
        )
        for dotenv_path in _dotenv_candidates(backend_dir, root_dir, initial_environment):
            if dotenv_path.exists():
                load_dotenv(dotenv_path=dotenv_path, override=False)

        resolved_environment = _normalize_environment(
            os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or initial_environment
        )
        if resolved_environment != initial_environment:
            for dotenv_path in _dotenv_candidates(backend_dir, root_dir, resolved_environment):
                if dotenv_path.exists():
                    load_dotenv(dotenv_path=dotenv_path, override=False)
        _sync_environment_aliases(resolved_environment)

        _overlay_ssm_parameters()

        _BOOTSTRAPPED = True
