"""``ExperimentUpdate``: required fields cannot be set to null (#541).

The request-level behaviour (422, nothing written) is pinned by
``backend/tests/integration/api/test_experiment_update_required_fields.py``;
this file pins the schema itself, and its OpenAPI shape.
"""

import pytest
from pydantic import ValidationError

from backend.app.schemas.experiment import NOT_NULL_UPDATE_FIELDS, ExperimentUpdate

pytestmark = [pytest.mark.unit]

REQUIRED = (
    "name",
    "status",
    "experiment_type",
    "sequential_testing_enabled",
    "optimization_type",
    "correction_method",
    "confidence_level",
)


def test_the_not_null_fields_are_exactly_these():
    assert NOT_NULL_UPDATE_FIELDS == REQUIRED


@pytest.mark.regression
@pytest.mark.parametrize("field", REQUIRED)
def test_null_is_refused_with_a_fixed_message(field):
    with pytest.raises(ValidationError) as caught:
        ExperimentUpdate(**{field: None})

    errors = caught.value.errors(include_url=False)
    assert [(e["type"], e["loc"], e["msg"]) for e in errors] == [
        ("null_not_allowed", (field,), f"{field} cannot be null")
    ]


@pytest.mark.parametrize("field", REQUIRED)
def test_leaving_the_field_out_is_allowed(field):
    update = ExperimentUpdate()

    assert field not in update.model_fields_set
    assert field not in update.model_dump(exclude_unset=True)


@pytest.mark.regression
def test_name_is_limited_to_the_column_length():
    assert ExperimentUpdate(name="n" * 100).name == "n" * 100
    with pytest.raises(ValidationError) as caught:
        ExperimentUpdate(name="n" * 101)
    (error,) = caught.value.errors(include_url=False)
    assert (error["type"], error["loc"]) == ("string_too_long", ("name",))


@pytest.mark.parametrize(
    "field", ["description", "hypothesis", "variants", "metrics", "bayesian_enabled"]
)
def test_null_on_a_nullable_field_is_still_accepted(field):
    update = ExperimentUpdate(**{field: None})

    assert update.model_dump(exclude_unset=True) == {field: None}


def test_openapi_shape():
    properties = ExperimentUpdate.model_json_schema()["properties"]

    assert properties["name"]["type"] == "string"
    assert properties["name"]["maxLength"] == 100
    assert properties["sequential_testing_enabled"]["type"] == "boolean"
    for field in REQUIRED:
        assert "anyOf" not in properties[field], field
    assert {"type": "null"} in properties["description"]["anyOf"]
