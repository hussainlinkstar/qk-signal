import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.reports import pdf_service
from app.services.reports.pdf_service import WhiteLabelBranding, render_html_to_pdf


class DummyCSS:
    def __init__(self, string: str):
        self.string = string


class DummyHTML:
    def __init__(self, string: str, base_url: str | None = None):
        self.string = string
        self.base_url = base_url

    def write_pdf(self, stylesheets=None):
        _ = stylesheets
        return (
            b"%PDF-1.7\n"
            b"1 0 obj<</CreationDate (D:20260519101010Z) /ModDate (D:20260519101010Z)>>endobj\n"
            b"trailer<</ID [<abcdefabcdefabcdefabcdefabcdefab> <12345123451234512345123451234512>]>>\n"
            b"%%EOF"
        )


def test_render_html_to_pdf_applies_branding_and_returns_deterministic_pdf(monkeypatch):
    monkeypatch.setattr(pdf_service, "_load_weasyprint", lambda: (DummyCSS, DummyHTML))

    pdf = render_html_to_pdf(
        "<h2>Audit Results</h2><p>Body</p>",
        branding=WhiteLabelBranding(
            company_name="Acme Agency",
            logo_url="https://cdn.example.com/logo.png",
            primary_color="#112233",
            secondary_color="#334455",
            text_color="#223344",
        ),
    )

    assert pdf.startswith(b"%PDF")
    assert b"D:20260519101010Z" not in pdf
    assert b"D:20240101000000Z" in pdf
    assert b"abcdef" not in pdf
    assert b"00000000000000000000000000000000" in pdf


def test_render_html_to_pdf_raises_when_weasyprint_not_available(monkeypatch):
    monkeypatch.setattr(pdf_service, "_load_weasyprint", lambda: (None, None))

    try:
        render_html_to_pdf("<p>Hello</p>")
    except RuntimeError as exc:
        assert "WeasyPrint" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when WeasyPrint is unavailable")
