# pyre-unsafe
"""AEX-07: Tests for content format detection (HTML vs Markdown).

Verifies that:
- Content format detection correctly identifies HTML vs markdown
- Markdown headings, tables, images, and lists are detected and scored
- HTML content continues to work identically
- Mixed content is handled gracefully
- Empty content is handled gracefully
"""

from score_utils import DeterministicScoringEngine

Engine = DeterministicScoringEngine


# ================================================================== #
#  1. Content format detection
# ================================================================== #


class TestContentFormatDetection:
    """Tests for _detect_content_format."""

    def test_html_with_div(self):
        assert Engine._detect_content_format("<div>Hello</div>") == "html"

    def test_html_with_p(self):
        assert Engine._detect_content_format("<p>Paragraph</p>") == "html"

    def test_html_with_h2(self):
        assert Engine._detect_content_format("<h2>Title</h2>") == "html"

    def test_html_with_table(self):
        assert Engine._detect_content_format("<table><tr><td>1</td></tr></table>") == "html"

    def test_markdown_headings(self):
        assert Engine._detect_content_format("## Heading Two\n\nSome text.") == "markdown"

    def test_markdown_lists(self):
        assert Engine._detect_content_format("- item 1\n- item 2\n- item 3") == "markdown"

    def test_markdown_mixed_content(self):
        assert (
            Engine._detect_content_format("# Title\n\nSome **bold** text.\n\n- list item")
            == "markdown"
        )

    def test_empty_content(self):
        assert Engine._detect_content_format("") == "html"

    def test_plain_text(self):
        assert (
            Engine._detect_content_format("Just some plain text without any markup.") == "markdown"
        )


# ================================================================== #
#  2. Dual-format helpers
# ================================================================== #


class TestDualFormatHelpers:
    """Tests for individual format-aware helper methods."""

    # Headings
    def test_h2_html(self):
        assert Engine._has_headings_h2("<h2>Section</h2>", "html") is True

    def test_h2_markdown(self):
        assert Engine._has_headings_h2("## Section Title", "markdown") is True

    def test_h2_markdown_no_match(self):
        assert Engine._has_headings_h2("### Not H2", "markdown") is False

    def test_h3_html(self):
        assert Engine._has_headings_h3("<h3>Subsection</h3>", "html") is True

    def test_h3_markdown(self):
        assert Engine._has_headings_h3("### Subsection Title", "markdown") is True

    # Images
    def test_images_html(self):
        content = '<img src="photo.jpg" alt="Photo"><img src="logo.png">'
        total, with_alt = Engine._count_image_alt_ratio(content, "html")
        assert total == 2
        assert with_alt == 1

    def test_images_markdown(self):
        content = "![Photo of office](photo.jpg)\n![](logo.png)\n![Logo](logo.svg)"
        total, with_alt = Engine._count_image_alt_ratio(content, "markdown")
        assert total == 3
        assert with_alt == 2  # "Photo of office" and "Logo" have alt text

    def test_images_markdown_none(self):
        total, _ = Engine._count_image_alt_ratio("No images here.", "markdown")
        assert total == 0

    # Lists
    def test_has_lists_html(self):
        assert Engine._has_lists("<ul><li>Item</li></ul>", "html") is True

    def test_has_lists_markdown_unordered(self):
        assert Engine._has_lists("- item 1\n- item 2", "markdown") is True

    def test_has_lists_markdown_ordered(self):
        assert Engine._has_lists("1. first\n2. second", "markdown") is True

    def test_has_lists_markdown_star(self):
        assert Engine._has_lists("* item 1\n* item 2", "markdown") is True

    def test_count_lists_html(self):
        content = "<ul><li>A</li></ul><ol><li>1</li></ol><ul><li>B</li></ul>"
        assert Engine._count_lists(content, "html") == 3

    def test_count_lists_markdown(self):
        content = "- a\n- b\n- c\n\n1. one\n2. two\n3. three\n\n- x\n- y\n- z"
        count = Engine._count_lists(content, "markdown")
        assert count >= 1  # At least detects some lists

    # Tables
    def test_has_tables_html(self):
        assert Engine._has_tables("<table><tr><td>1</td></tr></table>", "html") is True

    def test_has_tables_markdown(self):
        content = "| Col1 | Col2 |\n|------|------|\n| A | B |"
        assert Engine._has_tables(content, "markdown") is True

    def test_count_tables_html(self):
        content = "<table><tr></tr></table><table><tr></tr></table>"
        assert Engine._count_tables(content, "html") == 2

    def test_count_tables_markdown(self):
        content = "| A | B |\n|---|---|\n| 1 | 2 |\n\n| X | Y |\n|---|---|\n| 3 | 4 |"
        assert Engine._count_tables(content, "markdown") == 2

    # Definition markup
    def test_definition_html(self):
        assert Engine._has_definition_markup("<dl><dt>Term</dt><dd>Def</dd></dl>", "html") is True

    def test_definition_markdown(self):
        content = "Term\n: Definition of the term"
        assert Engine._has_definition_markup(content, "markdown") is True

    # Q&A patterns
    def test_qa_html(self):
        content = "<h2>What is SEO?</h2><p>SEO stands for search engine optimization and is a marketing discipline.</p>"
        count = Engine._count_qa_patterns(content, "html")
        assert count >= 1

    def test_qa_markdown(self):
        content = "## What is SEO?\nSEO stands for search engine optimization and is a discipline that helps websites rank higher."
        count = Engine._count_qa_patterns(content, "markdown")
        assert count >= 1

    # Paragraphs
    def test_paragraphs_html(self):
        content = (
            "<p>This is a short paragraph with some words in it.</p><p>Another paragraph here.</p>"
        )
        paras = Engine._extract_paragraphs(content, "html")
        assert len(paras) == 2

    def test_paragraphs_markdown(self):
        content = (
            "This is a paragraph with some words.\n\nAnother separate paragraph here with content."
        )
        paras = Engine._extract_paragraphs(content, "markdown")
        assert len(paras) == 2

    def test_paragraphs_markdown_skips_headings(self):
        content = "# Heading\n\nThis is a paragraph.\n\n## Another heading\n\nAnother paragraph."
        paras = Engine._extract_paragraphs(content, "markdown")
        assert len(paras) == 2  # Only paragraphs, not headings


