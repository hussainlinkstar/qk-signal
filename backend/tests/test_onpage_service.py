import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.seo.onpage_service import analyze_onpage_seo


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_analyze_onpage_seo_detects_required_issues(monkeypatch):
    html = (
        """
    <html>
      <head>
        <title>Short</title>
        <title>Duplicate</title>
      </head>
      <body>
        <h1>Main Heading</h1>
        <h1>Another Heading</h1>
        <p>"""
        + "word " * 20
        + """</p>
        <a href="/ok">ok</a>
        <a href="/broken">broken</a>
      </body>
    </html>
    """
    )

    def fake_fetch(url, *, method="GET", timeout=5, **kwargs):
        if url.endswith("/broken"):
            return _Response(404)
        return _Response(200)

    monkeypatch.setattr("services.url_validation.safe_sync_fetch", fake_fetch)

    issues = analyze_onpage_seo(html, "https://example.com/page")

    ids = {issue["id"] for issue in issues}
    assert "duplicate_title_tags" in ids
    assert "title_length_violation" in ids
    assert "multiple_h1" in ids
    assert "thin_content" in ids
    assert "broken_internal_links" in ids


def test_analyze_onpage_seo_missing_h1_and_title(monkeypatch):
    html = "<html><body><p>" + ("word " * 350) + "</p></body></html>"

    def fake_fetch(url, *, method="GET", timeout=5, **kwargs):
        return _Response(200)

    monkeypatch.setattr("services.url_validation.safe_sync_fetch", fake_fetch)

    issues = analyze_onpage_seo(html, "https://example.com/page")

    ids = {issue["id"] for issue in issues}
    assert "missing_title" in ids
    assert "missing_h1" in ids
    assert "thin_content" not in ids
