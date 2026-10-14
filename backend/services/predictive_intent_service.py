import hashlib
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import models
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class IndexedIntentItem:
    corpus_id: int
    question: str
    context: str | None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class IntentSearchHit:
    item: IndexedIntentItem
    similarity: float


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...


class VectorIndexProvider(Protocol):
    def reset(self) -> None: ...

    def upsert(self, item: IndexedIntentItem, embedding: list[float]) -> None: ...

    def query(self, query_embedding: list[float], top_k: int) -> list[IntentSearchHit]: ...


class HashingEmbeddingProvider:
    """Deterministic local embedding provider using hashed token buckets."""

    def __init__(self, dimensions: int = 64):
        self.dimensions = max(8, dimensions)

    def embed(self, text: str) -> list[float]:
        tokens = [token for token in text.lower().split() if token]
        if not tokens:
            return [0.0 for _ in range(self.dimensions)]

        vector = [0.0 for _ in range(self.dimensions)]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:2], byteorder="big") % self.dimensions
            sign = 1.0 if digest[2] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(component * component for component in vector))
        if norm == 0:
            return vector
        return [component / norm for component in vector]


class LocalFaissLikeIndexProvider:
    """In-memory cosine similarity index with a FAISS-compatible behavior surface."""

    def __init__(self):
        self._entries: list[tuple[IndexedIntentItem, list[float]]] = []

    def reset(self) -> None:
        self._entries = []

    def upsert(self, item: IndexedIntentItem, embedding: list[float]) -> None:
        self._entries = [entry for entry in self._entries if entry[0].corpus_id != item.corpus_id]
        self._entries.append((item, embedding))

    def query(self, query_embedding: list[float], top_k: int) -> list[IntentSearchHit]:
        scored: list[IntentSearchHit] = []
        for item, embedding in self._entries:
            similarity = _cosine_similarity(query_embedding, embedding)
            scored.append(IntentSearchHit(item=item, similarity=similarity))
        scored.sort(key=lambda hit: hit.similarity, reverse=True)
        return scored[: max(0, top_k)]


class ElasticsearchDenseVectorIndexProvider:
    """Stubbed provider abstraction for future Elasticsearch dense-vector usage."""

    def __init__(self):
        self._local_fallback = LocalFaissLikeIndexProvider()
        logger.info("Using local fallback index while Elasticsearch provider is not wired")

    def reset(self) -> None:
        self._local_fallback.reset()

    def upsert(self, item: IndexedIntentItem, embedding: list[float]) -> None:
        self._local_fallback.upsert(item, embedding)

    def query(self, query_embedding: list[float], top_k: int) -> list[IntentSearchHit]:
        return self._local_fallback.query(query_embedding, top_k)


def build_index_provider(provider_name: str) -> VectorIndexProvider:
    normalized = provider_name.strip().lower()
    if normalized in {"local", "faiss"}:
        return LocalFaissLikeIndexProvider()
    if normalized in {"elasticsearch", "es"}:
        return ElasticsearchDenseVectorIndexProvider()
    logger.warning("Unknown intent index provider '%s'. Falling back to local.", provider_name)
    return LocalFaissLikeIndexProvider()


