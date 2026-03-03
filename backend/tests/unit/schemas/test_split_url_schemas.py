"""
Unit tests for split_url Pydantic schemas — EP-036 Batch 1.

Tests cover:
- SplitUrlVariant field validation
- SplitUrlConfig: requires >= 2 variants
- SplitUrlConfig: traffic allocations must sum to 100
- SplitUrlConfig: optional fields (cookie_name, cookie_ttl_days, canonical_url)
- SplitUrlExperimentCreate inheriting from ExperimentCreate
"""
import pytest
from pydantic import ValidationError

# These imports will FAIL (red phase) until the implementation exists.
from backend.app.schemas.split_url import (
    SplitUrlVariant,
    SplitUrlConfig,
)


# ──────────────────────────────────────────────────────────────────────────
# SplitUrlVariant
# ──────────────────────────────────────────────────────────────────────────

class TestSplitUrlVariant:
    def test_valid_variant(self):
        v = SplitUrlVariant(
            name="control",
            url="https://example.com/control",
            traffic_allocation=50.0,
        )
        assert v.name == "control"
        assert v.url == "https://example.com/control"
        assert v.traffic_allocation == 50.0

    def test_variant_missing_name_raises(self):
        with pytest.raises(ValidationError):
            SplitUrlVariant(url="https://example.com", traffic_allocation=50.0)

    def test_variant_missing_url_raises(self):
        with pytest.raises(ValidationError):
            SplitUrlVariant(name="v1", traffic_allocation=50.0)

    def test_variant_missing_allocation_raises(self):
        with pytest.raises(ValidationError):
            SplitUrlVariant(name="v1", url="https://example.com")

    def test_variant_zero_allocation_allowed(self):
        # A zero allocation variant should be creatable (validation at config level)
        v = SplitUrlVariant(name="v1", url="https://example.com", traffic_allocation=0.0)
        assert v.traffic_allocation == 0.0

    def test_variant_100_allocation_allowed(self):
        v = SplitUrlVariant(name="v1", url="https://example.com", traffic_allocation=100.0)
        assert v.traffic_allocation == 100.0

    def test_variant_from_attributes(self):
        """ConfigDict(from_attributes=True) allows ORM object hydration."""

        class FakeOrm:
            name = "treatment"
            url = "https://example.com/t"
            traffic_allocation = 30.0

        v = SplitUrlVariant.model_validate(FakeOrm())
        assert v.name == "treatment"


# ──────────────────────────────────────────────────────────────────────────
# SplitUrlConfig — variant count validation
# ──────────────────────────────────────────────────────────────────────────

class TestSplitUrlConfigVariantCount:
    def _make_variant(self, name: str, url: str, alloc: float) -> SplitUrlVariant:
        return SplitUrlVariant(name=name, url=url, traffic_allocation=alloc)

    def test_two_variants_valid(self):
        config = SplitUrlConfig(
            variants=[
                self._make_variant("a", "https://example.com/a", 50.0),
                self._make_variant("b", "https://example.com/b", 50.0),
            ]
        )
        assert len(config.variants) == 2

    def test_three_variants_valid(self):
        config = SplitUrlConfig(
            variants=[
                self._make_variant("a", "https://example.com/a", 33.34),
                self._make_variant("b", "https://example.com/b", 33.33),
                self._make_variant("c", "https://example.com/c", 33.33),
            ]
        )
        assert len(config.variants) == 3

    def test_one_variant_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SplitUrlConfig(
                variants=[
                    self._make_variant("only", "https://example.com", 100.0)
                ]
            )
        assert "2" in str(exc_info.value) or "variant" in str(exc_info.value).lower()

    def test_zero_variants_raises(self):
        with pytest.raises(ValidationError):
            SplitUrlConfig(variants=[])


# ──────────────────────────────────────────────────────────────────────────
# SplitUrlConfig — traffic allocation sum validation
# ──────────────────────────────────────────────────────────────────────────

class TestSplitUrlConfigTrafficSum:
    def _make_variant(self, name: str, url: str, alloc: float) -> SplitUrlVariant:
        return SplitUrlVariant(name=name, url=url, traffic_allocation=alloc)

    def test_exact_100_valid(self):
        config = SplitUrlConfig(
            variants=[
                self._make_variant("a", "https://example.com/a", 50.0),
                self._make_variant("b", "https://example.com/b", 50.0),
            ]
        )
        assert config is not None

    def test_sum_less_than_100_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            SplitUrlConfig(
                variants=[
                    self._make_variant("a", "https://example.com/a", 40.0),
                    self._make_variant("b", "https://example.com/b", 40.0),
                ]
            )
        assert "100" in str(exc_info.value) or "sum" in str(exc_info.value).lower()

    def test_sum_greater_than_100_raises(self):
        with pytest.raises(ValidationError):
            SplitUrlConfig(
                variants=[
                    self._make_variant("a", "https://example.com/a", 60.0),
                    self._make_variant("b", "https://example.com/b", 60.0),
                ]
            )

    def test_floating_point_tolerance(self):
        """Sums like 33.34 + 33.33 + 33.33 = 100.00 must be accepted."""
        config = SplitUrlConfig(
            variants=[
                self._make_variant("a", "https://example.com/a", 33.34),
                self._make_variant("b", "https://example.com/b", 33.33),
                self._make_variant("c", "https://example.com/c", 33.33),
            ]
        )
        assert len(config.variants) == 3


# ──────────────────────────────────────────────────────────────────────────
# SplitUrlConfig — optional fields
# ──────────────────────────────────────────────────────────────────────────

class TestSplitUrlConfigOptionalFields:
    def _two_variant_config_kwargs(self):
        return {
            "variants": [
                SplitUrlVariant(name="a", url="https://example.com/a", traffic_allocation=50.0),
                SplitUrlVariant(name="b", url="https://example.com/b", traffic_allocation=50.0),
            ]
        }

    def test_cookie_name_defaults_to_none(self):
        config = SplitUrlConfig(**self._two_variant_config_kwargs())
        assert config.cookie_name is None

    def test_cookie_name_can_be_set(self):
        config = SplitUrlConfig(cookie_name="my_cookie", **self._two_variant_config_kwargs())
        assert config.cookie_name == "my_cookie"

    def test_cookie_ttl_days_default_30(self):
        config = SplitUrlConfig(**self._two_variant_config_kwargs())
        assert config.cookie_ttl_days == 30

    def test_cookie_ttl_days_custom(self):
        config = SplitUrlConfig(cookie_ttl_days=7, **self._two_variant_config_kwargs())
        assert config.cookie_ttl_days == 7

    def test_canonical_url_defaults_to_none(self):
        config = SplitUrlConfig(**self._two_variant_config_kwargs())
        assert config.canonical_url is None

    def test_canonical_url_can_be_set(self):
        config = SplitUrlConfig(
            canonical_url="https://example.com/canonical",
            **self._two_variant_config_kwargs(),
        )
        assert config.canonical_url == "https://example.com/canonical"

    def test_from_attributes_mode(self):
        """ConfigDict(from_attributes=True) must be set on SplitUrlConfig."""

        class FakeOrm:
            variants = [
                SplitUrlVariant(name="a", url="https://example.com/a", traffic_allocation=50.0),
                SplitUrlVariant(name="b", url="https://example.com/b", traffic_allocation=50.0),
            ]
            cookie_name = None
            cookie_ttl_days = 30
            canonical_url = None

        config = SplitUrlConfig.model_validate(FakeOrm())
        assert len(config.variants) == 2
