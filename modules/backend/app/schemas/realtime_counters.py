"""
Pydantic schemas for real-time DynamoDB counters (P2-B).

These schemas define the request/response models for the real-time
counter system that tracks assignments, events, and conversions
per experiment variant using DynamoDB atomic counters.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CounterType(str, Enum):
    """Type of counter to increment."""

    ASSIGNMENT = "assignment"
    EVENT = "event"
    CONVERSION = "conversion"


class VariantCounters(BaseModel):
    """Real-time counters for a single experiment variant."""

    model_config = ConfigDict(from_attributes=True)

    variant_id: str
    variant_name: str
    is_control: bool
    assignments: int = 0
    events: int = 0
    conversions: int = 0
    conversion_rate: float = 0.0  # conversions / assignments if assignments > 0


class ExperimentCounters(BaseModel):
    """Aggregated real-time counters for an experiment across all variants."""

    experiment_id: str
    experiment_name: Optional[str] = None
    total_assignments: int
    total_events: int
    total_conversions: int
    variants: list[VariantCounters]
    last_updated: Optional[str] = None  # ISO timestamp from DynamoDB


class IncrementRequest(BaseModel):
    """Request to increment a single counter."""

    experiment_id: str
    variant_id: str
    counter_type: CounterType
    amount: int = Field(default=1, ge=1, le=1000)


class IncrementResponse(BaseModel):
    """Response after incrementing a counter."""

    experiment_id: str
    variant_id: str
    counter_type: CounterType
    new_value: int


class BulkIncrementRequest(BaseModel):
    """Request to increment multiple counters in a single operation."""

    increments: list[IncrementRequest] = Field(..., min_length=1, max_length=100)


class BulkIncrementResponse(BaseModel):
    """Response after a bulk increment operation."""

    processed: int
    failed: int
    results: list[IncrementResponse]


class CounterResetRequest(BaseModel):
    """Request to reset one or more counters to zero."""

    experiment_id: str
    variant_id: Optional[str] = None  # None = reset all variants
    counter_type: Optional[CounterType] = None  # None = reset all counter types
    reason: str = Field(..., min_length=1, max_length=256)
