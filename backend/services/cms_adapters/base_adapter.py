from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from html import escape

SUPPORTED_CMS_FIELDS = {
    "head_scripts",
    "meta_title",
    "meta_description",
    "alt_text",
}


@dataclass(frozen=True)
class CMSChangePreview:
    page_url: str
    field: str
    current_value: str | None
    proposed_value: str
    diff_html: str


@dataclass(frozen=True)
class CMSPushResult:
    success: bool
    page_url: str
    revision_id: str | None
    error_message: str | None


class CMSAdapter(ABC):
    @abstractmethod
    async def test_connection(self) -> bool:
        """Return whether the CMS credentials are valid and usable."""

    @abstractmethod
    async def preview_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
    ) -> CMSChangePreview:
        """Return the current/proposed values and an HTML diff preview."""

    @abstractmethod
    async def push_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
        approved_by: int,
    ) -> CMSPushResult:
        """Apply a change directly into the target CMS."""

    @abstractmethod
    async def rollback_change(self, *, revision_id: str) -> bool:
        """Attempt a native CMS rollback by revision identifier."""


def build_diff_html(current_value: str | None, proposed_value: str) -> str:
    before = escape(current_value or "")
    after = escape(proposed_value)
    return (
        "<section class='cms-diff'>"
        "<div class='cms-diff__column cms-diff__column--before'>"
        "<h4>Current</h4>"
        f"<pre>{before or '<empty>'}</pre>"
        "</div>"
        "<div class='cms-diff__column cms-diff__column--after'>"
        "<h4>Proposed</h4>"
        f"<pre>{after or '<empty>'}</pre>"
        "</div>"
        "</section>"
    )


def validate_supported_field(field: str) -> str:
    normalized = str(field or "").strip().lower()
    if normalized not in SUPPORTED_CMS_FIELDS:
        supported = ", ".join(sorted(SUPPORTED_CMS_FIELDS))
        raise ValueError(f"Unsupported CMS field '{field}'. Supported: {supported}.")
    return normalized
