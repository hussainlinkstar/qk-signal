from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature
from auth.security import get_current_user_from_token as get_current_user
from core.config import settings
from database import get_db
from services.audit_helpers import resolve_subscription_plan as _resolve_subscription_plan
from services.portal_service import resolve_workspace_owner_plan
from services.s3_storage_service import get_storage_service
from services.workspace_rbac import require_not_portal_only

router = APIRouter(prefix="/uploads", tags=["Uploads"])

MAX_LOGO_FILE_SIZE_BYTES = 2 * 1024 * 1024
ALLOWED_LOGO_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class LogoUploadResponse(BaseModel):
    url: str
    object_uri: str
    filename: str
    content_type: str
    size_bytes: int
    storage: Literal["gcs", "local"]


# _resolve_subscription_plan imported from services.audit_helpers (Item 24).


def _require_white_label_plan(
    db: Session,
    user: models.User | None,
    *,
    scope: Literal["workspace", "user"],
) -> None:
    if scope == "workspace" and user is not None:
        workspace = (
            db.query(models.Workspace)
            .join(
                models.WorkspaceUser,
                models.WorkspaceUser.workspace_id == models.Workspace.id,
            )
            .filter(models.WorkspaceUser.user_id == user.id)
            .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
            .first()
        )
        if workspace is not None:
            if can_use_feature(
                resolve_workspace_owner_plan(db, workspace=workspace), "has_white_label"
            ):
                return
            raise HTTPException(
                status_code=402, detail="White-label is available on the Executive plan"
            )
    if can_use_feature(_resolve_subscription_plan(user), "has_white_label"):
        return
    raise HTTPException(status_code=402, detail="White-label is available on the Executive plan")


def _resolve_logo_scope_prefix(
    db: Session,
    *,
    user: models.User,
    scope: Literal["workspace", "user"],
) -> str:
    if scope == "user":
        return f"users/{user.id}/"

    membership = (
        db.query(models.WorkspaceUser.workspace_id)
        .filter(models.WorkspaceUser.user_id == user.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .first()
    )
    if membership and membership[0]:
        return f"workspaces/{int(membership[0])}/"
    return f"users/{user.id}/"


def _resolve_file_extension(*, upload_file: UploadFile, content_type: str) -> str:
    filename_extension = Path((upload_file.filename or "").strip()).suffix.lower()
    if filename_extension in ALLOWED_LOGO_EXTENSIONS:
        if filename_extension == ".jpeg":
            return ".jpg"
        return filename_extension

    if content_type in ALLOWED_LOGO_CONTENT_TYPES:
        return ALLOWED_LOGO_CONTENT_TYPES[content_type]

    guessed = mimetypes.guess_extension(content_type or "")
    if guessed and guessed.lower() in ALLOWED_LOGO_EXTENSIONS:
        if guessed.lower() == ".jpeg":
            return ".jpg"
        return guessed.lower()

    raise HTTPException(
        status_code=400,
        detail="Unsupported logo format. Allowed: PNG, JPG, WebP.",
    )


def _build_local_logo_url(object_uri: str) -> str:
    object_path = object_uri[8:] if object_uri.startswith("local://") else object_uri
    encoded_object_path = quote(object_path.strip("/"), safe="/")
    backend_base = (settings.BACKEND_PUBLIC_URL or "http://localhost:8000").rstrip("/")
    return f"{backend_base}/api/v1/uploads/logo/local/{encoded_object_path}"


@router.post("/logo", response_model=LogoUploadResponse)
async def upload_logo_asset(
    scope: Literal["workspace", "user"] = "workspace",
    file: UploadFile = File(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot upload branding logos.")
    _require_white_label_plan(db, user, scope=scope)

    content_type = str(file.content_type or "").strip().lower()
    extension = _resolve_file_extension(upload_file=file, content_type=content_type)
    if content_type not in ALLOWED_LOGO_CONTENT_TYPES:
        content_type = mimetypes.types_map.get(extension, "")
    if content_type not in ALLOWED_LOGO_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported logo MIME type. Allowed: image/png, image/jpeg, image/webp.",
        )

    payload = await file.read()
    size_bytes = len(payload)
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Uploaded logo is empty.")
    if size_bytes > MAX_LOGO_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Logo file is too large. Maximum size is 2MB.")

    scope_prefix = _resolve_logo_scope_prefix(db, user=user, scope=scope)
    final_filename = f"{uuid.uuid4().hex}{extension}"
    gcs_service = get_storage_service()
    object_uri = gcs_service.upload_file(
        prefix=f"{settings.STORAGE_LOGOS_PREFIX}{scope_prefix}",
        filename=final_filename,
        data=payload,
        content_type=content_type,
        cache_control="public,max-age=31536000",
        metadata={"uploaded_by_user_id": str(user.id)},
    )

    if object_uri.startswith("gs://"):
        public_url = gcs_service.to_public_url(object_uri)
        if not public_url:
            raise HTTPException(status_code=500, detail="Failed to resolve logo public URL.")
        storage_type: Literal["gcs", "local"] = "gcs"
        url = public_url
    else:
        storage_type = "local"
        url = _build_local_logo_url(object_uri)

    return LogoUploadResponse(
        url=url,
        object_uri=object_uri,
        filename=final_filename,
        content_type=content_type,
        size_bytes=size_bytes,
        storage=storage_type,
    )


@router.get("/logo/local/{object_path:path}", include_in_schema=False)
def fetch_local_logo(object_path: str):
    parts = Path(object_path.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=404, detail="Logo not found.")

    gcs_service = get_storage_service()
    payload = gcs_service.download_file(storage_uri=f"local://{object_path}")
    if payload is None:
        raise HTTPException(status_code=404, detail="Logo not found.")

    media_type = mimetypes.guess_type(object_path)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "public, max-age=300",
        "X-Content-Type-Options": "nosniff",
    }
    if object_path.lower().endswith(".svg"):
        media_type = "application/octet-stream"
        headers["Content-Disposition"] = 'attachment; filename="logo.svg"'
    return Response(
        content=payload,
        media_type=media_type,
        headers=headers,
    )


@router.get("/cms/local/{object_path:path}", include_in_schema=False)
def fetch_local_cms_image(object_path: str):
    """Serve locally-stored CMS images (development/fallback)."""
    parts = Path(object_path.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=404, detail="Image not found.")

    gcs_service = get_storage_service()
    payload = gcs_service.download_file(storage_uri=f"local://{object_path}")
    if payload is None:
        raise HTTPException(status_code=404, detail="Image not found.")

    media_type = mimetypes.guess_type(object_path)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(
        content=payload,
        media_type=media_type,
        headers=headers,
    )


@router.get("/cms/s3/{object_path:path}", include_in_schema=False)
def fetch_s3_cms_image(object_path: str):
    """Serve CMS images stored in the private S3 bucket (proxied via backend IAM)."""
    parts = Path(object_path.replace("\\", "/")).parts
    if any(part == ".." for part in parts):
        raise HTTPException(status_code=404, detail="Image not found.")
    from core.config import settings

    bucket = str(getattr(settings, "S3_BUCKET_NAME", "") or "").strip()
    if not bucket:
        raise HTTPException(status_code=404, detail="Image not found.")
    gcs_service = get_storage_service()
    payload = gcs_service.download_file(storage_uri=f"s3://{bucket}/{object_path}")
    if payload is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    media_type = mimetypes.guess_type(object_path)[0] or "application/octet-stream"
    headers = {"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"}
    return Response(content=payload, media_type=media_type, headers=headers)
