from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import quote
from database import get_db
from auth.security import get_current_user_from_token as get_current_user
from core.config import settings
from services.oauth_service import oauth
from services.jira_service import jira_service
from services.workspace_rbac import require_workspace_write_access, resolve_project_access
from app.services.compliance.plan_validator import PlanValidator
from app.schemas.jira_schema import (
    JiraConnectionStatus,
    JiraExportRequest,
    JiraExportResponse,
    JiraInitializeRequest,
    JiraProject,
)
import models

router = APIRouter(prefix="/integrations/jira", tags=["Jira Integration"])
logger = logging.getLogger(__name__)
plan_validator = PlanValidator()


def check_jira_access(user: models.User = Depends(get_current_user)):
    if not plan_validator.has_feature(user, "can_export_to_jira"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Jira Integration is a premium feature. Please upgrade to Specialist.",
        )
    return user


@router.get("/authorize", dependencies=[Depends(check_jira_access)])
async def jira_authorize(request: Request, user: models.User = Depends(get_current_user)):
    """Initiate Jira 3LO OAuth flow."""
    # Check if Jira OAuth is configured
    if not settings.JIRA_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Jira OAuth is not configured on the server. Please set JIRA_CLIENT_ID and JIRA_CLIENT_SECRET.",
        )

    # Build redirect URI
    callback_url = (
        str(settings.BACKEND_PUBLIC_URL or "http://localhost:8000")
        + "/api/v1/integrations/jira/callback"
    )

    # Store user_id in state to link connection upon return
    # In a real app, use a more secure state (session or signed token)
    state = json.dumps({"user_id": user.id})

    return await oauth.jira.authorize_redirect(request, callback_url, state=state)


@router.get("/callback")
async def jira_callback(request: Request, db: Session = Depends(get_db)):
    """Handle Jira 3LO OAuth callback."""
    if not settings.JIRA_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Jira OAuth is not configured on the server.",
        )

    try:
        token = await oauth.jira.authorize_access_token(request)
        state_raw = request.query_params.get("state")
        if not state_raw:
            raise HTTPException(status_code=400, detail="Missing state")

        state = json.loads(state_raw)
        user_id = state.get("user_id")

        # Determine workspace (for now, assume user's first owned workspace)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user or not user.owned_workspaces:
            raise HTTPException(status_code=404, detail="Workspace not found")

        workspace_id = user.owned_workspaces[0].id

        # Discover Cloud ID
        resources = await jira_service.get_accessible_resources(token["access_token"])
        if not resources:
            raise HTTPException(status_code=400, detail="No accessible Jira resources found")

        # Use the first accessible resource
        cloud_id = resources[0]["id"]

        # Save or update connection
        conn = (
            db.query(models.JiraConnection)
            .filter(models.JiraConnection.workspace_id == workspace_id)
            .first()
        )
        if not conn:
            conn = models.JiraConnection(workspace_id=workspace_id)
            db.add(conn)

        conn.access_token = token["access_token"]
        conn.refresh_token = token.get("refresh_token")
        if token.get("expires_at"):
            conn.expires_at = datetime.fromtimestamp(token["expires_at"])

        conn.cloud_id = cloud_id
        conn.site_name = resources[0].get("name")

        # Discover actual site URL (baseUrl) via serverInfo
        try:
            server_info = await jira_service.get_server_info(cloud_id, token["access_token"])
            conn.site_url = server_info.get("baseUrl", resources[0].get("url"))
            logger.info("Retrieved Jira baseUrl: %s", conn.site_url)
        except Exception as sie:
            logger.warning("Failed to fetch serverInfo for Jira resource: %s", str(sie))
            conn.site_url = resources[0].get("url")

        db.commit()

        # Redirect back to frontend connections page
        frontend_url = str(settings.FRONTEND_URL or "http://localhost:3000")
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/connections?provider=jira&status=connected"
        )

    except Exception as e:
        logger.error("Jira OAuth error: %s", str(e))
        frontend_url = str(settings.FRONTEND_URL or "http://localhost:3000")
        return RedirectResponse(
            url=f"{frontend_url}/dashboard/connections?provider=jira&status=error&message={quote(str(e))}"
        )


