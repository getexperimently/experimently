"""Experiment create/update schemas: string limits match their columns (#551).

A schema string field stored in a ``String(n)`` column must carry
``max_length == n``. Without it a longer value reaches the database, and the
request answers 500 (update) or a generic 400 (create) instead of 422. The
request-level behaviour for the metric fields is pinned by
``backend/tests/integration/api/test_experiment_metric_field_lengths.py``.
"""

import enum

import annotated_types
import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy import String, Text

from backend.app.models.experiment import Experiment, Metric, Variant
from backend.app.schemas.experiment import (
    ExperimentCreate,
    ExperimentUpdate,
    MetricBase,
    VariantBase,
)

pytestmark = [pytest.mark.unit]

#: Schema -> the table its string fields are stored in.
PAIRS = [
    (ExperimentCreate, Experiment),
    (ExperimentUpdate, Experiment),
    (VariantBase, Variant),
    (MetricBase, Metric),
]


def _max_length(schema: type[BaseModel], field: str):
    """The field's ``max_length``; for an enum field, its longest value's
    length, which bounds it as surely (``correction_method``, #580)."""
    annotation = schema.model_fields[field].annotation
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return max(len(member.value) for member in annotation)
    for item in schema.model_fields[field].metadata:
        if isinstance(item, annotated_types.MaxLen):
            return item.max_length
    return None


def _string_columns(model):
    """Column name -> length for every plain String/Text column."""
    out = {}
    for column in model.__table__.columns:
        if isinstance(column.type, (String, Text)) and not hasattr(
            column.type, "enums"
        ):
            out[column.name] = column.type.length
    return out


def _fits(schema: type[BaseModel], field: str, column_length: int) -> bool:
    """A string field must carry the column's length; an enum field's longest
    value must fit in it."""
    limit = _max_length(schema, field)
    annotation = schema.model_fields[field].annotation
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return limit <= column_length
    return limit == column_length


@pytest.mark.regression
@pytest.mark.parametrize(
    "schema, model", PAIRS, ids=[schema.__name__ for schema, _ in PAIRS]
)
def test_every_bounded_string_column_has_the_same_schema_limit(schema, model):
    columns = _string_columns(model)
    mismatches = {
        field: (columns[field], _max_length(schema, field))
        for field in schema.model_fields
        if columns.get(field) is not None and not _fits(schema, field, columns[field])
    }
    assert mismatches == {}, "field: (column length, schema max_length)"


def test_the_pin_sees_the_metric_columns():
    """Guard the guard: the pin above would pass vacuously on no columns."""
    assert _string_columns(Metric)["aggregation_method"] == 50
    assert _string_columns(Metric)["event_value_path"] == 100


@pytest.mark.regression
@pytest.mark.parametrize(
    "field, limit", [("aggregation_method", 50), ("event_value_path", 100)]
)
def test_metric_field_is_limited_to_its_column_length(field, limit):
    base = {"name": "m", "event_name": "e"}
    assert getattr(MetricBase(**base, **{field: "x" * limit}), field) == "x" * limit
    with pytest.raises(ValidationError) as caught:
        MetricBase(**base, **{field: "x" * (limit + 1)})
    (error,) = caught.value.errors(include_url=False)
    assert (error["type"], error["loc"], error["ctx"]) == (
        "string_too_long",
        (field,),
        {"max_length": limit},
    )
