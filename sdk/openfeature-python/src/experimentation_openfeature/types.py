"""
Internal types for the Experimentation Platform OpenFeature Provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProviderConfig:
    """Configuration for ExperimentationProvider."""

    api_key: str
    """API key used in X-API-Key header."""

    base_url: str = "http://localhost:8000"
    """Base URL of the Experimentation Platform API."""

    cache_ttl: int = 300
    """Cache TTL in seconds. Defaults to 5 minutes."""

    timeout: int = 10
    """HTTP request timeout in seconds."""


@dataclass
class FlagVariant:
    """A single variant within a feature flag."""

    key: str
    weight: float
    value: Any = None


@dataclass
class TargetingRule:
    """A targeting rule applied to decide flag audience."""

    attribute: str
    operator: str
    value: Any


@dataclass
class FeatureFlagDefinition:
    """Feature flag definition as returned by the platform API."""

    key: str
    enabled: bool
    rollout_percentage: float
    variants: List[FlagVariant] = field(default_factory=list)
    rules: List[TargetingRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FeatureFlagDefinition":
        """Deserialize from API response dict."""
        variants = [
            FlagVariant(
                key=v["key"],
                weight=v.get("weight", 0.0),
                value=v.get("value"),
            )
            for v in data.get("variants") or []
        ]
        rules = [
            TargetingRule(
                attribute=r["attribute"],
                operator=r["operator"],
                value=r["value"],
            )
            for r in data.get("rules") or []
        ]
        return cls(
            key=data["key"],
            enabled=data.get("enabled", False),
            rollout_percentage=float(data.get("rollout_percentage", 0.0)),
            variants=variants,
            rules=rules,
        )


@dataclass
class LocalEvalResult:
    """Result of a local flag evaluation."""

    value: Any
    """Resolved value."""

    variant: Optional[str]
    """Variant key if assigned, else None."""

    enabled: bool
    """Whether the flag is on for this user."""
