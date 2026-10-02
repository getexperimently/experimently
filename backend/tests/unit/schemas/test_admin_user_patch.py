"""
``AdminUserPatch``: the body of ``PATCH /api/v1/admin/users/{user_id}`` (#607).

Send only the keys to change; at least one; ``null`` refused; any other key
refused. The API behaviour is pinned in
``backend/tests/integration/api/test_admin_users_api.py``; these pin the
schema on its own, including what it publishes.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.user import AdminUserPatch, UserUpdate

pytestmark = [pytest.mark.unit]


def _error_types(body: dict) -> list:
    with pytest.raises(ValidationError) as caught:
        AdminUserPatch.model_validate(body)
    return [error["type"] for error in caught.value.errors()]


class TestAdminUserPatch:
    def test_only_the_keys_sent_are_set(self):
        patch = AdminUserPatch.model_validate({"role": "ANALYST"})
        assert patch.model_fields_set == {"role"}
        assert patch.model_dump(exclude_unset=True) == {"role": "ANALYST"}

    @pytest.mark.parametrize("sent", ["analyst", "Analyst", "ANALYST"])
    def test_the_role_is_case_insensitive(self, sent):
        assert AdminUserPatch.model_validate({"role": sent}).role == "ANALYST"

    def test_false_is_a_value_not_an_omission(self):
        patch = AdminUserPatch.model_validate({"is_active": False})
        assert patch.model_fields_set == {"is_active"}
        assert patch.is_active is False

    @pytest.mark.parametrize(
        "body, expected",
        [
            ({"role": None}, ["literal_error"]),
            ({"is_active": None}, ["bool_type"]),
            ({"role": "SUPERADMIN"}, ["literal_error"]),
            ({}, ["value_error"]),
            ({"is_superuser": True}, ["extra_forbidden"]),
            ({"role": "VIEWER", "username": "x"}, ["extra_forbidden"]),
        ],
        ids=["null-role", "null-active", "unknown-role", "empty", "superuser", "extra"],
    )
    def test_refused(self, body, expected):
        assert _error_types(body) == expected

    def test_the_published_schema_has_no_null_branch_and_no_default(self):
        schema = AdminUserPatch.model_json_schema()
        assert schema["additionalProperties"] is False
        assert "required" not in schema
        assert schema["properties"]["role"]["type"] == "string"
        assert schema["properties"]["role"]["enum"] == [
            "ADMIN",
            "DEVELOPER",
            "ANALYST",
            "VIEWER",
        ]
        assert schema["properties"]["is_active"]["type"] == "boolean"
        for name, prop in schema["properties"].items():
            assert "anyOf" not in prop, name
            assert "default" not in prop, name

    def test_user_update_is_untouched(self):
        """T59: the PUT body keeps its required fields and its defaults."""
        schema = UserUpdate.model_json_schema()
        assert schema["required"] == ["username", "email"]
        assert "role" not in schema["properties"]
        assert schema.get("additionalProperties") is None
