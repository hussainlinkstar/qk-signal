import pytest
from unittest.mock import patch, MagicMock
from fastapi import Request
import middleware.rate_limiter as rate_limiter_module
from middleware.rate_limiter import rate_limiter
from services.ai_engine import AIFactory
from core.runtime_config import _cache


@pytest.fixture(autouse=True)
def wipe_cache():
    # Clear both config caches before and after each test; the rate limiter's
    # module-level cache would otherwise leak mocked limits into later tests.
    _cache.clear()
    rate_limiter_module._CONFIG_CACHE.clear()
    global _cache_ts
    _cache_ts = 0
    yield
    _cache.clear()
    rate_limiter_module._CONFIG_CACHE.clear()
    _cache_ts = 0


@patch("middleware.rate_limiter.get_config_value")
@patch("middleware.rate_limiter.SessionLocal")
@pytest.mark.asyncio
async def test_rate_limiter_uses_runtime_config(mock_session_local, mock_get_config):
    # Setup mocks
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    # Mock return values for get_config_value
    def mock_get_config_value(key, db):
        if key == "LOGIN_RATE_LIMIT":
            return 3
        if key == "LOGIN_RATE_WINDOW":
            return 60
        if key == "DEFAULT_RATE_LIMIT":
            return 5
        if key == "DEFAULT_RATE_WINDOW":
            return 60
        return 100

    mock_get_config.side_effect = mock_get_config_value

    # Create a mock request
    mock_request = MagicMock(spec=Request)
    mock_request.client.host = "192.168.1.1"
    mock_request.headers = {}
    mock_request.url.path = "/api/v1/auth/login"

    # Clear the config cache; other tests may have cached the real defaults.
    rate_limiter_module._CONFIG_CACHE.clear()

    # The limit is set to 3. After 3 recorded failures the next check blocks.
    for _ in range(3):
        await rate_limiter.record_login_failure(mock_request, "user@example.com")

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await rate_limiter.ensure_login_allowed(mock_request, "user@example.com")

    assert exc_info.value.status_code == 429


# get_model_instance resolves its DB session and config reader via local
# imports (`from database import SessionLocal` / `from core.runtime_config
# import get_config_value`), so the patch seams live on those source modules,
# not on services.ai_engine. The Bedrock cutover also normalizes every
# provider/tier to the single live "bedrock" provider, so the runtime-config
# key is "BEDROCK_<TIER>_MODEL".
@patch("core.runtime_config.get_config_value")
@patch("database.SessionLocal")
def test_ai_engine_uses_runtime_config(mock_session_local, mock_get_config):
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    def mock_get_config_value(key, db):
        if key == "BEDROCK_FAST_MODEL":
            return "bedrock-fast-override"
        return None

    mock_get_config.side_effect = mock_get_config_value

    factory = AIFactory()

    # Should use the runtime-config override (legacy provider names normalize to
    # bedrock under the cutover, so "google"/"fast" resolves BEDROCK_FAST_MODEL).
    provider, model = factory.get_model_instance("google", "fast")
    assert provider == "bedrock"
    assert model == "bedrock-fast-override"

    # Missing override should fall back to the default model map.
    provider, model = factory.get_model_instance("bedrock", "smart")
    assert provider == "bedrock"
    assert model != "bedrock-fast-override"
