"""``stored_metric_type``: the one mapping from a sent metric type to a stored one (#558).

The API refuses an unknown type in the request schema already; these pin the
service's own behaviour for callers that hand it a dict.
"""

from __future__ import annotations

import pytest

from backend.app.models.experiment import MetricType as ModelMetricType
from backend.app.schemas.experiment import MetricType as SchemaMetricType
from backend.app.services.experiment_service import (
    UNKNOWN_METRIC_TYPE_MESSAGE,
    AnalysisConfigError,
    stored_metric_type,
)

pytestmark = pytest.mark.unit


@pytest.mark.regression
@pytest.mark.parametrize("member", list(SchemaMetricType))
def test_each_schema_value_is_stored_as_the_same_model_value(member):
    assert stored_metric_type(member) is ModelMetricType(member.value)
    assert stored_metric_type(member.value) is ModelMetricType(member.value)
    assert stored_metric_type(member.value.upper()) is ModelMetricType(member.value)


def test_a_model_member_and_a_missing_value():
    assert stored_metric_type(ModelMetricType.REVENUE) is ModelMetricType.REVENUE
    assert stored_metric_type(None) is ModelMetricType.CONVERSION


@pytest.mark.regression
@pytest.mark.parametrize("value", ["mtype-not-a-type", "", "proportion"])
def test_an_unknown_value_is_refused_with_a_fixed_message(value):
    with pytest.raises(AnalysisConfigError) as raised:
        stored_metric_type(value)

    assert raised.value.field == "metrics"
    assert raised.value.message == UNKNOWN_METRIC_TYPE_MESSAGE
    assert UNKNOWN_METRIC_TYPE_MESSAGE == (
        "metric_type must be one of: conversion, revenue, count, duration, custom"
    )
