import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.audit_output_language_service import (
    build_audit_output_language_instruction,
    get_audit_output_language_name,
    resolve_audit_output_language,
)


def test_audit_output_language_defaults_to_english(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUDIT_OUTPUT_LANGUAGE", "en", raising=False)

    assert resolve_audit_output_language("ro") == "en"
    assert get_audit_output_language_name() == "English"
    assert (
        "Always communicate in English."
        == build_audit_output_language_instruction().split(" Do not", 1)[0]
    )


def test_audit_output_language_can_be_configured_for_future_rollout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIT_OUTPUT_LANGUAGE", "ro", raising=False)

    assert resolve_audit_output_language() == "ro"
    assert get_audit_output_language_name() == "Romanian"
    assert "Always communicate in Romanian." in build_audit_output_language_instruction()


def test_audit_output_language_supports_explicit_override_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AUDIT_OUTPUT_LANGUAGE", "en", raising=False)

    assert resolve_audit_output_language("ro", allow_override=True) == "ro"
