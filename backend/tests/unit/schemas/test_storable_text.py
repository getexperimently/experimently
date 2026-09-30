"""The request-text check shared by the tracking schemas (#543, #402)."""

from typing import Annotated

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.app.api.v1.endpoints.client_errors import ClientErrorRequest
from backend.app.api.v1.endpoints.flag_evaluations import FlagEvaluationCount
from backend.app.schemas.storable_text import (
    contains_unstorable_text,
    storable_text_param,
    unstorable_text_message,
)
from backend.app.schemas.tracking import (
    AssignmentRequest,
    EventBatchRequest,
    EventCreate,
    EventRequest,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

REFUSED = ["\x00", "\ud800", "\udbff", "\udc00", "\udfff"]
STORABLE = ["", "plain", "été", "\U0001f642", "퟿", "", "\x01"]


@pytest.mark.parametrize("char", REFUSED)
@pytest.mark.parametrize(
    "shape",
    [
        lambda c: f"a{c}b",
        lambda c: {"k": f"a{c}"},
        lambda c: {f"a{c}": 1},
        lambda c: [1, [2, {"x": (f"{c}",)}]],
    ],
    ids=["string", "dict-value", "dict-key", "nested"],
)
def test_refused_characters_are_found(char, shape):
    assert contains_unstorable_text(shape(char))


@pytest.mark.parametrize("text", STORABLE)
def test_storable_text_is_not_flagged(text):
    assert not contains_unstorable_text({text: [text, {"k": text}]})


def test_deep_nesting_does_not_exhaust_the_stack():
    value = "\x00"
    for _ in range(50_000):
        value = [value]
    assert contains_unstorable_text(value)


@pytest.mark.parametrize(
    "model,data,field",
    [
        (AssignmentRequest, {"experiment_key": "k", "user_id": "u\x00"}, "user_id"),
        (
            EventRequest,
            {"event_type": "t", "user_id": "u", "experiment_key": "k\ud800"},
            "experiment_key",
        ),
        (
            EventCreate,
            {"event_name": "n", "experiment_id": "x", "properties": '{"k": "\\u0000"}'},
            "properties",
        ),
        (
            ClientErrorRequest,
            {"feature_flag_key": "f\udfff", "error_type": "t", "message": "m"},
            "feature_flag_key",
        ),
        (
            FlagEvaluationCount,
            {
                "flag_key": "f\x00",
                "count": 1,
                "enabled_count": 0,
                "window_start": "2026-09-27T12:00:00Z",
                "window_end": "2026-09-27T12:01:00Z",
            },
            "flag_key",
        ),
    ],
    ids=["assign", "track", "events-json-string", "errors", "evaluations"],
)
def test_schema_refuses_with_the_fixed_message(model, data, field):
    with pytest.raises(ValidationError) as exc:
        model.model_validate(data)
    errors = exc.value.errors()
    assert [e["loc"] for e in errors] == [(field,)]
    assert errors[0]["msg"] == f"Value error, {unstorable_text_message(field)}"


def test_batch_names_the_item_field():
    with pytest.raises(ValidationError) as exc:
        EventBatchRequest.model_validate(
            {"events": [{"event_type": "t", "user_id": "u\x00", "experiment_key": "k"}]}
        )
    assert [e["loc"] for e in exc.value.errors()] == [("events", 0, "user_id")]


# ---------------------------------------------------------------------------
# storable_text_param: the same check for a path or query parameter (#547)
# ---------------------------------------------------------------------------

PARAM = TypeAdapter(Annotated[str, storable_text_param("flag_key")])


@pytest.mark.parametrize("char", REFUSED)
def test_param_refuses_with_the_fixed_message(char):
    with pytest.raises(ValidationError) as caught:
        PARAM.validate_python(f"a{char}b")
    (error,) = caught.value.errors()
    assert error["msg"] == f"Value error, {unstorable_text_message('flag_key')}"


@pytest.mark.parametrize("text", STORABLE)
def test_param_accepts_storable_text_unchanged(text):
    assert PARAM.validate_python(text) == text


def test_param_adds_nothing_to_the_json_schema():
    """The OpenAPI document must not change when a route adopts the check."""
    assert PARAM.json_schema() == TypeAdapter(str).json_schema()
