from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

import models
from services.audit_search_metrics import load_project_search_metrics

PROJECT_SOURCE_PROVIDER_MAP: dict[models.ProjectDataSourceType, models.OAuthProvider] = {
    models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE: models.OAuthProvider.GOOGLE,
    models.ProjectDataSourceType.GOOGLE_ANALYTICS_4: models.OAuthProvider.GOOGLE,
    models.ProjectDataSourceType.BING_WEBMASTER: models.OAuthProvider.BING,
}

ORDERED_SOURCE_TYPES: tuple[models.ProjectDataSourceType, ...] = (
    models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
    models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
    models.ProjectDataSourceType.BING_WEBMASTER,
)


def _binding_mode_value(mode: models.ProjectDataSourceBindingMode | str | None) -> str | None:
    if mode is None:
        return None
    if isinstance(mode, models.ProjectDataSourceBindingMode):
        return mode.value
    return str(mode)


def _source_type_value(source_type: models.ProjectDataSourceType | str) -> str:
    if isinstance(source_type, models.ProjectDataSourceType):
        return source_type.value
    return str(source_type)


def _provider_value(provider: models.OAuthProvider | str) -> str:
    if isinstance(provider, models.OAuthProvider):
        return provider.value
    return str(provider)


def _connection_available(
    connection: models.OAuthConnection | models.ProjectOAuthConnection | None,
) -> bool:
    return connection is not None


def _source_is_active(row: models.ProjectDataSource | None) -> bool:
    return bool(row and row.is_active)


def _has_mapped_source(row: models.ProjectDataSource | None) -> bool:
    if row is None:
        return False
    source_id = str(row.source_id or "").strip()
    source_label = str(row.source_label or "").strip()
    return bool(source_id or source_label)


def _preferred_binding_mode(
    *,
    provider: models.OAuthProvider,
    workspace_connection: models.OAuthConnection | None,
    project_connection: models.ProjectOAuthConnection | None,
) -> models.ProjectDataSourceBindingMode:
    if _connection_available(project_connection):
        return models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK
    if _connection_available(workspace_connection):
        return models.ProjectDataSourceBindingMode.WORKSPACE
    return models.ProjectDataSourceBindingMode.AI_ESTIMATE


def _resolve_requested_mode(
    row: models.ProjectDataSource | None,
) -> models.ProjectDataSourceBindingMode | None:
    if row is None:
        return None
    if isinstance(row.binding_mode, models.ProjectDataSourceBindingMode):
        return row.binding_mode
    raw = _binding_mode_value(row.binding_mode)
    if not raw:
        return None
    try:
        return models.ProjectDataSourceBindingMode(raw)
    except ValueError:
        return None


