"""
Integration tests for POST /api/v1/users/ with real password hashing.

The unit tests in ``backend/tests/unit/api/test_users.py`` patch
``backend.app.api.v1.endpoints.users.get_password_hash``, which hid a 500:
``UserCreate.password`` is a pydantic ``SecretStr`` and ``get_password_hash``
calls ``password.encode()``.  Nothing here patches hashing, so the endpoint
has to produce a hash the auth service can actually verify.
"""
import uuid

import pytest
from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.services.local_auth_service import (
    InvalidCredentialsError,
    LocalAuthService,
)

PASSWORD = "StrongPass123"


def _payload(**overrides) -> dict:
    suffix = uuid.uuid4().hex[:8]
    body = {
        "username": f"invited_{suffix}",
        "email": f"invited_{suffix}@example.com",
        "full_name": "Invited User",
        "password": PASSWORD,
        "is_active": True,
        "is_superuser": False,
    }
    body.update(overrides)
    return body


@pytest.mark.integration
class TestCreateUserHashesPassword:
    """POST /api/v1/users/ — the dashboard's "invite user" modal."""

    def test_create_user_returns_201_without_patching_hashing(self, admin_client):
        """Real hashing path: the endpoint must not 500 on SecretStr."""
        response = admin_client.post("/api/v1/users/", json=_payload())

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["username"].startswith("invited_")
        assert data["is_active"] is True

    def test_created_user_can_log_in_with_the_password_sent(
        self, admin_client, db_session: Session
    ):
        """The stored hash is a real bcrypt hash of the submitted password."""
        body = _payload()
        response = admin_client.post("/api/v1/users/", json=body)
        assert response.status_code == 201, response.text

        created = db_session.query(User).filter(User.email == body["email"]).first()
        assert created is not None
        # Never the raw password, never the SecretStr repr ("**********").
        assert created.hashed_password not in (PASSWORD, "**********")
        assert created.hashed_password.startswith("$2b$")

        service = LocalAuthService()
        authenticated = service.authenticate(
            db_session, email=body["email"], password=PASSWORD
        )
        assert authenticated.id == created.id

        with pytest.raises(InvalidCredentialsError):
            LocalAuthService().authenticate(
                db_session, email=body["email"], password="WrongPass123"
            )

    def test_non_superuser_cannot_create_users(self, developer_client):
        """Only superusers may invite: the permission check still applies."""
        response = developer_client.post("/api/v1/users/", json=_payload())
        assert response.status_code == 403, response.text
