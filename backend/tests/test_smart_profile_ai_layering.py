"""SIGV2-1252: the smart-profile LLM call must not live in a router.

AGENTS.md 4.4 forbids calling an LLM API directly from ``backend/routers/``.
The smart-profile generator used to call ``core.bedrock_text.bedrock_generate_text``
inside ``routers/workspace_router.py``; it now goes through the ai-service layer
(``services.smart_profile_service``), which is the single seam the rest of the
synchronous request paths (pre-scan, advisor chat, CMS) already use.

These tests therefore mock the *service*, never Bedrock, and additionally pin
the layering rule so the direct call cannot come back.
"""

from __future__ import annotations

from pathlib import Path
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import routers.workspace_router as workspace_router_module
from routers.workspace_router import (
    ProjectCreateRequest,
    ProjectSmartProfileGenerateRequest,
    create_project_in_current_workspace,
    generate_project_smart_profile,
)
from services import smart_profile_service
from tests.test_workspace_project_endpoints import _build_db, _cleanup

_ROUTER_SOURCE = Path(workspace_router_module.__file__)

_EVIDENCE = {
    "project": {
        "name": "Layered Profile",
        "domain_url": "layered.example",
        "target_country": "RO",
        "language": "en",
        "competitors": [],
    },
    "domain_snapshot": {"title": "Layered Profile"},
    "latest_audit": {},
}


def _stub_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        workspace_router_module,
        "_build_grounded_smart_profile_sources",
        lambda project, db_session: (_EVIDENCE, ["project_profile_fields"]),
        raising=True,
    )


def _create_project(db, user) -> int:
    created = create_project_in_current_workspace(
        payload=ProjectCreateRequest(
            name="Layered Profile",
            domain_url="layered.example",
            target_country="RO",
            language="en",
        ),
        user=user,
        db=db,
    )
    return int(created["id"])


def test_workspace_router_does_not_call_bedrock_directly() -> None:
    source = _ROUTER_SOURCE.read_text(encoding="utf-8")

    assert "core.bedrock_text" not in source
    assert "bedrock_generate_text" not in source


def test_generate_project_smart_profile_goes_through_ai_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        project_id = _create_project(db, user)
        _stub_sources(monkeypatch)

        calls: list[dict] = []

        def _fake_generate(evidence: dict) -> dict:
            calls.append(evidence)
            return {
                "icp_roles": ["CEO", "CMO"],
                "pain_points": "Low AI answer visibility.",
                "usp": "Entity-first GEO framework.",
                "priority_pulse_tags": ["GEO", "AEO"],
                "sme_profiles": ["LinkedIn: Geo Strategist"],
            }

        monkeypatch.setattr(
            smart_profile_service,
            "generate_smart_profile",
            _fake_generate,
            raising=True,
        )

        response = generate_project_smart_profile(
            project_id=project_id,
            payload=ProjectSmartProfileGenerateRequest(overwrite_existing=True),
            user=user,
            db=db,
        )

        assert calls == [_EVIDENCE]
        db.refresh(user)
        assert user.credits == 4
        assert response.project.icp_roles == ["CEO", "CMO"]
        assert response.project.usp == "Entity-first GEO framework."
        assert response.project.priority_pulse_tags == ["GEO", "AEO"]
        assert "pain_points" in response.generated_fields
        assert response.grounded_sources == ["project_profile_fields"]
        assert response.model == smart_profile_service.resolve_smart_profile_model()
    finally:
        _cleanup(db, engine)


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            smart_profile_service.SmartProfileUnavailableError(
                "AI generation is currently unavailable."
            ),
            503,
            "AI generation is currently unavailable.",
        ),
        (
            smart_profile_service.SmartProfileGenerationError("boom"),
            502,
            "AI generation failed: boom",
        ),
        (
            smart_profile_service.SmartProfileInvalidResponseError(
                "AI generation returned an invalid response format."
            ),
            502,
            "AI generation returned an invalid response format.",
        ),
    ],
)
def test_generate_project_smart_profile_maps_service_errors(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    db, _session_factory, engine, user = _build_db()
    try:
        project_id = _create_project(db, user)
        _stub_sources(monkeypatch)

        def _raise(evidence: dict) -> dict:
            raise error

        monkeypatch.setattr(
            smart_profile_service,
            "generate_smart_profile",
            _raise,
            raising=True,
        )

        with pytest.raises(HTTPException) as exc_info:
            generate_project_smart_profile(
                project_id=project_id,
                payload=ProjectSmartProfileGenerateRequest(overwrite_existing=True),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == expected_status
        assert exc_info.value.detail == expected_detail
    finally:
        _cleanup(db, engine)


def test_service_raises_unavailable_when_bedrock_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smart_profile_service, "bedrock_available", lambda: False, raising=True)

    with pytest.raises(smart_profile_service.SmartProfileUnavailableError):
        smart_profile_service.generate_smart_profile(_EVIDENCE)


def test_service_keeps_bedrock_call_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def _fake_bedrock(system: str, user_prompt: str, **kwargs):
        captured["system"] = system
        captured["user"] = user_prompt
        captured["kwargs"] = kwargs
        # Not JSON on purpose: this test pins the call shape, not the parsing.
        return "sorry, no json today"

    monkeypatch.setattr(smart_profile_service, "bedrock_available", lambda: True, raising=True)
    monkeypatch.setattr(smart_profile_service, "bedrock_generate_text", _fake_bedrock, raising=True)

    with pytest.raises(smart_profile_service.SmartProfileInvalidResponseError):
        smart_profile_service.generate_smart_profile(_EVIDENCE)

    assert captured["kwargs"]["tier"] == "smart"
    assert captured["kwargs"]["max_tokens"] == 2048
    assert captured["kwargs"]["use_case"] == "smart_profile"
    assert "temperature" not in captured["kwargs"]
    assert "Layered Profile" in captured["user"]
