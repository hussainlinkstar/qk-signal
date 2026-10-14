import base64
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import cms_ai_service


def test_ensure_faq_section_appends_faq_block_when_missing() -> None:
    body = "## Intro\n\nParagraph text."
    faq_items = [
        {"question": "What is GEO?", "answer": "Generative Engine Optimization for AI systems."}
    ]

    updated = cms_ai_service._ensure_faq_section(body, faq_items)

    assert "## FAQ" in updated
    assert "### What is GEO?" in updated
    assert "Generative Engine Optimization for AI systems." in updated


def test_ensure_faq_section_preserves_existing_faq() -> None:
    body = "## Intro\n\nText\n\n## FAQ\n\n### Existing?\nYes."
    faq_items = [{"question": "New question", "answer": "New answer"}]

    updated = cms_ai_service._ensure_faq_section(body, faq_items)

    assert updated == body


def test_normalize_cms_image_data_url_repairs_double_base64_payload() -> None:
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    )
    inner_b64 = base64.b64encode(png_bytes).decode("ascii")
    double_b64 = base64.b64encode(inner_b64.encode("ascii")).decode("ascii")
    broken = f"data:image/png;base64,{double_b64}"

    normalized = cms_ai_service.normalize_cms_image_data_url(broken)

    assert normalized is not None
    assert normalized.startswith("data:image/png;base64,")
    assert normalized.endswith(inner_b64)