# ================================================================== #
#  3. On-Page Content scoring with markdown
# ================================================================== #


class TestOnPageContentMarkdown:
    """Verify that markdown content gets scored for on-page content signals."""

    def test_markdown_headings_score_points(self):
        """Markdown ## and ### should earn heading hierarchy points."""
        md_content = "## Section One\n\n### Subsection\n\nSome text here."
        score_md = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            md_content,
            [],
            [],
        )
        # No headings at all
        score_plain = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            "Just plain text here.",
            [],
            [],
        )
        assert score_md > score_plain

    def test_markdown_images_score_points(self):
        """Markdown images with alt text should earn alt-text points."""
        md_content = "![Descriptive alt](image.jpg)\n\n" * 5
        bonuses = []
        Engine._calculate_onpage_content_score(
            {"title": "Test"},
            md_content,
            [],
            bonuses,
        )
        assert any("alt-text" in b.get("reason", "").lower() for b in bonuses)

    def test_markdown_lists_score_points(self):
        """Markdown lists should earn structured content points."""
        md_content = "# Title\n\n- item 1\n- item 2\n- item 3"
        score_md = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            md_content,
            [],
            [],
        )
        score_plain = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            "Just plain text here.",
            [],
            [],
        )
        assert score_md >= score_plain

    def test_markdown_tables_score_points(self):
        """Markdown tables should earn structured content points."""
        md_content = "# Title\n\n| Col1 | Col2 |\n|------|------|\n| A | B |"
        score_md = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            md_content,
            [],
            [],
        )
        score_plain = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            "Just plain text here.",
            [],
            [],
        )
        assert score_md >= score_plain

    def test_html_content_still_works(self):
        """HTML content should continue to work identically."""
        html_content = (
            '<h2>Section</h2><h3>Sub</h3><img src="x.jpg" alt="desc"><ul><li>Item</li></ul>'
        )
        bonuses = []
        score = Engine._calculate_onpage_content_score(
            {"title": "Test", "headings": ["H1"]},
            html_content,
            [],
            bonuses,
        )
        assert score > 0


# ================================================================== #
#  4. Snippet Formatting scoring with markdown
# ================================================================== #


