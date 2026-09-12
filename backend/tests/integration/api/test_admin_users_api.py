"""
`GET /api/v1/admin/users` — the list the dashboard's user administration reads.

Regression: `UserListResponse.items` was annotated `List[Dict[str, Any]]` while
the endpoint handed it ORM objects, so every call was a 500, and no user
response schema carried `role`, which the dashboard needs to render the role
chip and decide what to offer.
"""

from __future__ import annotations

import uuid

import pytest

from backend.app.core.security import get_password_hash
from backend.app.models.user import User, UserRole


def _make_user(db_session, role: UserRole) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"admin_list_{suffix}",
        email=f"admin_list_{suffix}@example.com",
        full_name=f"Admin List {suffix}",
        hashed_password=get_password_hash("Str0ng-Passw0rd"),
        is_active=True,
        is_superuser=role is UserRole.ADMIN,
        role=role,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.mark.regression
class TestAdminUserList:
    def test_returns_200_with_the_users_and_their_roles(self, admin_client, db_session):
        analyst = _make_user(db_session, UserRole.ANALYST)

        response = admin_client.get("/api/v1/admin/users", params={"limit": 100})

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] >= 1
        # Newest first, so the account just created is on the first page.
        listed = {item["email"]: item for item in body["items"]}
        assert analyst.email in listed
        assert listed[analyst.email]["role"] == "ANALYST"
        assert listed[analyst.email]["username"] == analyst.username
        # The hash never leaves the server.
        assert "hashed_password" not in listed[analyst.email]

    def test_newest_first_so_pagination_is_deterministic(
        self, admin_client, db_session
    ):
        """Without an ORDER BY, pages can repeat or drop rows."""
        newest = _make_user(db_session, UserRole.VIEWER)

        first_page = admin_client.get(
            "/api/v1/admin/users", params={"skip": 0, "limit": 5}
        ).json()

        assert first_page["items"][0]["email"] == newest.email
        # Two identical requests agree, and the second page does not repeat the first.
        again = admin_client.get(
            "/api/v1/admin/users", params={"skip": 0, "limit": 5}
        ).json()
        assert [i["id"] for i in again["items"]] == [
            i["id"] for i in first_page["items"]
        ]
        second_page = admin_client.get(
            "/api/v1/admin/users", params={"skip": 5, "limit": 5}
        ).json()
        assert not {i["id"] for i in first_page["items"]} & {
            i["id"] for i in second_page["items"]
        }

    def test_pagination_fields_are_echoed(self, admin_client):
        response = admin_client.get(
            "/api/v1/admin/users", params={"skip": 0, "limit": 1}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["skip"] == 0 and body["limit"] == 1
        assert len(body["items"]) <= 1

    def test_a_non_superuser_is_refused(self, developer_client):
        assert developer_client.get("/api/v1/admin/users").status_code == 403
