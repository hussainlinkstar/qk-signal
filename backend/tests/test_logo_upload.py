from __future__ import annotations

import asyncio
from io import BytesIO
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.datastructures import Headers

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from routers.upload_router import fetch_local_logo, upload_logo_asset


class _FakeStorageService:
    def upload_file(self, **_kwargs) -> str:
        return "gs://test-bucket/logos/workspaces/1/logo.png"

    def to_public_url(self, storage_uri: str) -> str:
        return f"https://storage.googleapis.com/test-bucket/{storage_uri.removeprefix('gs://test-bucket/')}"


def _build_upload_file(filename: str, payload: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        filename=filename,
        file=BytesIO(payload),
        headers=Headers({"content-type": content_type}),
    )


def _seed_users(db: Session) -> tuple[models.User, models.User]:
    elite_user = models.User(
        email="elite-logo@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    free_user = models.User(
        email="free-logo@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    db.add_all([elite_user, free_user])
    db.flush()

    workspace = models.Workspace(name="Logo Workspace", owner_id=elite_user.id)
    db.add(workspace)
    db.flush()

    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=elite_user.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    db.add(
        models.Subscription(
            user_id=elite_user.id,
            stripe_customer_id="cus_logo_upload",
            plan_type="plan_executive",
            status="active",
        )
    )

    db.commit()
    db.refresh(elite_user)
    db.refresh(free_user)
    return elite_user, free_user


def test_logo_upload_route_enforces_plan_and_validates_file(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()

    elite_user, free_user = _seed_users(db)
    monkeypatch.setattr("routers.upload_router.get_storage_service", lambda: _FakeStorageService())

    try:
        success = asyncio.run(
            upload_logo_asset(
                scope="workspace",
                file=_build_upload_file("logo.png", b"png-bytes", "image/png"),
                user=elite_user,
                db=db,
            )
        )
        assert success.storage == "gcs"
        assert success.url.startswith("https://storage.googleapis.com/test-bucket/")
        assert success.object_uri.startswith("gs://test-bucket/logos/workspaces/")

        with pytest.raises(HTTPException) as forbidden_exc:
            asyncio.run(
                upload_logo_asset(
                    scope="workspace",
                    file=_build_upload_file("logo.png", b"png-bytes", "image/png"),
                    user=free_user,
                    db=db,
                )
            )
        assert forbidden_exc.value.status_code == 402

        with pytest.raises(HTTPException) as wrong_type_exc:
            asyncio.run(
                upload_logo_asset(
                    scope="workspace",
                    file=_build_upload_file("logo.txt", b"not-an-image", "text/plain"),
                    user=elite_user,
                    db=db,
                )
            )
        assert wrong_type_exc.value.status_code == 400

        with pytest.raises(HTTPException) as svg_exc:
            asyncio.run(
                upload_logo_asset(
                    scope="workspace",
                    file=_build_upload_file(
                        "logo.svg",
                        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                        "image/svg+xml",
                    ),
                    user=elite_user,
                    db=db,
                )
            )
        assert svg_exc.value.status_code == 400
        assert "PNG, JPG, WebP" in str(svg_exc.value.detail)

        with pytest.raises(HTTPException) as too_large_exc:
            asyncio.run(
                upload_logo_asset(
                    scope="workspace",
                    file=_build_upload_file(
                        "logo.png",
                        b"a" * (2 * 1024 * 1024 + 1),
                        "image/png",
                    ),
                    user=elite_user,
                    db=db,
                )
            )
        assert too_large_exc.value.status_code == 413
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_fetch_local_logo_serves_existing_svg_as_attachment(monkeypatch) -> None:
    class _LocalSvgStorageService:
        def download_file(self, storage_uri: str) -> bytes | None:
            assert storage_uri == "local://logos/workspaces/1/logo.svg"
            return b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"

    monkeypatch.setattr(
        "routers.upload_router.get_storage_service", lambda: _LocalSvgStorageService()
    )

    response = fetch_local_logo("logos/workspaces/1/logo.svg")

    assert response.media_type == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == 'attachment; filename="logo.svg"'
