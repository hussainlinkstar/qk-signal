"""Command palette search endpoint (SIGV2-1020).

Two dynamic groups only: Projects and Reports. Static Pages, Settings and
Actions live in the frontend. Authorization is inside the query via the
resolved current workspace - a foreign or revoked object is
indistinguishable from a genuine miss (AC2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from routers.workspace_router import _get_or_create_current_workspace
from services.palette_search_service import (
    PALETTE_SEARCH_DEFAULT_PER_GROUP,
    PALETTE_SEARCH_MAX_PER_GROUP,
    PALETTE_SEARCH_MAX_QUERY_LENGTH,
    run_palette_search,
)

router = APIRouter(tags=["Search"])


class PaletteSearchResultItem(BaseModel):
    """One palette hit. ``destination`` is a first-party route that rechecks
    access when followed - never a signed URL or raw storage reference."""

    type: str = Field(..., description="Stable result type: project or report.")
    id: int
    label: str
    secondary: str = ""
    destination: str


class PaletteSearchGroups(BaseModel):
    projects: list[PaletteSearchResultItem] = Field(default_factory=list)
    reports: list[PaletteSearchResultItem] = Field(default_factory=list)


class PaletteSearchResponse(BaseModel):
    query: str
    groups: PaletteSearchGroups


@router.get("/search/palette", response_model=PaletteSearchResponse)
def palette_search(
    q: str | None = Query(default=None, max_length=PALETTE_SEARCH_MAX_QUERY_LENGTH),
    per_group: int = Query(
        default=PALETTE_SEARCH_DEFAULT_PER_GROUP,
        ge=1,
        le=PALETTE_SEARCH_MAX_PER_GROUP,
    ),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Resolution honours the X-Workspace-Id header / tenant context, so a
    # tenant switch changes the result set rather than serving stale scope.
    workspace = _get_or_create_current_workspace(db, user)
    return run_palette_search(
        db,
        workspace_id=workspace.id,
        raw_query=q,
        per_group=per_group,
    )