class TestSnippetFormattingMarkdown:
    """Verify that markdown content gets scored for snippet formatting signals."""

    def test_markdown_tables_detected(self):
        """Markdown tables should be counted for snippet formatting."""
        md_content = "| Feature | Status |\n|---------|--------|\n| Auth | Done |\n\n| Q | A |\n|---|---|\n| Why | Because |"
        bonuses = []
        score = Engine._calculate_snippet_formatting_score(md_content, [], bonuses)
        assert any("table" in b.get("reason", "").lower() for b in bonuses)
        assert score > 0

    def test_markdown_lists_detected(self):
        """Markdown lists should be counted for snippet formatting."""
        md_content = (
            "- item 1\n- item 2\n- item 3\n\n1. first\n2. second\n3. third\n\n- a\n- b\n- c"
        )
        bonuses = []
        Engine._calculate_snippet_formatting_score(md_content, [], bonuses)
        assert any("list" in b.get("reason", "").lower() for b in bonuses)

    def test_markdown_qa_detected(self):
        """Markdown Q&A patterns should be detected."""
        md_content = (
            "## What is SEO?\nSEO is the practice of optimizing websites to rank higher in search engines.\n\n"
            "## How does GEO work?\nGEO focuses on geographic optimization for local search visibility in your area.\n\n"
            "## Why is AEO important?\nAEO ensures your content is optimized for AI-powered answer engines and chatbots.\n\n"
        )
        bonuses = []
        Engine._calculate_snippet_formatting_score(md_content, [], bonuses)
        assert any("q&a" in b.get("reason", "").lower() for b in bonuses)

    def test_markdown_concise_paragraphs_detected(self):
        """Markdown paragraphs should be extracted and checked for conciseness."""
        paragraphs = [
            "This is a well-crafted paragraph with about twenty words that serves as an effective answer for readers."
        ] * 6
        md_content = "\n\n".join(paragraphs)
        bonuses = []
        Engine._calculate_snippet_formatting_score(md_content, [], bonuses)
        assert any("concise" in b.get("reason", "").lower() for b in bonuses)

    def test_markdown_summary_pattern_detected(self):
        """Summary/TL;DR should be detected in markdown."""
        md_content = "## Summary\n\nThis is a brief summary of the key points."
        bonuses = []
        Engine._calculate_snippet_formatting_score(md_content, [], bonuses)
        assert any("summary" in b.get("reason", "").lower() for b in bonuses)

    def test_html_snippet_formatting_still_works(self):
        """HTML content should continue to work for snippet formatting."""
        html_content = (
            "<h2>What is SEO?</h2><p>SEO is the practice of optimizing websites to rank well in engines.</p>"
            "<table><tr><td>Feature</td></tr></table>"
            "<ul><li>Item 1</li></ul>"
        )
        bonuses = []
        score = Engine._calculate_snippet_formatting_score(html_content, [], bonuses)
        assert score > 0

    def test_empty_content_no_crash(self):
        """Empty content should not crash."""
        score = Engine._calculate_snippet_formatting_score("", [], [])
        assert score == 0.0


# ================================================================== #
#  5. Equivalence: HTML vs Markdown for same content
# ================================================================== #


class TestHTMLMarkdownEquivalence:
    """Verify that equivalent HTML and markdown produce comparable scores."""

    def test_headings_equivalent(self):
        """H2 detection should work in both formats."""
        html = "<h2>Section</h2>"
        md = "## Section"
        assert Engine._has_headings_h2(html, "html") is True
        assert Engine._has_headings_h2(md, "markdown") is True

    def test_tables_equivalent(self):
        """Table detection should work in both formats."""
        html = "<table><tr><td>A</td></tr></table>"
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        assert Engine._has_tables(html, "html") is True
        assert Engine._has_tables(md, "markdown") is True

    def test_lists_equivalent(self):
        """List detection should work in both formats."""
        html = "<ul><li>Item</li></ul>"
        md = "- Item"
        assert Engine._has_lists(html, "html") is True
        assert Engine._has_lists(md, "markdown") is True

    def test_images_equivalent(self):
        """Image detection should work in both formats."""
        html = '<img src="test.jpg" alt="Test image">'
        md = "![Test image](test.jpg)"
        html_total, html_alt = Engine._count_image_alt_ratio(html, "html")
        md_total, md_alt = Engine._count_image_alt_ratio(md, "markdown")
        assert html_total == 1
        assert md_total == 1
        assert html_alt == 1
        assert md_alt == 1
