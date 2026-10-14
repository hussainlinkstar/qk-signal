from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse


TITLE_MIN_LENGTH = 30
TITLE_MAX_LENGTH = 60
THIN_CONTENT_MIN_WORDS = 300
BROKEN_LINK_TIMEOUT_SECONDS = 5


class _OnPageHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_texts: list[str] = []
        self.h1_texts: list[str] = []
        self.links: list[str] = []
        self._text_parts: list[str] = []

        self._inside_title = False
        self._inside_h1 = False
        self._ignored_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower_tag = tag.lower()

        if lower_tag == "title":
            self._inside_title = True
            self.title_texts.append("")

        if lower_tag == "h1":
            self._inside_h1 = True
            self.h1_texts.append("")

        if lower_tag == "a":
            attrs_dict = {name.lower(): value for name, value in attrs}
            href = attrs_dict.get("href")
            if href:
                self.links.append(href.strip())

        if lower_tag in {"script", "style", "noscript", "svg", "template"}:
            self._ignored_stack.append(lower_tag)

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()

        if lower_tag == "title":
            self._inside_title = False

        if lower_tag == "h1":
            self._inside_h1 = False

        if lower_tag in {"script", "style", "noscript", "svg", "template"} and self._ignored_stack:
            self._ignored_stack.pop()

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return

        if self._inside_title and self.title_texts:
            self.title_texts[-1] = (self.title_texts[-1] + " " + text).strip()

        if self._inside_h1 and self.h1_texts:
            self.h1_texts[-1] = (self.h1_texts[-1] + " " + text).strip()

        if not self._ignored_stack:
            self._text_parts.append(text)

    @property
    def body_text(self) -> str:
        return " ".join(self._text_parts)


def _build_issue(
    issue_id: str,
    severity: str,
    problem: str,
    why_it_matters: str,
    fix_instruction: str,
) -> dict[str, str]:
    return {
        "id": issue_id,
        "severity": severity,
        "problem": problem,
        "why_it_matters": why_it_matters,
        "fix_instruction": fix_instruction,
    }


def _is_internal_link(href: str, page_url: str) -> bool:
    parsed_page = urlparse(page_url)
    normalized_href = href.strip()

    if not normalized_href:
        return False

    if normalized_href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False

    parsed_link = urlparse(urljoin(page_url, normalized_href))

    if parsed_link.scheme not in {"http", "https"}:
        return False

    return parsed_link.netloc == parsed_page.netloc


def _is_broken_link(url: str) -> bool:
    from services.url_validation import SSRFBlockedError, safe_sync_fetch

    try:
        response = safe_sync_fetch(url, method="HEAD", timeout=BROKEN_LINK_TIMEOUT_SECONDS)
        if response.status_code == 405:
            response = safe_sync_fetch(url, method="GET", timeout=BROKEN_LINK_TIMEOUT_SECONDS)
        return response.status_code >= 400
    except SSRFBlockedError:
        return True
    except Exception:
        return True


def analyze_onpage_seo(raw_html: str, page_url: str) -> list[dict[str, Any]]:
    parser = _OnPageHTMLParser()
    parser.feed(raw_html or "")

    issues: list[dict[str, Any]] = []

    title_count = len(parser.title_texts)
    first_title = parser.title_texts[0].strip() if parser.title_texts else ""

    if title_count > 1:
        issues.append(
            _build_issue(
                issue_id="duplicate_title_tags",
                severity="high",
                problem=f"Page has {title_count} <title> tags.",
                why_it_matters="Multiple title tags can confuse search engines about which title should be indexed.",
                fix_instruction="Keep exactly one descriptive <title> tag in the <head> section.",
            )
        )

    if not first_title:
        issues.append(
            _build_issue(
                issue_id="missing_title",
                severity="high",
                problem="Page is missing a <title> tag.",
                why_it_matters="The title tag is a primary on-page relevance signal and is often used as the search result headline.",
                fix_instruction="Add one unique <title> tag that clearly describes the page topic.",
            )
        )
    elif not TITLE_MIN_LENGTH <= len(first_title) <= TITLE_MAX_LENGTH:
        issues.append(
            _build_issue(
                issue_id="title_length_violation",
                severity="medium",
                problem=(
                    f"Title length is {len(first_title)} characters; recommended range is "
                    f"{TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH}."
                ),
                why_it_matters="Titles that are too short may miss context, while long titles are more likely to be truncated in search results.",
                fix_instruction=(
                    "Rewrite the title to be specific and compelling while staying within "
                    f"{TITLE_MIN_LENGTH}-{TITLE_MAX_LENGTH} characters."
                ),
            )
        )

    h1_count = len([h1 for h1 in parser.h1_texts if h1.strip()])
    if h1_count == 0:
        issues.append(
            _build_issue(
                issue_id="missing_h1",
                severity="high",
                problem="Page is missing an <h1> heading.",
                why_it_matters="An <h1> helps search engines and users quickly understand the primary topic of the page.",
                fix_instruction="Add one clear, descriptive <h1> heading near the top of the main content.",
            )
        )
    elif h1_count > 1:
        issues.append(
            _build_issue(
                issue_id="multiple_h1",
                severity="medium",
                problem=f"Page has {h1_count} <h1> headings.",
                why_it_matters="Multiple top-level headings can dilute topical focus and reduce heading hierarchy clarity.",
                fix_instruction="Use a single primary <h1> and demote additional section headings to <h2>/<h3>.",
            )
        )

    word_count = len(parser.body_text.split())
    if word_count < THIN_CONTENT_MIN_WORDS:
        issues.append(
            _build_issue(
                issue_id="thin_content",
                severity="medium",
                problem=(
                    f"Page has approximately {word_count} words of indexable text, below "
                    f"the {THIN_CONTENT_MIN_WORDS}-word threshold."
                ),
                why_it_matters="Thin pages often provide limited value and may struggle to rank for competitive queries.",
                fix_instruction="Expand the main content with helpful, original information that fully addresses user intent.",
            )
        )

    broken_internal_links: list[str] = []
    seen: set[str] = set()
    for href in parser.links:
        if not _is_internal_link(href, page_url):
            continue

        absolute_url = urljoin(page_url, href)
        if absolute_url in seen:
            continue

        seen.add(absolute_url)
        if _is_broken_link(absolute_url):
            broken_internal_links.append(absolute_url)

    if broken_internal_links:
        sample_links = ", ".join(broken_internal_links[:5])
        issues.append(
            _build_issue(
                issue_id="broken_internal_links",
                severity="high",
                problem=(
                    f"Detected {len(broken_internal_links)} broken internal link(s). "
                    f"Example(s): {sample_links}."
                ),
                why_it_matters="Broken internal links waste crawl budget, hurt user experience, and weaken internal linking signals.",
                fix_instruction="Update or remove broken links and ensure internal URLs return a valid 2xx/3xx response.",
            )
        )

    return issues
