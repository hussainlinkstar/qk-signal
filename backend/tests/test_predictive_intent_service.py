import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.predictive_intent_service import (
    HashingEmbeddingProvider,
    IndexedIntentItem,
    IntentSearchHit,
    PredictiveIntentService,
)


class DummyEmbeddingProvider:
    def __init__(self):
        self._vectors = {
            "what is schema markup?": [1.0, 0.0],
            "how to improve core web vitals?": [0.0, 1.0],
            "schema help": [0.9, 0.1],
        }

    def embed(self, text: str) -> list[float]:
        return self._vectors.get(text.lower(), [0.5, 0.5])


class DummyIndexProvider:
    def __init__(self):
        self.items: list[tuple[IndexedIntentItem, list[float]]] = []

    def reset(self) -> None:
        self.items = []

    def upsert(self, item: IndexedIntentItem, embedding: list[float]) -> None:
        self.items.append((item, embedding))

    def query(self, query_embedding: list[float], top_k: int) -> list[IntentSearchHit]:
        scores = []
        for item, embedding in self.items:
            similarity = sum(a * b for a, b in zip(query_embedding, embedding))
            scores.append(IntentSearchHit(item=item, similarity=similarity))
        scores.sort(key=lambda hit: hit.similarity, reverse=True)
        return scores[:top_k]


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_embedding_flow_generates_deterministic_normalized_vectors() -> None:
    provider = HashingEmbeddingProvider(dimensions=32)

    embedding_a = provider.embed("Improve local SEO snippets")
    embedding_b = provider.embed("Improve local SEO snippets")

    assert len(embedding_a) == 32
    assert embedding_a == embedding_b
    assert pytest.approx(sum(component * component for component in embedding_a), rel=1e-5) == 1.0


def test_top_k_ranking_returns_nearest_neighbors(db_session) -> None:
    service = PredictiveIntentService(
        embedding_provider=DummyEmbeddingProvider(),
        index_provider=DummyIndexProvider(),
        reindex_interval_seconds=3600,
    )
    service.ingest_corpus(
        db_session,
        entries=[
            {"question": "What is schema markup?", "context": "structured data basics"},
            {"question": "How to improve core web vitals?", "context": "speed and ux"},
        ],
        reindex=True,
    )

    results = service.predict(db_session, query="schema help", top_k=1)

    assert len(results) == 1
    assert results[0]["question"] == "What is schema markup?"


def test_score_normalization_maps_values_between_zero_and_one(db_session) -> None:
    service = PredictiveIntentService(
        embedding_provider=DummyEmbeddingProvider(),
        index_provider=DummyIndexProvider(),
        reindex_interval_seconds=3600,
    )
    service.ingest_corpus(
        db_session,
        entries=[
            {"question": "What is schema markup?"},
            {"question": "How to improve core web vitals?"},
        ],
        reindex=True,
    )

    results = service.predict(db_session, query="schema help", top_k=2)

    assert results[0]["normalized_score"] == pytest.approx(1.0)
    assert results[1]["normalized_score"] == pytest.approx(0.0)
    assert all(0.0 <= item["normalized_score"] <= 1.0 for item in results)


def test_predict_persists_telemetry(db_session) -> None:
    service = PredictiveIntentService(
        embedding_provider=DummyEmbeddingProvider(),
        index_provider=DummyIndexProvider(),
        reindex_interval_seconds=3600,
    )
    service.ingest_corpus(
        db_session, entries=[{"question": "What is schema markup?"}], reindex=True
    )
    results = service.predict(db_session, query="schema help", top_k=1)

    service.persist_query_telemetry(
        db=db_session,
        query="schema help",
        top_k=1,
        provider="local",
        latency_ms=12.5,
        results=results,
    )

    telemetry = db_session.query(models.IntentQueryTelemetry).all()
    assert len(telemetry) == 1
    assert telemetry[0].provider == "local"
    assert telemetry[0].response_payload[0]["question"] == "What is schema markup?"


def test_classify_query_intent_prefers_corpus_metadata_intent(db_session) -> None:
    service = PredictiveIntentService(
        embedding_provider=DummyEmbeddingProvider(),
        index_provider=DummyIndexProvider(),
        reindex_interval_seconds=3600,
    )
    service.ingest_corpus(
        db_session,
        entries=[
            {
                "question": "What is schema markup?",
                "metadata": {"intent": "informational"},
            }
        ],
        reindex=True,
    )

    intent = service.classify_query_intent(db_session, query="schema help", category="seo")

    assert intent == "informational"


def test_classify_query_intent_uses_lexical_fallback_without_corpus_match(db_session) -> None:
    service = PredictiveIntentService(
        embedding_provider=DummyEmbeddingProvider(),
        index_provider=DummyIndexProvider(),
        reindex_interval_seconds=3600,
    )

    intent = service.classify_query_intent(
        db_session,
        query="book hvac service near me",
        category="hvac",
    )

    assert intent == "transactional"
