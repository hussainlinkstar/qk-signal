"""Tests for AEX-12: Embedding similarity upgrade for Track B grounding.

Covers:
- EmbeddingCache warm/get/similarity/fallback
- Dense retrieval & grounding in HallucinationService
- Batch embedding API calls
- Cost tracking / embedding stats
- Graceful fallback to TF-IDF when embeddings unavailable
- dense_cosine_similarity helper
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from services.embedding_service import (
    EmbeddingCache,
    dense_cosine_similarity,
    sparse_cosine_similarity,
    tfidf_vectors_for_texts,
)
from services.hallucination_service import HallucinationService


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_fake_embed_fn(dimension: int = 8):
    """Return an async mock that produces deterministic unit vectors.

    Each unique text maps to a reproducible direction so that semantically
    'similar' texts can be arranged by the test author.
    """
    _cache: dict[str, list[float]] = {}
    _call_count = 0

    async def _embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
        nonlocal _call_count
        _call_count += 1
        results: list[list[float]] = []
        for text in texts:
            if text not in _cache:
                idx = len(_cache)
                vec = [0.0] * dimension
                vec[idx % dimension] = 1.0
                if idx >= dimension:
                    vec[(idx - 1) % dimension] = 0.5
                _cache[text] = vec
            results.append(list(_cache[text]))
        return results

    _embed.call_count = lambda: _call_count
    _embed._cache = _cache
    return _embed


def _make_semantic_embed_fn():
    """Embed fn where semantically similar texts share vector components."""
    mapping: dict[str, list[float]] = {}

    async def _embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
        results: list[list[float]] = []
        for t in texts:
            if t not in mapping:
                mapping[t] = [0.0] * 8
            results.append(list(mapping[t]))
        return results

    _embed._mapping = mapping
    return _embed


def _make_analysis_with_claims(claim_texts: list[str]) -> dict[str, Any]:
    return {
        "claims": [
            {"id": f"c-{i}", "text": t, "field_path": "test", "field_label": "Test"}
            for i, t in enumerate(claim_texts, 1)
        ]
    }


# ── dense_cosine_similarity ──────────────────────────────────────────


def test_dense_cosine_identical_vectors():
    v = [1.0, 2.0, 3.0]
    assert dense_cosine_similarity(v, v) == pytest.approx(1.0)


def test_dense_cosine_orthogonal_vectors():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert dense_cosine_similarity(a, b) == pytest.approx(0.0)


def test_dense_cosine_opposite_vectors():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert dense_cosine_similarity(a, b) == pytest.approx(-1.0)


def test_dense_cosine_empty_vectors():
    assert dense_cosine_similarity([], []) == 0.0


def test_dense_cosine_zero_norm():
    assert dense_cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_dense_cosine_length_mismatch():
    assert dense_cosine_similarity([1.0, 2.0], [1.0]) == 0.0


# ── tfidf_vectors_for_texts ──────────────────────────────────────────


def test_tfidf_vectors_basic():
    texts = ["the cat sat on the mat", "a dog played in the yard"]
    vectors, idf = tfidf_vectors_for_texts(texts)
    assert len(vectors) == 2
    assert "cat" in vectors[0]
    assert "dog" in vectors[1]
    assert len(idf) > 0


def test_tfidf_vectors_empty():
    vectors, idf = tfidf_vectors_for_texts([])
    assert vectors == []
    assert idf == {}


# ── sparse_cosine_similarity ─────────────────────────────────────────


def test_sparse_cosine_identical():
    v = {"a": 1.0, "b": 2.0}
    assert sparse_cosine_similarity(v, v) == pytest.approx(1.0)


def test_sparse_cosine_disjoint():
    assert sparse_cosine_similarity({"a": 1.0}, {"b": 1.0}) == pytest.approx(0.0)


def test_sparse_cosine_empty():
    assert sparse_cosine_similarity({}, {"a": 1.0}) == 0.0


# ── EmbeddingCache ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_warm_and_get():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["hello", "world"])

    assert cache.using_dense is True
    assert cache.get("hello") is not None
    assert cache.get("world") is not None
    assert cache.get("missing") is None
    assert cache.stats["total_texts_embedded"] == 2
    assert cache.stats["total_api_calls"] >= 1


@pytest.mark.asyncio
async def test_cache_deduplicates():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["same", "same", "same", "other"])

    assert cache.stats["total_texts_embedded"] == 2
    assert cache.stats["cache_size"] == 2


@pytest.mark.asyncio
async def test_cache_skips_already_cached():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["a", "b"])
    calls_after_first = cache.stats["total_api_calls"]

    await cache.warm(["a", "b"])
    assert cache.stats["total_api_calls"] == calls_after_first


@pytest.mark.asyncio
async def test_cache_batching():
    """Texts exceeding batch_size are split into multiple API calls."""
    embed_fn = _make_fake_embed_fn(dimension=16)
    cache = EmbeddingCache(embed_fn=embed_fn, batch_size=3)

    texts = [f"text-{i}" for i in range(7)]
    await cache.warm(texts)

    assert cache.stats["total_api_calls"] == 3  # 3 + 3 + 1
    assert cache.stats["total_texts_embedded"] == 7


@pytest.mark.asyncio
async def test_cache_similarity():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["alpha", "beta"])

    sim = cache.similarity("alpha", "beta")
    assert sim is not None
    assert isinstance(sim, float)

    missing_sim = cache.similarity("alpha", "missing")
    assert missing_sim is None


@pytest.mark.asyncio
async def test_cache_api_failure_falls_back():
    """When embedding API raises, cache should not be dense."""

    async def _failing_embed(texts, *, model=None):
        raise RuntimeError("API quota exceeded")

    cache = EmbeddingCache(embed_fn=_failing_embed)
    await cache.warm(["some text"])

    assert cache.using_dense is False
    assert cache.get("some text") is None
    assert "api_error" in (cache.stats["fallback_reason"] or "")


@pytest.mark.asyncio
async def test_cache_no_embed_fn():
    """When embed_fn is None, cache remains empty."""
    cache = EmbeddingCache(embed_fn=None)
    await cache.warm(["text"])

    assert cache.using_dense is False
    assert cache.stats["fallback_reason"] == "no_embed_fn"


@pytest.mark.asyncio
async def test_cache_stats_tracking():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["a", "b", "c"])

    stats = cache.stats
    assert stats["using_dense"] is True
    assert stats["total_texts_embedded"] == 3
    assert stats["total_api_calls"] >= 1
    assert stats["total_latency_ms"] >= 0
    assert stats["cache_size"] == 3
    assert stats["fallback_reason"] is None


# ── HallucinationService with dense embeddings ───────────────────────


def _make_dense_cache_from_mapping(
    mapping: dict[str, list[float]],
) -> EmbeddingCache:
    """Create a pre-warmed EmbeddingCache from a text→vector mapping."""
    cache = EmbeddingCache(embed_fn=None)
    cache._cache = dict(mapping)
    cache._using_dense = True
    return cache


def test_hallucination_dense_grounding_high_similarity():
    """Claims with high embedding similarity to evidence are grounded."""
    source = "The website lacks mobile optimization and responsive design elements."
    claim = "The site is not responsive on phones and mobile devices."

    base_vec = [0.9, 0.1, 0.0, 0.0]
    similar_vec = [0.85, 0.15, 0.05, 0.0]

    mapping = {source: base_vec, claim: similar_vec}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    sim = dense_cosine_similarity(base_vec, similar_vec)
    assert sim > 0.65, f"Expected similarity > 0.65, got {sim}"
    assert result["supported_sentences"] == 1
    assert result["score"] == 100
    assert result.get("embedding_stats") is not None
    assert result["embedding_stats"]["using_dense"] is True


def test_hallucination_dense_grounding_low_similarity():
    """Claims with low embedding similarity to evidence are flagged."""
    source = "The website uses modern CSS grid layout with responsive breakpoints."
    claim = "The company was founded in 1995 in Silicon Valley."

    orthogonal_a = [1.0, 0.0, 0.0, 0.0]
    orthogonal_b = [0.0, 0.0, 0.0, 1.0]

    mapping = {source: orthogonal_a, claim: orthogonal_b}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    sim = dense_cosine_similarity(orthogonal_a, orthogonal_b)
    assert sim < 0.4, f"Expected similarity < 0.4, got {sim}"
    assert result["supported_sentences"] == 0
    assert claim in result["unsupported_sentences"]


def test_hallucination_dense_mixed_claims():
    """Mix of grounded and ungrounded claims with embeddings."""
    source = "Fast page load times improve user experience and search rankings."
    grounded_claim = "Page speed affects SEO performance positively."
    hallucinated_claim = "The company won an award for innovation in 2023."

    source_vec = [0.8, 0.2, 0.0, 0.0]
    grounded_vec = [0.75, 0.25, 0.05, 0.0]
    hallucinated_vec = [0.0, 0.0, 0.9, 0.1]

    mapping = {
        source: source_vec,
        grounded_claim: grounded_vec,
        hallucinated_claim: hallucinated_vec,
    }
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([grounded_claim, hallucinated_claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    assert result["total_sentences"] == 2
    assert result["supported_sentences"] == 1
    assert result["score"] == 50


def test_hallucination_dense_evidence_retrieval_method():
    """Evidence refs should include retrieval_method='embedding' when dense."""
    source = "Structured data helps search engines understand page content."
    claim = "Schema markup improves search engine interpretation."

    close_vec_a = [0.9, 0.1, 0.0, 0.0]
    close_vec_b = [0.85, 0.15, 0.0, 0.0]

    mapping = {source: close_vec_a, claim: close_vec_b}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    cv = result["claim_verifications"]
    assert len(cv) == 1
    evidence = cv[0]["evidence_refs"]
    assert len(evidence) >= 1
    assert evidence[0].get("retrieval_method") == "embedding"


def test_hallucination_dense_threshold_boundary():
    """Claims exactly at embedding_grounding_threshold are grounded."""
    source = "Content about web performance metrics."
    claim = "Information about site speed indicators."

    angle = math.acos(0.65)
    vec_a = [math.cos(0.0), math.sin(0.0), 0.0, 0.0]
    vec_b = [math.cos(angle), math.sin(angle), 0.0, 0.0]

    sim = dense_cosine_similarity(vec_a, vec_b)
    assert abs(sim - 0.65) < 0.01

    mapping = {source: vec_a, claim: vec_b}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService(embedding_grounding_threshold=0.65)
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    assert result["supported_sentences"] == 1


def test_hallucination_dense_below_threshold():
    """Claims just below embedding_grounding_threshold are not grounded."""
    source = "Content about web performance metrics."
    claim = "Information about site speed indicators."

    angle = math.acos(0.63)
    vec_a = [math.cos(0.0), math.sin(0.0), 0.0, 0.0]
    vec_b = [math.cos(angle), math.sin(angle), 0.0, 0.0]

    sim = dense_cosine_similarity(vec_a, vec_b)
    assert sim < 0.65

    mapping = {source: vec_a, claim: vec_b}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService(embedding_grounding_threshold=0.65)
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    assert result["supported_sentences"] == 0


def test_hallucination_falls_back_to_tfidf_when_cache_not_dense():
    """When embedding_cache.using_dense is False, TF-IDF path is used."""
    cache = EmbeddingCache(embed_fn=None)
    assert cache.using_dense is False

    source = "OpenAI released a new model update for coding workflows."
    analysis = _make_analysis_with_claims(["OpenAI released a new model update."])

    service = HallucinationService()
    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    assert result["total_sentences"] == 1
    assert result["embedding_stats"]["using_dense"] is False


def test_hallucination_no_cache_uses_tfidf():
    """When no embedding_cache is passed, TF-IDF is used (backward compat)."""
    source = "The site has excellent Core Web Vitals scores."
    analysis = _make_analysis_with_claims(["The site has excellent Core Web Vitals scores."])

    service = HallucinationService()
    result = service.analyze(
        source_content=source,
        analysis=analysis,
    )

    assert result["total_sentences"] == 1
    assert "embedding_stats" not in result


def test_hallucination_dense_embedding_stats_in_result():
    """Result includes embedding_stats when cache is provided."""
    source = "Some evidence text for grounding."
    claim = "A claim to verify."

    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 0.0]

    mapping = {source: vec_a, claim: vec_b}
    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([claim])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    stats = result.get("embedding_stats")
    assert stats is not None
    assert stats["using_dense"] is True
    assert stats["cache_size"] == 2


def test_hallucination_dense_multiple_chunks():
    """Multiple evidence chunks — best match wins."""
    source = (
        "The website uses excellent structured data markup. "
        "It also has fast page load times. "
        "The mobile experience is well optimized."
    )
    claim = "Page load times are excellent."

    chunk_1_vec = [0.1, 0.9, 0.0, 0.0]
    chunk_2_vec = [0.0, 0.1, 0.9, 0.0]
    claim_vec = [0.0, 0.05, 0.85, 0.1]

    svc = HallucinationService(chunk_size=40, chunk_overlap=0)
    chunks = svc._chunk_text(source)

    mapping = {claim: claim_vec}
    for i, chunk in enumerate(chunks):
        if i == 0:
            mapping[chunk] = chunk_1_vec
        elif i == 1:
            mapping[chunk] = [0.0, 0.1, 0.85, 0.05]
        else:
            mapping[chunk] = chunk_2_vec

    cache = _make_dense_cache_from_mapping(mapping)

    analysis = _make_analysis_with_claims([claim])
    result = svc.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    cv = result["claim_verifications"]
    assert len(cv) == 1
    best_retrieval = max(float(ref.get("retrieval_score") or 0) for ref in cv[0]["evidence_refs"])
    assert best_retrieval > 0.6


def test_hallucination_dense_no_evidence_for_claim():
    """Claim with no embedding in cache gets no evidence."""
    source = "Some evidence text."

    cache = _make_dense_cache_from_mapping({source: [1.0, 0.0]})

    service = HallucinationService()
    analysis = _make_analysis_with_claims(["A claim with no embedding."])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    assert result["supported_sentences"] == 0


def test_hallucination_dense_brand_truth_bypasses_embeddings():
    """Brand truth path should not use embedding cache."""
    source = "Some content."
    brand_truth = {
        "company_name": {"value": "Acme Corp", "confidence": "high"},
    }

    cache = _make_dense_cache_from_mapping({"x": [1.0]})

    service = HallucinationService()
    analysis = _make_analysis_with_claims(["The company name is Acme Corp."])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        brand_truth_payload=brand_truth,
        embedding_cache=cache,
    )

    assert "embedding_stats" not in result


@pytest.mark.asyncio
async def test_cache_warm_empty_list():
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm([])

    assert cache.stats["total_texts_embedded"] == 0
    assert cache.stats["total_api_calls"] == 0


@pytest.mark.asyncio
async def test_cache_partial_warm():
    """Warming with new texts after initial warm only embeds new ones."""
    embed_fn = _make_fake_embed_fn()
    cache = EmbeddingCache(embed_fn=embed_fn)

    await cache.warm(["a", "b"])
    assert cache.stats["total_texts_embedded"] == 2

    await cache.warm(["b", "c"])
    assert cache.stats["total_texts_embedded"] == 3
    assert cache.stats["cache_size"] == 3


def test_hallucination_dense_certainty_levels():
    """Dense path produces correct certainty_level labels."""
    source = "Evidence text for testing certainty levels."

    high_vec = [0.99, 0.01, 0.0, 0.0]

    mapping = {source: [1.0, 0.0, 0.0, 0.0]}

    claim_high = "Nearly identical evidence text."
    mapping[claim_high] = high_vec

    cache = _make_dense_cache_from_mapping(mapping)

    service = HallucinationService()
    analysis = _make_analysis_with_claims([claim_high])

    result = service.analyze(
        source_content=source,
        analysis=analysis,
        embedding_cache=cache,
    )

    cv = result["claim_verifications"]
    assert len(cv) == 1
    assert cv[0]["certainty_level"] in ("high", "medium", "low")
    assert cv[0]["certainty_score"] > 0


# ── _build_embedding_cache helper ─────────────────────────────────────


@pytest.mark.asyncio
async def test_build_embedding_cache_integration():
    """_build_embedding_cache extracts chunks + claims and warms cache."""
    from audit_runner import _build_embedding_cache

    embed_fn = _make_fake_embed_fn(dimension=16)

    class FakeAIClient:
        async def embed_texts(self, texts, *, model=None):
            return await embed_fn(texts, model=model)

    ai_client = FakeAIClient()
    svc = HallucinationService()
    source = "Some web content about SEO best practices and keyword optimization."
    analysis = _make_analysis_with_claims(
        [
            "SEO best practices are important.",
            "Keyword optimization helps rankings.",
        ]
    )

    cache = await _build_embedding_cache(
        ai_client=ai_client,
        hallucination_service=svc,
        markdown_content=source,
        ai_analysis_results=analysis,
    )

    assert cache is not None
    assert cache.using_dense is True
    assert cache.stats["cache_size"] > 0


@pytest.mark.asyncio
async def test_build_embedding_cache_no_embed_method():
    """Returns None when ai_client lacks embed_texts method."""
    from audit_runner import _build_embedding_cache

    class NoEmbedClient:
        pass

    cache = await _build_embedding_cache(
        ai_client=NoEmbedClient(),
        hallucination_service=HallucinationService(),
        markdown_content="content",
        ai_analysis_results=_make_analysis_with_claims(["claim"]),
    )

    assert cache is None


# ── AIFactory.embed_texts → Bedrock Cohere Embed v4 ───────────────────


@pytest.mark.asyncio
async def test_embed_texts_uses_bedrock_cohere_1536():
    """embed_texts calls bedrock invoke_model and returns 1536-dim vectors.

    Mocks bedrock_client.invoke_model with the verified Cohere Embed v4
    response shape; no network is touched.
    """
    import io
    import json

    from services.ai_engine import AIFactory

    texts = ["first chunk of text", "second chunk of text"]
    fake_vectors = [[0.01] * 1536, [0.02] * 1536]
    captured: dict[str, Any] = {}

    class FakeBody:
        def __init__(self, payload: bytes) -> None:
            self._buf = io.BytesIO(payload)

        def read(self) -> bytes:
            return self._buf.read()

    class FakeBedrockClient:
        def invoke_model(self, *, modelId: str, body: str):  # noqa: N803
            captured["modelId"] = modelId
            captured["body"] = json.loads(body)
            payload = json.dumps({"embeddings": {"float": fake_vectors}}).encode()
            return {"body": FakeBody(payload)}

    engine = AIFactory.__new__(AIFactory)
    engine.bedrock_client = FakeBedrockClient()

    result = await engine.embed_texts(texts)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(len(vec) == 1536 for vec in result)
    assert result == fake_vectors
    # Verified Cohere Embed v4 request body shape.
    assert captured["body"]["texts"] == texts
    assert captured["body"]["input_type"] == "search_document"
    assert captured["body"]["embedding_types"] == ["float"]
    assert captured["modelId"].endswith("cohere.embed-v4:0")


@pytest.mark.asyncio
async def test_embed_texts_requires_bedrock_client():
    """embed_texts raises ConnectionError when no Bedrock client is set."""
    from services.ai_engine import AIFactory

    engine = AIFactory.__new__(AIFactory)
    engine.bedrock_client = None

    with pytest.raises(ConnectionError):
        await engine.embed_texts(["text"])
