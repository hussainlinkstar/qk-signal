from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class JiraProject(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    id: str


class JiraTokenExchange(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_in: int
    scope: str


class JiraExportRequest(BaseModel):
    project_key: str
    summary: str
    description: str  # Markdown text that will be converted to ADF
    issue_type: str = "Task"
    priority: Optional[str] = None


class JiraInitializeRequest(BaseModel):
    project_id: int


class JiraExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    issue_id: str
    issue_key: str
    issue_url: str


class JiraConnectionStatus(BaseModel):
    is_connected: bool
    cloud_id: Optional[str] = None
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    default_project: Optional[str] = None
    projects: List[JiraProject] = Field(default_factory=list)
