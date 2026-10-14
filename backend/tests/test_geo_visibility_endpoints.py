import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parents[1]))

from main import app, get_current_user


class _FakeGeoVisibilityService:
    async def run_visibility_audit(self, *, target, location, seed_queries, brand):
        seed_queries = seed_queries or []
        return {
            "target": target,
            "location": location,
            "provider": "mock-provider",
            "seed_queries": seed_queries,
            "total_queries": len(seed_queries),
            "citations": 1,
            "timed_out_queries": 0,
            "visibility_index": 100.0,
            "partial_results": False,
            "results": [
                {
                    "query": seed_queries[0] if seed_queries else "best clinic",
                    "answer_excerpt": "Acme is highly visible",
                    "provider_citations": ["https://example.com"],
                    "brand_cited": bool(brand),
                    "status": "ok",
                    "error": None,
                }
            ],
        }


def _override_user():
    return SimpleNamespace(id=1, email="user@example.com", role="user")


def test_geo_visibility_get_and_post_return_same_payload(monkeypatch):
    from routers import api_router as api_module

    monkeypatch.setattr(api_module, "geo_visibility_service", _FakeGeoVisibilityService())
    app.dependency_overrides[get_current_user] = _override_user

    client = TestClient(app)
    params = {
        "target": "https://example.com",
        "location": "Bucharest",
        "seed_queries": ["dentist bucharest", "best dental clinic"],
        "brand": "Acme",
    }

    get_response = client.get("/api/v1/geo-visibility", params=params)
    post_response = client.post("/api/v1/geo-visibility", json=params)

    assert get_response.status_code == 200
    assert post_response.status_code == 200
    assert get_response.json() == post_response.json()

    app.dependency_overrides.clear()


def test_geo_visibility_openapi_lists_post_only():
    client = TestClient(app)
    openapi = client.get("/openapi.json")

    assert openapi.status_code == 200
    path_spec = openapi.json()["paths"]["/api/v1/geo-visibility"]
    assert "post" in path_spec
    assert "get" not in path_spec
