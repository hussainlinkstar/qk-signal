"""Embedding service with caching, batching, and TF-IDF fallback.

AEX-12: Provides dense embedding vectors via Google text-embedding-004 for
grounding verification.  Falls back to TF-IDF sparse vectors when the
embedding API is unavailable.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}

# ── Constants ─────────────────────────────────────────────────────────

EMBEDDING_BATCH_SIZE = 100
"""Max texts per single embed_content API call (Google limit ~2048 but
we batch conservatively for latency)."""

EMBEDDING_DIMENSION = 1536
"""Output dimension for Cohere Embed v4 on Bedrock."""


# ── Typing ────────────────────────────────────────────────────────────


class EmbedCallable(Protocol):
    """Async callable that returns dense vectors for a list of texts."""

    async def __call__(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]: ...


# ── Dense vector helpers ──────────────────────────────────────────────


def dense_cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity for two dense float vectors of equal length."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── TF-IDF fallback helpers ──────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]


def tfidf_vectors_for_texts(
    texts: list[str],
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Build TF-IDF sparse vectors and the IDF table for *texts*."""
    documents = [_tokenize(t) for t in texts]
    if not documents:
        return [], {}

    df: Counter[str] = Counter()
    for doc in documents:
        for token in set(doc):
            df[token] += 1

    total = len(documents)
    idf = {tok: math.log((total + 1) / (freq + 1)) + 1 for tok, freq in df.items()}

    vectors: list[dict[str, float]] = []
    for doc in documents:
        counts = Counter(doc)
        denom = sum(counts.values()) or 1
        vectors.append({tok: (cnt / denom) * idf.get(tok, 1.0) for tok, cnt in counts.items()})
    return vectors, idf


def sparse_cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(v * right.get(k, 0.0) for k, v in left.items())
    ln = math.sqrt(sum(v * v for v in left.values()))
    rn = math.sqrt(sum(v * v for v in right.values()))
    if ln == 0 or rn == 0:
        return 0.0
    return dot / (ln * rn)


# ── EmbeddingCache ────────────────────────────────────────────────────


class EmbeddingCache:
    """Per-audit embedding cache with batched API calls and TF-IDF fallback.

    Usage (inside an async audit runner)::

        cache = EmbeddingCache(embed_fn=ai_client.embed_texts)
        await cache.warm(evidence_chunks + claim_texts)
        vec = cache.get(some_text)       # instant cache hit
        sim = cache.similarity(a, b)     # dense cosine similarity
    """

    def __init__(
        self,
        embed_fn: EmbedCallable | None = None,
        *,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self._embed_fn = embed_fn
        self._batch_size = batch_size
        self._cache: dict[str, list[float]] = {}
        self._using_dense = False
        self._total_texts_embedded = 0
        self._total_api_calls = 0
        self._total_latency_ms = 0.0
        self._fallback_reason: str | None = None

    # ── Public interface ──────────────────────────────────────────────

    @property
    def using_dense(self) -> bool:
        """Whether the cache holds real dense embeddings (vs TF-IDF)."""
        return self._using_dense

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "using_dense": self._using_dense,
            "total_texts_embedded": self._total_texts_embedded,
            "total_api_calls": self._total_api_calls,
            "total_latency_ms": round(self._total_latency_ms, 1),
            "cache_size": len(self._cache),
            "fallback_reason": self._fallback_reason,
        }

    async def warm(self, texts: list[str]) -> None:
        """Pre-compute embeddings for *texts*.

        Deduplicates, batches API calls, and falls back to no-op on
        failure (callers will use TF-IDF through the old path).
        """
        unique_texts = []
        seen: set[str] = set()
        for t in texts:
            if t not in seen:
                seen.add(t)
                unique_texts.append(t)

        uncached = [t for t in unique_texts if t not in self._cache]
        if not uncached:
            return

        if self._embed_fn is None:
            self._fallback_reason = "no_embed_fn"
            return

        try:
            await self._batch_embed(uncached)
            self._using_dense = True
        except Exception as exc:
            logger.warning(
                "Embedding API failed, will use TF-IDF fallback: %s",
                str(exc)[:200],
            )
            self._fallback_reason = f"api_error: {str(exc)[:150]}"
            self._cache.clear()
            self._using_dense = False

    def get(self, text: str) -> list[float] | None:
        """Return cached dense vector, or ``None`` if absent."""
        return self._cache.get(text)

    def similarity(self, text_a: str, text_b: str) -> float | None:
        """Dense cosine similarity between two previously-warmed texts.

        Returns ``None`` if either text has no cached embedding.
        """
        va = self._cache.get(text_a)
        vb = self._cache.get(text_b)
        if va is None or vb is None:
            return None
        return dense_cosine_similarity(va, vb)

    # ── Internal ──────────────────────────────────────────────────────

    async def _batch_embed(self, texts: list[str]) -> None:
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            t0 = time.monotonic()
            vectors = await self._embed_fn(batch)
            elapsed = (time.monotonic() - t0) * 1000
            self._total_api_calls += 1
            self._total_latency_ms += elapsed
            self._total_texts_embedded += len(batch)
            for text, vec in zip(batch, vectors):
                self._cache[text] = vec
