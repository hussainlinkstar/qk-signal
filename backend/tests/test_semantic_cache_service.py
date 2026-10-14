import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.semantic_cache_service import (
    SEMANTIC_CACHE_SITE_CLASSIFY_TTL_SECONDS,
    SemanticCacheService,
)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self.values[key] = value
        self.ttls[key] = ttl


def test_build_key_is_stable_for_equivalent_payloads() -> None:
    service = SemanticCacheService(redis_client=FakeRedis())
    key_a = service.build_key(
        feature_key="site.classify",
        route_provider="google",
        route_tier="fast",
        semantic_payload={"content": "Acme", "meta": {"a": 1, "b": 2}},
    )
    key_b = service.build_key(
        feature_key="site.classify",
        route_provider="google",
        route_tier="fast",
        semantic_payload={"meta": {"b": 2, "a": 1}, "content": "Acme"},
    )

    assert key_a == key_b


def test_set_and_get_json_round_trip_with_feature_ttl() -> None:
    fake_redis = FakeRedis()
    service = SemanticCacheService(redis_client=fake_redis)
    semantic_payload = {"content": "Acme Corp homepage"}

    service.set_json(
        feature_key="site.classify",
        route_provider="google",
        route_tier="fast",
        semantic_payload=semantic_payload,
        value={"category": "SaaS", "confidence": 0.91},
    )

    cache_key = next(iter(fake_redis.values))
    assert fake_redis.ttls[cache_key] == SEMANTIC_CACHE_SITE_CLASSIFY_TTL_SECONDS

    cached_entry = service.get_json(
        feature_key="site.classify",
        route_provider="google",
        route_tier="fast",
        semantic_payload=semantic_payload,
    )

    assert cached_entry is not None
    assert cached_entry["response"] == {"category": "SaaS", "confidence": 0.91}
    assert json.loads(fake_redis.values[cache_key])["metadata"]["feature_key"] == "site.classify"
