"""
Tests for the feature flag Pydantic schemas (#94, D39 as narrowed by D40).

* ``FeatureFlagRead`` is the one response representation. It reads the stored
  ``status`` (lower-cased) and derives ``is_active`` from it, holds types only,
  and shares no base with the request models.
* ``FeatureFlagCreate`` / ``FeatureFlagUpdate`` refuse unknown fields, accept
  the read-only fields of a response, refuse an explicit null on the NOT NULL
  fields, start a new flag off, and accept ``default_value`` only as JSON
  ``false``.
"""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.app.models.feature_flag import FeatureFlag, FeatureFlagStatus
from backend.app.schemas.feature_flag import (
    DEFAULT_VALUE_UNSUPPORTED,
    NOT_NULL_FIELDS,
    READ_ONLY_FIELDS,
    FeatureFlagCreate,
    FeatureFlagListResponse,
    FeatureFlagRead,
    FeatureFlagUpdate,
    flag_to_read,
)

pytestmark = pytest.mark.unit


def _flag(status, **overrides) -> FeatureFlag:
    now = datetime(2024, 1, 1, 12, 0, 0)
    values = {
        "id": uuid.uuid4(),
        "key": "checkout-v2",
        "name": "Checkout v2",
        "description": "New checkout",
        "status": status,
        "rollout_percentage": 25,
        "targeting_rules": None,
        "default_value": False,
        "tags": ["checkout"],
        "owner_id": uuid.uuid4(),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return FeatureFlag(**values)


def _errors(model, data):
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return [(e["type"], e["loc"]) for e in caught.value.errors()]


class TestFeatureFlagReadStatus:
    """``status`` / ``is_active`` derivation from ORM instances and dicts."""

    def test_inactive_model_reports_inactive(self):
        read = flag_to_read(_flag(FeatureFlagStatus.INACTIVE))
        assert read.status == "inactive"
        assert read.is_active is False

    def test_active_model_reports_active(self):
        read = flag_to_read(_flag(FeatureFlagStatus.ACTIVE))
        assert read.status == "active"
        assert read.is_active is True

    def test_archived_model_is_not_active(self):
        read = flag_to_read(_flag(FeatureFlagStatus.ARCHIVED))
        assert read.status == "archived"
        assert read.is_active is False

    def test_string_status_on_model_is_normalised(self):
        """CRUD helpers assign ``FeatureFlagStatus.X.value`` (a str) in-session."""
        flag = _flag(FeatureFlagStatus.INACTIVE)
        flag.status = FeatureFlagStatus.ACTIVE.value  # "ACTIVE"
        read = flag_to_read(flag)
        assert read.status == "active"
        assert read.is_active is True

    def test_dict_status_overrides_conflicting_is_active(self):
        data = {
            "id": str(uuid.uuid4()),
            "key": "k",
            "name": "n",
            "is_active": True,
            "status": FeatureFlagStatus.INACTIVE,
            "rollout_percentage": 0,
            "default_value": False,
            "created_at": datetime(2024, 1, 1),
            "updated_at": datetime(2024, 1, 1),
        }
        read = FeatureFlagRead.model_validate(data)
        assert read.status == "inactive"
        assert read.is_active is False

    def test_list_response_serialises_status_and_is_active(self):
        response = FeatureFlagListResponse(
            items=[_flag(FeatureFlagStatus.INACTIVE), _flag(FeatureFlagStatus.ACTIVE)],
            total=2,
            skip=0,
            limit=100,
        )
        dumped = response.model_dump(mode="json")
        assert [i["status"] for i in dumped["items"]] == ["inactive", "active"]
        assert [i["is_active"] for i in dumped["items"]] == [False, True]


class TestFeatureFlagReadShape:
    EXPECTED = {
        "id",
        "key",
        "name",
        "description",
        "status",
        "is_active",
        "rollout_percentage",
        "targeting_rules",
        "default_value",
        "tags",
        "owner_id",
        "created_at",
        "updated_at",
    }

    @pytest.mark.regression
    def test_exact_field_set_and_no_rules(self):
        """``rules``, ``variants``, ``metrics`` and ``last_evaluated`` are gone."""
        dumped = flag_to_read(_flag(FeatureFlagStatus.ACTIVE)).model_dump(mode="json")
        assert set(dumped) == self.EXPECTED

    @pytest.mark.regression
    def test_null_owner_is_null_not_the_string_none(self):
        dumped = flag_to_read(
            _flag(FeatureFlagStatus.ACTIVE, owner_id=None)
        ).model_dump(mode="json")
        assert dumped["owner_id"] is None

    @pytest.mark.regression
    def test_reports_the_stored_default_value(self):
        """Read from the row, not a schema default: a row forced to true says true."""
        read = flag_to_read(_flag(FeatureFlagStatus.ACTIVE, default_value=True))
        assert read.default_value is True

    def test_holds_types_only(self):
        """A stored key the request pattern would refuse still reads (PE M2b)."""
        read = flag_to_read(
            _flag(FeatureFlagStatus.ACTIVE, key="Legacy Key", name="n" * 150)
        )
        assert read.key == "Legacy Key"

    def test_shares_no_base_with_the_request_models(self):
        """``extra="forbid"`` is inherited; a forbidding response 500s on a row."""
        assert not issubclass(FeatureFlagRead, (FeatureFlagCreate, FeatureFlagUpdate))
        assert FeatureFlagRead.model_config.get("extra") in (None, "ignore")
        for name in FeatureFlagRead.model_fields:
            field = FeatureFlagRead.model_fields[name]
            assert not field.metadata, f"{name} carries a constraint: {field.metadata}"

    def test_every_field_is_required_in_the_published_schema(self):
        schema = FeatureFlagRead.model_json_schema(mode="serialization")
        assert set(schema["required"]) == self.EXPECTED
        assert schema["properties"]["is_active"]["type"] == "boolean"
        assert schema["properties"]["default_value"]["type"] == "boolean"


class TestReadOnlySet:
    def test_read_only_is_what_a_response_has_and_a_request_does_not_write(self):
        """V4b: computed, so a new response field must be classified."""
        writable = {"is_active"} | (
            set(FeatureFlagCreate.model_fields) - READ_ONLY_FIELDS
        )
        assert set(FeatureFlagRead.model_fields) - writable == READ_ONLY_FIELDS

    def test_request_models_declare_every_read_only_field(self):
        for model in (FeatureFlagCreate, FeatureFlagUpdate):
            assert READ_ONLY_FIELDS <= set(model.model_fields), model.__name__
            for name in READ_ONLY_FIELDS:
                extra = model.model_fields[name].json_schema_extra or {}
                assert extra.get("readOnly") is True, (model.__name__, name)

    def test_a_response_body_validates_as_both_request_models(self):
        """A GET body can be sent back unchanged."""
        body = flag_to_read(_flag(FeatureFlagStatus.ARCHIVED)).model_dump(mode="json")
        FeatureFlagUpdate.model_validate(body)
        FeatureFlagCreate.model_validate(
            {**body, "status": "inactive", "key": "checkout-v2"}
        )


class TestRequestModels:
    @pytest.mark.regression
    @pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
    @pytest.mark.parametrize(
        "field", ["rules", "enabled", "variants", "metrics", "last_evaluated", "foo"]
    )
    def test_unknown_field_is_refused(self, model, field):
        data = {"key": "k", "name": "n", field: 1}
        assert _errors(model, data) == [("extra_forbidden", (field,))]

    @pytest.mark.regression
    def test_a_new_flag_is_off_unless_asked(self):
        assert FeatureFlagCreate(key="k", name="n").is_active is False

    def test_defaults(self):
        created = FeatureFlagCreate(key="k", name="n")
        assert created.rollout_percentage == 0
        assert created.default_value is False

    @pytest.mark.regression
    @pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
    @pytest.mark.parametrize("field", NOT_NULL_FIELDS)
    def test_explicit_null_is_refused(self, model, field):
        data = {"key": "k", "name": "n", field: None}
        assert _errors(model, data) == [("null_not_allowed", (field,))]

    @pytest.mark.parametrize("field", ["description", "targeting_rules", "tags"])
    def test_nullable_fields_accept_null_on_update(self, field):
        update = FeatureFlagUpdate.model_validate({field: None})
        assert update.model_dump(exclude_unset=True) == {field: None}

    def test_name_is_limited_to_the_column_length(self):
        assert _errors(FeatureFlagCreate, {"key": "k", "name": "x" * 101}) == [
            ("string_too_long", ("name",))
        ]


class TestDefaultValue:
    @pytest.mark.regression
    @pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
    def test_default_value_true_is_422(self, model):
        with pytest.raises(ValidationError) as caught:
            model.model_validate({"key": "k", "name": "n", "default_value": True})
        (error,) = caught.value.errors()
        assert error["type"] == "default_value_unsupported"
        assert error["loc"] == ("default_value",)
        assert error["msg"] == DEFAULT_VALUE_UNSUPPORTED

    @pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
    @pytest.mark.parametrize("sent", ["false", "true", 0, 1, {}, [], "s3cr3t-value"])
    def test_only_json_false_is_a_boolean(self, model, sent):
        with pytest.raises(ValidationError) as caught:
            model.model_validate({"key": "k", "name": "n", "default_value": sent})
        (error,) = caught.value.errors()
        assert (error["type"], error["loc"]) == ("bool_type", ("default_value",))
        assert str(sent) not in error["msg"]

    @pytest.mark.parametrize("model", [FeatureFlagCreate, FeatureFlagUpdate])
    def test_false_is_accepted(self, model):
        assert (
            model.model_validate(
                {"key": "k", "name": "n", "default_value": False}
            ).default_value
            is False
        )
