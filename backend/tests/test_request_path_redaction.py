from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import _safe_request_path


def _request(path: str, route_path: str | None = None) -> SimpleNamespace:
    route = SimpleNamespace(path=route_path) if route_path else None
    return SimpleNamespace(
        scope={"route": route} if route else {},
        url=SimpleNamespace(path=path),
    )


def test_magic_link_token_is_redacted_before_route_resolution() -> None:
    request = _request("/api/v1/magic-links/super-secret-token/oauth/google/start")

    assert _safe_request_path(request) == "/api/v1/magic-links/{token}/oauth/google/start"


def test_resolved_route_template_is_used_for_metric_cardinality() -> None:
    request = _request(
        "/api/v1/projects/42",
        "/api/v1/projects/{project_id}",
    )

    assert _safe_request_path(request) == "/api/v1/projects/{project_id}"
