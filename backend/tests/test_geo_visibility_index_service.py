import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.geo.visibility_service import GeoVisibilityService


@pytest.mark.asyncio
async def test_compute_visibility_index_from_mentions_and_citations():
    responses = {
        "prompt-1": "Acme is a leading option for SMB payroll.",
        "prompt-2": {
            "answer": "Top alternatives",
            "citations": ["https://reviews.example.com/acme"],
        },
        "prompt-3": "No relevant brand listed here.",
    }

    async def fake_provider(prompt: str):
        return responses[prompt]

    service = GeoVisibilityService(provider_callable=fake_provider)

    result = await service.compute_visibility_index(
        brand_name="Acme",
        prompts=["prompt-1", "prompt-2", "prompt-3"],
    )

    assert result["visibility_index"] == pytest.approx(66.67)
    assert result["visible_prompts"] == 2
    assert len(result["results"]) == 3
    assert result["results"][0]["brand_mentioned"] is True
    assert result["results"][1]["brand_cited"] is True
    assert result["results"][2]["visible"] is False


@pytest.mark.asyncio
async def test_compute_visibility_index_marks_provider_failures_as_non_visible():
    async def fake_provider(prompt: str):
        if prompt == "bad":
            raise RuntimeError("provider unavailable")
        return "No mention"

    service = GeoVisibilityService(provider_callable=fake_provider)

    result = await service.compute_visibility_index(
        brand_name="Acme",
        prompts=["good", "bad"],
    )

    assert result["visibility_index"] == 0
    assert result["results"][1]["status"] == "error"
    assert "provider unavailable" in result["results"][1]["error"]


@pytest.mark.asyncio
async def test_compute_visibility_index_validates_inputs():
    service = GeoVisibilityService(provider_callable=lambda _prompt: None)

    with pytest.raises(ValueError, match="brand_name is required"):
        await service.compute_visibility_index(brand_name=" ", prompts=["test"])

    with pytest.raises(ValueError, match="At least one controlled prompt is required"):
        await service.compute_visibility_index(brand_name="Acme", prompts=[])
