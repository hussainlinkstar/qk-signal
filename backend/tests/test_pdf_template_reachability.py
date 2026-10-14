"""SIGV2-1277: every file under services/pdf_reports/templates must be
reachable from the two live entry templates (white_label.html, battle.html)
or be a named runtime resource. Orphaned templates look authoritative, pass
review, and change nothing in the output - the trap this guards against.

Static analysis only: parse {% include %}, {% extends %}, {% import %} and
{% from ... import %} statements; no Jinja environment needed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "services" / "pdf_reports" / "templates"

# The only templates the renderer ever loads by name.
ENTRY_TEMPLATES = {"white_label.html", "battle.html"}
# Loaded programmatically by renderer._build_stylesheet(), not via include.
RUNTIME_RESOURCES = {"report.css.j2"}

_REFERENCE_RE = re.compile(r"""{%\s*(?:include|extends|import|from)\s+['"]([^'"]+)['"]""")


def _referenced_templates(path: Path) -> set[str]:
    return set(_REFERENCE_RE.findall(path.read_text(encoding="utf-8")))


def test_every_template_file_is_reachable_from_a_live_entry():
    reachable: set[str] = set(ENTRY_TEMPLATES)
    frontier = list(ENTRY_TEMPLATES)
    while frontier:
        current = frontier.pop()
        for reference in _referenced_templates(TEMPLATE_DIR / current):
            if reference not in reachable:
                reachable.add(reference)
                candidate = TEMPLATE_DIR / reference
                assert candidate.exists(), f"{current} references missing template {reference!r}"
                frontier.append(reference)

    on_disk = {
        str(path.relative_to(TEMPLATE_DIR)) for path in TEMPLATE_DIR.rglob("*") if path.is_file()
    }

    orphans = on_disk - reachable - RUNTIME_RESOURCES
    assert not orphans, (
        "Template files not reachable from white_label.html or battle.html "
        f"(SIGV2-1277): {sorted(orphans)}"
    )
