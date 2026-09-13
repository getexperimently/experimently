"""
Pydantic schemas for Split URL experiment *configuration* — EP-036 Batch 1.

Defines the data structures for split URL experiment configuration,
including URL variants, traffic allocation, and cookie settings.

CORE. This module is pure declarative validation (at least two variants,
allocations summing to 100) with no routing behaviour, and it types
``ExperimentCreate.split_url_config`` / ``ExperimentUpdate.split_url_config``.
Keeping it in the core is what stops that field degrading to unvalidated
JSON when the split_url module is not installed. The routing itself —
``services/split_url_service`` and the preview endpoint — is the module's.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class SplitUrlVariant(BaseModel):
    """A single URL variant in a split URL experiment."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    url: str
    traffic_allocation: float  # Percentage: 0–100


class SplitUrlConfig(BaseModel):
    """
    Configuration for a split URL experiment.

    Requires at least 2 URL variants whose traffic_allocation values sum to 100.
    """

    model_config = ConfigDict(from_attributes=True)

    variants: List[SplitUrlVariant]
    cookie_name: Optional[str] = None  # Auto-generated from experiment_key if not set
    cookie_ttl_days: int = 30
    canonical_url: Optional[str] = (
        None  # Injected as <link rel="canonical"> in served page
    )

    @field_validator("variants")
    @classmethod
    def validate_variants(cls, v: List[SplitUrlVariant]) -> List[SplitUrlVariant]:
        """Ensure at least 2 URL variants are provided."""
        if len(v) < 2:
            raise ValueError("At least 2 URL variants required")
        return v

    @model_validator(mode="after")
    def validate_traffic_sum(self) -> "SplitUrlConfig":
        """Ensure traffic allocations sum to 100 (within floating-point tolerance)."""
        total = sum(v.traffic_allocation for v in self.variants)
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Traffic allocations must sum to 100, got {total}")
        return self