def resolve_project_audit_data_sources(
    db: Session,
    *,
    project_id: int,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        warnings.append("Project context is unavailable; running audit in AI Estimates Only mode.")
        return {
            "project_id": project_id,
            "workspace_id": None,
            "mode": "ai_estimate_only",
            "has_external_data": False,
            "fallback_applied": True,
            "provider_modes": {},
            "sources": [],
            "search_metrics": {},
            "project_profile": {},
        }, warnings

    data_source_rows = (
        db.query(models.ProjectDataSource)
        .filter(models.ProjectDataSource.project_id == project.id)
        .all()
    )
    rows_by_source_type: dict[models.ProjectDataSourceType, models.ProjectDataSource] = {}
    for row in data_source_rows:
        if isinstance(row.source_type, models.ProjectDataSourceType):
            rows_by_source_type[row.source_type] = row

    workspace_connections = (
        db.query(models.OAuthConnection)
        .filter(models.OAuthConnection.workspace_id == project.workspace_id)
        .all()
    )
    workspace_by_provider: dict[models.OAuthProvider, models.OAuthConnection] = {}
    for row in workspace_connections:
        if isinstance(row.provider, models.OAuthProvider):
            workspace_by_provider[row.provider] = row

    project_connections = (
        db.query(models.ProjectOAuthConnection)
        .filter(models.ProjectOAuthConnection.project_id == project.id)
        .all()
    )
    project_by_provider: dict[models.OAuthProvider, models.ProjectOAuthConnection] = {}
    for row in project_connections:
        if isinstance(row.provider, models.OAuthProvider):
            project_by_provider[row.provider] = row

    sources: list[dict[str, Any]] = []
    fallback_applied = False

    for source_type in ORDERED_SOURCE_TYPES:
        provider = PROJECT_SOURCE_PROVIDER_MAP[source_type]
        row = rows_by_source_type.get(source_type)
        requested_mode = _resolve_requested_mode(row)
        workspace_connection = workspace_by_provider.get(provider)
        project_connection = project_by_provider.get(provider)
        preferred_mode = _preferred_binding_mode(
            provider=provider,
            workspace_connection=workspace_connection,
            project_connection=project_connection,
        )

        resolved_mode = preferred_mode
        if requested_mode == models.ProjectDataSourceBindingMode.AI_ESTIMATE:
            resolved_mode = models.ProjectDataSourceBindingMode.AI_ESTIMATE
        elif (
            requested_mode is not None
            and preferred_mode == models.ProjectDataSourceBindingMode.WORKSPACE
        ):
            if requested_mode == models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK:
                resolved_mode = models.ProjectDataSourceBindingMode.WORKSPACE
            else:
                resolved_mode = requested_mode
        elif (
            requested_mode is not None
            and preferred_mode == models.ProjectDataSourceBindingMode.AI_ESTIMATE
        ):
            resolved_mode = models.ProjectDataSourceBindingMode.AI_ESTIMATE

        fallback_reason = None
        if (
            requested_mode is not None
            and requested_mode != models.ProjectDataSourceBindingMode.AI_ESTIMATE
            and resolved_mode != requested_mode
        ):
            fallback_applied = True
            fallback_reason = (
                f"{_source_type_value(source_type)} requested "
                f"{requested_mode.value} but resolved {resolved_mode.value}."
            )
            warnings.append(fallback_reason)

        source_metadata = row.metadata_json if row and isinstance(row.metadata_json, dict) else {}
        has_external_data = (
            resolved_mode != models.ProjectDataSourceBindingMode.AI_ESTIMATE
            and _source_is_active(row)
            and _has_mapped_source(row)
        )
        effective_mode = (
            resolved_mode if has_external_data else models.ProjectDataSourceBindingMode.AI_ESTIMATE
        )
        sources.append(
            {
                "source_type": _source_type_value(source_type),
                "provider": _provider_value(provider),
                "is_active": _source_is_active(row),
                "requested_binding_mode": _binding_mode_value(requested_mode),
                "resolved_binding_mode": resolved_mode.value,
                "effective_binding_mode": effective_mode.value,
                "workspace_connection_available": _connection_available(workspace_connection),
                "project_connection_available": _connection_available(project_connection),
                "source_id": (row.source_id if row and has_external_data else None),
                "source_label": (row.source_label if row and has_external_data else None),
                "project_data_source_id": (row.id if row else None),
                "oauth_connection_id": (
                    row.oauth_connection_id
                    if row and resolved_mode == models.ProjectDataSourceBindingMode.WORKSPACE
                    else None
                ),
                "project_oauth_connection_id": (
                    row.project_oauth_connection_id
                    if row
                    and resolved_mode == models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK
                    else None
                ),
                "has_external_data": has_external_data,
                "fallback_reason": fallback_reason,
                "metadata": source_metadata,
            }
        )

    resolved_modes = {
        str(entry["effective_binding_mode"])
        for entry in sources
        if isinstance(entry.get("effective_binding_mode"), str)
    }
    has_external_data = any(bool(entry.get("has_external_data")) for entry in sources)
    if not resolved_modes or resolved_modes == {
        models.ProjectDataSourceBindingMode.AI_ESTIMATE.value
    }:
        mode = "ai_estimate_only"
    elif len(resolved_modes) == 1:
        mode = next(iter(resolved_modes))
    else:
        mode = "mixed"

    if not has_external_data:
        warnings.append("No connected data sources found. Running in AI Estimates Only mode.")

    provider_modes: dict[str, str] = {}
    for provider in models.OAuthProvider:
        provider_modes[provider.value] = _preferred_binding_mode(
            provider=provider,
            workspace_connection=workspace_by_provider.get(provider),
            project_connection=project_by_provider.get(provider),
        ).value

    context: dict[str, Any] = {
        "project_id": project.id,
        "workspace_id": project.workspace_id,
        "mode": mode,
        "has_external_data": has_external_data,
        "fallback_applied": fallback_applied,
        "provider_modes": provider_modes,
        "sources": sources,
        # What the connected sources actually measured, not just that they are
        # connected (SIGV2-1265). Read from storage, never from a provider API.
        "search_metrics": load_project_search_metrics(db, project_id=project.id),
        "project_profile": {
            "name": project.name,
            "domain_url": project.domain_url,
            "target_country": project.target_country,
            "language": project.language,
            "icp_roles": list(project.icp_roles or []),
            "pain_points": project.pain_points,
            "usp": project.usp,
            "competitors": list(project.competitors_json or []),
            "priority_pulse_tags": list(project.priority_pulse_tags or []),
            "sme_profiles": list(project.sme_profiles or []),
        },
    }
    return context, warnings