class PredictiveIntentService:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider | None = None,
        index_provider: VectorIndexProvider | None = None,
        reindex_interval_seconds: int | None = None,
    ):
        self.embedding_provider = embedding_provider or HashingEmbeddingProvider()
        self.index_provider = index_provider or build_index_provider(
            os.getenv("INTENT_INDEX_PROVIDER", "local")
        )
        self.reindex_interval = timedelta(
            seconds=reindex_interval_seconds
            if reindex_interval_seconds is not None
            else int(os.getenv("INTENT_REINDEX_INTERVAL_SECONDS", "900"))
        )
        self._last_reindex_at: datetime | None = None

    def ingest_corpus(
        self, db: Session, entries: list[dict[str, Any]], reindex: bool = True
    ) -> int:
        inserted = 0
        for entry in entries:
            question = str(entry.get("question", "")).strip()
            if not question:
                continue
            context = entry.get("context")
            metadata = entry.get("metadata")
            db.add(
                models.IntentCorpusEntry(
                    question=question,
                    context=context.strip() if isinstance(context, str) else None,
                    metadata_json=metadata if isinstance(metadata, dict) else None,
                )
            )
            inserted += 1

        db.commit()
        if reindex and inserted > 0:
            self.rebuild_index(db)
        return inserted

    def rebuild_index(self, db: Session) -> int:
        self.index_provider.reset()
        corpus_entries = (
            db.query(models.IntentCorpusEntry).order_by(models.IntentCorpusEntry.id.asc()).all()
        )
        for row in corpus_entries:
            item = IndexedIntentItem(
                corpus_id=row.id,
                question=row.question,
                context=row.context,
                metadata=row.metadata_json if isinstance(row.metadata_json, dict) else None,
            )
            embedding = self.embedding_provider.embed(
                f"{row.question}\n{row.context or ''}".strip()
            )
            self.index_provider.upsert(item, embedding)
        self._last_reindex_at = datetime.now(timezone.utc)
        return len(corpus_entries)

    def maybe_reindex(self, db: Session) -> None:
        now = datetime.now(timezone.utc)
        if self._last_reindex_at is None or now - self._last_reindex_at >= self.reindex_interval:
            self.rebuild_index(db)

    def predict(self, db: Session, query: str, top_k: int) -> list[dict[str, Any]]:
        self.maybe_reindex(db)
        query_embedding = self.embedding_provider.embed(query)
        hits = self.index_provider.query(query_embedding, top_k=top_k)
        normalized_scores = _normalize_scores([hit.similarity for hit in hits])

        results: list[dict[str, Any]] = []
        for hit, normalized_score in zip(hits, normalized_scores):
            results.append(
                {
                    "corpus_id": hit.item.corpus_id,
                    "question": hit.item.question,
                    "context": hit.item.context,
                    "metadata": hit.item.metadata or {},
                    "similarity": hit.similarity,
                    "normalized_score": normalized_score,
                }
            )
        return results

    def classify_query_intent(self, db: Session, *, query: str, category: str | None = None) -> str:
        candidate = " ".join(
            part.strip()
            for part in (query, category or "")
            if isinstance(part, str) and part.strip()
        )
        if not candidate:
            return "informational"

        try:
            predictions = self.predict(db=db, query=candidate, top_k=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Intent prediction failed, using lexical fallback: %s", exc)
            predictions = []

        predicted = _intent_from_predictions(predictions)
        if predicted:
            return predicted
        return _infer_intent_from_query_text(candidate)

    def persist_query_telemetry(
        self,
        db: Session,
        query: str,
        top_k: int,
        provider: str,
        latency_ms: float,
        results: list[dict[str, Any]],
    ) -> None:
        db.add(
            models.IntentQueryTelemetry(
                query=query,
                top_k=top_k,
                provider=provider,
                latency_ms=latency_ms,
                response_payload=json.loads(json.dumps(results)),
            )
        )
        db.commit()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    length = min(len(left), len(right))
    dot_product = sum(left[i] * right[i] for i in range(length))
    left_norm = math.sqrt(sum(left[i] * left[i] for i in range(length)))
    right_norm = math.sqrt(sum(right[i] * right[i] for i in range(length)))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    min_score = min(scores)
    max_score = max(scores)
    if math.isclose(min_score, max_score):
        return [1.0 for _ in scores]
    return [max(0.0, min(1.0, (score - min_score) / (max_score - min_score))) for score in scores]


ALLOWED_INTENTS = {"informational", "transactional", "navigational"}


def _intent_from_predictions(predictions: list[dict[str, Any]]) -> str | None:
    intent_scores: dict[str, float] = {}
    for row in predictions:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        intent_value = str(metadata.get("intent") or "").strip().lower()
        if intent_value not in ALLOWED_INTENTS:
            continue
        weight = float(row.get("normalized_score") or 0.0)
        intent_scores[intent_value] = intent_scores.get(intent_value, 0.0) + max(0.0, weight)

    if not intent_scores:
        return None
    return sorted(intent_scores.items(), key=lambda item: item[1], reverse=True)[0][0]


def _infer_intent_from_query_text(query: str) -> str:
    text = query.lower()
    transactional_keywords = (
        "buy",
        "price",
        "pricing",
        "quote",
        "book",
        "hire",
        "order",
        "checkout",
        "demo",
        "trial",
        "subscribe",
    )
    navigational_keywords = (
        "login",
        "official",
        "site",
        "address",
        "contact",
        "directions",
        "hours",
        "phone",
        "near me",
    )
    if any(keyword in text for keyword in transactional_keywords):
        return "transactional"
    if any(keyword in text for keyword in navigational_keywords):
        return "navigational"
    return "informational"
