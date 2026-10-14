from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.runtime_cors import RuntimeCORSMiddleware


def _build_app(origins_ref: dict[str, list[str]]) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    app.add_middleware(
        RuntimeCORSMiddleware,
        allow_origins_resolver=lambda: list(origins_ref["origins"]),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
            "Accept-Language",
        ],
    )
    return app


def test_runtime_cors_preflight_uses_latest_origin_list_without_restart() -> None:
    origins_ref = {"origins": ["https://legacy.example.com"]}
    client = TestClient(_build_app(origins_ref))

    legacy_response = client.options(
        "/ping",
        headers={
            "Origin": "https://legacy.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert legacy_response.status_code == 200
    assert legacy_response.headers["access-control-allow-origin"] == "https://legacy.example.com"

    blocked_response = client.options(
        "/ping",
        headers={
            "Origin": "https://fresh.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert blocked_response.status_code == 400

    origins_ref["origins"] = ["https://fresh.example.com"]

    refreshed_response = client.options(
        "/ping",
        headers={
            "Origin": "https://fresh.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert refreshed_response.status_code == 200
    assert refreshed_response.headers["access-control-allow-origin"] == "https://fresh.example.com"


def test_runtime_cors_simple_response_reflects_updated_origin() -> None:
    origins_ref = {"origins": ["https://legacy.example.com"]}
    client = TestClient(_build_app(origins_ref))

    origins_ref["origins"] = ["https://fresh.example.com"]
    response = client.get("/ping", headers={"Origin": "https://fresh.example.com"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://fresh.example.com"
    assert response.headers["access-control-allow-credentials"] == "true"
