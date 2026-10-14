import models
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin import get_db
from auth.token_verifier import get_current_staff_user
from database import Base
from main import app


def _build_client_with_db(admin_user: models.User):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_get_current_user
    return TestClient(app), db


def test_email_outbox_template_key_filter_targets_template_key() -> None:
    admin_user = models.User(
        email="admin-outbox@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    db.add_all(
        [
            models.EmailOutbox(
                user_id=admin_user.id,
                to_email="finance@example.com",
                subject="Invoice paid",
                category="billing",
                template_key="invoice.paid",
                status="pending",
                attempts=0,
            ),
            models.EmailOutbox(
                user_id=admin_user.id,
                to_email="ops@example.com",
                subject="Audit complete",
                category="billing",
                template_key="audit.completed",
                status="pending",
                attempts=0,
            ),
        ]
    )
    db.commit()

    response = client.get(
        "/api/v1/admin/email-outbox",
        params={"template_key": "invoice.paid"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["template_key"] == "invoice.paid"
    assert payload["items"][0]["category"] == "billing"

    app.dependency_overrides.clear()
    db.close()
