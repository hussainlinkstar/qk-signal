from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from models import AnnotationVisibility


MAX_ANNOTATION_CONTENT_LENGTH = 5000


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_content(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Annotation content is required.")
    if len(normalized) > MAX_ANNOTATION_CONTENT_LENGTH:
        raise ValueError(
            f"Annotation content must be {MAX_ANNOTATION_CONTENT_LENGTH} characters or fewer."
        )
    return normalized


class AnnotationCreateRequest(BaseModel):
    section_path: str | None = Field(default=None, max_length=255)
    source_recommendation_key: str | None = Field(default=None, max_length=255)
    content: str = Field(..., min_length=1, max_length=MAX_ANNOTATION_CONTENT_LENGTH)
    visibility: AnnotationVisibility = AnnotationVisibility.INTERNAL
    parent_id: int | None = None

    @field_validator("section_path", "source_recommendation_key")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        return _normalize_content(value)


class AnnotationUpdateRequest(BaseModel):
    content: str | None = Field(default=None, max_length=MAX_ANNOTATION_CONTENT_LENGTH)
    visibility: AnnotationVisibility | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_content(value)


class AnnotationResponse(BaseModel):
    id: int
    audit_id: int
    project_id: int
    user_id: int | None
    user_display_name: str | None
    parent_id: int | None
    section_path: str | None
    source_recommendation_key: str | None
    content: str
    visibility: str
    is_deleted: bool
    created_at: str
    updated_at: str | None
    can_edit: bool = False
    can_delete: bool = False
    replies: list["AnnotationResponse"] = Field(default_factory=list)


class AnnotationThreadPageResponse(BaseModel):
    items: list[AnnotationResponse] = Field(default_factory=list)
    page: int
    per_page: int
    total: int
    has_more: bool


AnnotationResponse.model_rebuild()