@router.get(
    "/status", response_model=JiraConnectionStatus, dependencies=[Depends(check_jira_access)]
)
async def get_jira_status(
    user: models.User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Check Jira connection status and list projects."""
    if not user.owned_workspaces:
        return JiraConnectionStatus(is_connected=False)

    workspace_id = user.owned_workspaces[0].id
    conn = (
        db.query(models.JiraConnection)
        .filter(models.JiraConnection.workspace_id == workspace_id)
        .first()
    )

    if not conn or not conn.access_token:
        return JiraConnectionStatus(is_connected=False)

    # Auto-refresh token if expired or expiring soon (5 min buffer)
    if conn.refresh_token and conn.expires_at:
        if datetime.now(conn.expires_at.tzinfo) > (conn.expires_at - timedelta(minutes=5)):
            try:
                new_token = await jira_service.refresh_access_token(conn.refresh_token)
                conn.access_token = new_token["access_token"]
                if "refresh_token" in new_token:
                    conn.refresh_token = new_token["refresh_token"]
                conn.expires_at = datetime.now(conn.expires_at.tzinfo) + timedelta(
                    seconds=new_token["expires_in"]
                )
                db.commit()
                logger.info("Successfully refreshed Jira token for workspace %s", workspace_id)
            except Exception as re:
                logger.error(
                    "Failed to refresh Jira token for workspace %s: %s", workspace_id, str(re)
                )
                # If refresh fails, we might still try with old token or just let it fail below
                pass

    # Auto-fix site_url if it's pointing to api.atlassian.com (Legacy fallback)
    if conn.site_url and "api.atlassian.com" in conn.site_url:
        try:
            server_info = await jira_service.get_server_info(conn.cloud_id, conn.access_token)
            new_url = server_info.get("baseUrl")
            if new_url and new_url != conn.site_url:
                conn.site_url = new_url
                db.commit()
                logger.info("Auto-fixed Jira site_url to: %s", new_url)
        except Exception as afe:
            logger.warning("Failed to auto-fix Jira site_url: %s", str(afe))

    # Fetch projects
    try:
        projects = await jira_service.get_projects(conn.cloud_id, conn.access_token)
        return JiraConnectionStatus(
            is_connected=True,
            cloud_id=conn.cloud_id,
            site_name=conn.site_name,
            site_url=conn.site_url,
            default_project=conn.default_jira_project_key,
            projects=projects,
        )
    except Exception as e:
        logger.error("Failed to fetch Jira projects for workspace %s: %s", workspace_id, str(e))
        return JiraConnectionStatus(
            is_connected=True,
            cloud_id=conn.cloud_id,
            site_name=conn.site_name,
            site_url=conn.site_url,
        )


@router.post(
    "/export", response_model=JiraExportResponse, dependencies=[Depends(check_jira_access)]
)
async def export_to_jira(
    payload: JiraExportRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a recommendation to Jira."""
    workspace_id = user.owned_workspaces[0].id
    conn = (
        db.query(models.JiraConnection)
        .filter(models.JiraConnection.workspace_id == workspace_id)
        .first()
    )

    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Jira not connected")

    browse_base_url = jira_service.normalize_browse_base_url(conn.site_url)
    if browse_base_url is None:
        try:
            server_info = await jira_service.get_server_info(conn.cloud_id, conn.access_token)
            resolved_site_url = jira_service.normalize_browse_base_url(server_info.get("baseUrl"))
            if resolved_site_url:
                conn.site_url = resolved_site_url
                db.commit()
                browse_base_url = resolved_site_url
        except Exception as exc:
            logger.warning(
                "Failed to refresh Jira browse base URL for workspace %s: %s", workspace_id, exc
            )

    try:
        return await jira_service.create_issue(
            cloud_id=conn.cloud_id,
            access_token=conn.access_token,
            project_key=payload.project_key,
            summary=payload.summary,
            description_md=payload.description,
            issue_type=payload.issue_type,
            site_url=browse_base_url,
        )
    except Exception as e:
        logger.error("Jira export error: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to export to Jira: {str(e)}")


@router.post("/initialize", response_model=JiraProject, dependencies=[Depends(check_jira_access)])
async def initialize_jira_project(
    payload: JiraInitializeRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a default Qiko Signal project in user's Jira."""
    access = resolve_project_access(db, user=user, project_id=payload.project_id)
    require_workspace_write_access(access.role)
    project = access.project
    conn = (
        db.query(models.JiraConnection)
        .filter(models.JiraConnection.workspace_id == access.workspace.id)
        .first()
    )

    if not conn or not conn.access_token:
        raise HTTPException(status_code=400, detail="Jira not connected")

    try:
        # 1. Get current Atlassian user accountId
        myself = await jira_service.get_myself(conn.cloud_id, conn.access_token)
        account_id = myself["accountId"]

        # 2. Derive project name and key
        # Jira keys must be uppercase alphanumeric, 2-10 chars.
        project_name = f"Qiko Signal - {project.name}"
        # Take first 3-4 chars of project name, or default to SYN
        clean_name = "".join(c for c in project.name if c.isalnum()).upper()
        proposed_key = f"SYN{clean_name[:7]}"[:10]
        if len(proposed_key) < 2:
            proposed_key = "SYNAI"

        # 3. Create the project
        new_project = await jira_service.create_project(
            cloud_id=conn.cloud_id,
            access_token=conn.access_token,
            name=project_name,
            key=proposed_key,
            lead_account_id=account_id,
        )

        # 4. (Optional) save as default
        conn.default_jira_project_key = new_project.key
        db.commit()

        return new_project
    except Exception as e:
        logger.error("Jira project initialization failed for project %s: %s", project.id, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to initialize Jira project: {str(e)}")
