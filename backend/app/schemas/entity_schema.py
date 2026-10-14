from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SiteMapEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    normalized_key: str
    frequency: int
    avg_relevance_score: float
    category: str


class SiteMapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_id: int
    audit_count: int
    last_seen_at: str | None = None
    entities: list[SiteMapEntity]
