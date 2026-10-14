"""Generate email template previews in light and forced-dark variants."""

from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_PATH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_PATH))

# Keep standalone runs deterministic
os.environ.setdefault("APP_ENV", "test")

from services.email_templates import (  # noqa: E402
    DEFAULT_PREVIEW_CONTEXT,
    RENDER_FAILURE_MARKER,
    TEMPLATE_DEFINITIONS,
    render_template,
)


dummy_context = {
    **DEFAULT_PREVIEW_CONTEXT,
    "brand_name": "Qiko Signal",
    "view_in_browser_url": "https://qiko.ai/signal/email-preview",
    "social_links": [
        {"platform": "x", "label": "X", "glyph": "X", "url": "https://x.com/qikoai"},
        {
            "platform": "linkedin",
            "label": "LinkedIn",
            "glyph": "in",
            "url": "https://linkedin.com/company/qikoai",
        },
    ],
    "footer_links": [
        {"label": "About", "url": "https://qiko.ai/about"},
        {"label": "Blog", "url": "https://qiko.ai/blog"},
        {"label": "Support", "url": "https://qiko.ai/contact"},
        {"label": "Legal", "url": "https://qiko.ai/terms"},
        {"label": "Privacy", "url": "https://qiko.ai/privacy"},
    ],
    "company_address": "Qiko Signal Labs\n42 Orbit Avenue\nBucharest, Romania",
    "company_legal_name": "Qiko Signal Labs SRL",
    "company_trademark_text": "Qiko Signal is a trademark of Qiko Signal Labs SRL.",
}


def main() -> int:
    output_dir = BACKEND_PATH / "email_previews"
    output_dir.mkdir(exist_ok=True)

    failures: list[str] = []
    success_count = 0
    for key, definition in TEMPLATE_DEFINITIONS.items():
        try:
            light_rendered = render_template(key, dummy_context)
            light_name = f"{definition.html_template.replace('.html', '')}-light.html"
            (output_dir / light_name).write_text(light_rendered.html, encoding="utf-8")

            dark_rendered = render_template(key, {**dummy_context, "force_dark_mode": True})
            dark_name = f"{definition.html_template.replace('.html', '')}-dark.html"
            (output_dir / dark_name).write_text(dark_rendered.html, encoding="utf-8")
        except Exception as exc:
            print(f"FAIL {key}: {exc}")
            failures.append(key)
            continue

        if (
            RENDER_FAILURE_MARKER in light_rendered.html
            or RENDER_FAILURE_MARKER in dark_rendered.html
        ):
            print(f"FAIL {key}: template rendering fell back to the error body")
            failures.append(key)
            continue

        print(f"OK {key}: {light_name}, {dark_name}")
        success_count += 1

    print(f"\nGenerated {success_count} template preview pairs in {output_dir}")
    if failures:
        print(f"{len(failures)} template(s) failed: {', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
