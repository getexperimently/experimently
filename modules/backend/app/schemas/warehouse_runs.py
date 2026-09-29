"""Request bodies for warehouse analysis runs and source previews.

A run names what to analyse -- a connection, an assignment source and one to
ten metric sources -- and optionally the window and which warehouse variant
label is which experiment variant.  There is no field for SQL and none for a
limit: the statements are generated from the saved, validated sources, and
the limits are the connection's.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StringConstraints,
    model_validator,
)

from modules.backend.app.schemas.warehouse_sources import NAME_PATTERN

#: A variant label as the warehouse returns it: cut to 64 characters.
VariantLabel = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern=NAME_PATTERN)
]
EXPERIMENT_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
ExperimentKey = Annotated[
    str, StringConstraints(max_length=100, pattern=EXPERIMENT_KEY_PATTERN)
]

MAX_METRICS_PER_RUN = 10
MAX_VARIANT_MAP_ENTRIES = 50

_FORBID = ConfigDict(extra="forbid")


class _Window(BaseModel):
    model_config = _FORBID

    #: A value without a UTC offset is read as UTC.
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


class RunCreate(_Window):
    """``POST /experiments/{experiment_id}/runs``."""

    connection_id: uuid.UUID
    assignment_source_id: uuid.UUID
    #: The first is the primary metric.
    metric_source_ids: Annotated[
        list[uuid.UUID], Field(min_length=1, max_length=MAX_METRICS_PER_RUN)
    ]
    #: Warehouse variant label -> the experiment's variant id.  Labels not
    #: listed are matched to a variant by its name.
    variant_map: Optional[
        Annotated[
            dict[VariantLabel, uuid.UUID],
            Field(max_length=MAX_VARIANT_MAP_ENTRIES),
        ]
    ] = None
    confidence_level: Annotated[StrictFloat, Field(ge=0.80, le=0.99)] = 0.95
    correction_method: Literal["none", "bonferroni", "benjamini_hochberg"] = "none"

    @model_validator(mode="after")
    def _distinct_metrics(self) -> "RunCreate":
        if len(set(self.metric_source_ids)) != len(self.metric_source_ids):
            raise ValueError("metric_source_ids must not repeat a source")
        return self


class PreviewRequest(_Window):
    """``POST /sources/{id}/preview``.  The window defaults to the last 7 days;
    ``experiment_key`` narrows an assignment preview to one experiment."""

    experiment_key: Optional[ExperimentKey] = None
