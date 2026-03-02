"""
Unit tests for ExperimentTemplateService.

Covers:
- list_templates() with and without type filter
- get_template() by ID
- recommend_template() keyword matching
- Structural validation of all templates in the library
"""

import pytest

from backend.app.services.experiment_template_service import (
    ExperimentTemplateService,
    ExperimentTemplate,
    TEMPLATE_LIBRARY,
)


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_list_templates_returns_all_five(self):
        """list_templates() with no filter returns all 5 templates."""
        templates = ExperimentTemplateService.list_templates()
        assert len(templates) == 5

    def test_list_templates_filters_by_checkout(self):
        """list_templates(type='checkout') returns only checkout templates."""
        templates = ExperimentTemplateService.list_templates(experiment_type="checkout")
        assert len(templates) > 0
        for t in templates:
            assert t.experiment_type == "checkout"

    def test_list_templates_filters_by_onboarding(self):
        """list_templates(type='onboarding') returns only onboarding templates."""
        templates = ExperimentTemplateService.list_templates(experiment_type="onboarding")
        assert len(templates) > 0
        for t in templates:
            assert t.experiment_type == "onboarding"

    def test_list_templates_returns_list_of_experiment_templates(self):
        """Each item in list_templates() is an ExperimentTemplate."""
        for t in ExperimentTemplateService.list_templates():
            assert isinstance(t, ExperimentTemplate)


# ---------------------------------------------------------------------------
# get_template
# ---------------------------------------------------------------------------

class TestGetTemplate:
    def test_get_template_by_id_returns_correct_template(self):
        """get_template('checkout-cta') returns the checkout CTA template."""
        template = ExperimentTemplateService.get_template("checkout-cta")
        assert template is not None
        assert template.id == "checkout-cta"
        assert template.experiment_type == "checkout"

    def test_get_template_unknown_id_returns_none(self):
        """get_template('unknown') returns None."""
        template = ExperimentTemplateService.get_template("unknown-template-id")
        assert template is None

    def test_get_template_onboarding_flow(self):
        """get_template('onboarding-flow') returns correct template."""
        template = ExperimentTemplateService.get_template("onboarding-flow")
        assert template is not None
        assert template.experiment_type == "onboarding"


# ---------------------------------------------------------------------------
# recommend_template
# ---------------------------------------------------------------------------

class TestRecommendTemplate:
    def test_recommend_checkout_template_for_checkout_description(self):
        """recommend_template with checkout-related description returns checkout template."""
        template = ExperimentTemplateService.recommend_template(
            "I want to test checkout button colours"
        )
        assert template is not None
        # The returned template should be relevant to checkout
        assert "checkout" in template.experiment_type or "ecommerce" in template.tags

    def test_recommend_returns_a_template(self):
        """recommend_template always returns a template (even for unmatched descriptions)."""
        template = ExperimentTemplateService.recommend_template(
            "Some completely unrelated description xyz"
        )
        assert template is not None
        assert isinstance(template, ExperimentTemplate)


# ---------------------------------------------------------------------------
# Structural validation of all templates
# ---------------------------------------------------------------------------

class TestTemplateStructure:
    def test_all_templates_have_required_fields(self):
        """All templates have non-empty required fields."""
        for t in TEMPLATE_LIBRARY:
            assert t.id, f"Template '{t.name}' has empty id"
            assert t.name, f"Template '{t.id}' has empty name"
            assert t.description, f"Template '{t.id}' has empty description"
            assert t.experiment_type, f"Template '{t.id}' has empty experiment_type"
            assert t.primary_metric, f"Template '{t.id}' has empty primary_metric"

    def test_all_templates_have_non_empty_tags(self):
        """All templates have at least one tag."""
        for t in TEMPLATE_LIBRARY:
            assert isinstance(t.tags, list), f"Template '{t.id}' tags is not a list"
            assert len(t.tags) > 0, f"Template '{t.id}' has empty tags"

    def test_all_templates_minimum_sample_size_positive(self):
        """minimum_sample_size > 0 for all templates."""
        for t in TEMPLATE_LIBRARY:
            assert t.minimum_sample_size > 0, (
                f"Template '{t.id}' has non-positive minimum_sample_size"
            )

    def test_all_templates_duration_positive(self):
        """recommended_duration_days > 0 for all templates."""
        for t in TEMPLATE_LIBRARY:
            assert t.recommended_duration_days > 0, (
                f"Template '{t.id}' has non-positive recommended_duration_days"
            )

    def test_all_templates_effect_size_valid(self):
        """expected_effect_size > 0 and < 1 for all templates."""
        for t in TEMPLATE_LIBRARY:
            assert 0 < t.expected_effect_size < 1, (
                f"Template '{t.id}' has invalid expected_effect_size {t.expected_effect_size}"
            )

    def test_template_ids_are_unique(self):
        """All template IDs are unique."""
        ids = [t.id for t in TEMPLATE_LIBRARY]
        assert len(ids) == len(set(ids)), "Duplicate template IDs found"

    def test_template_names_are_unique(self):
        """All template names are unique."""
        names = [t.name for t in TEMPLATE_LIBRARY]
        assert len(names) == len(set(names)), "Duplicate template names found"

    def test_all_templates_have_guardrail_metrics(self):
        """All templates have at least one guardrail metric."""
        for t in TEMPLATE_LIBRARY:
            assert isinstance(t.guardrail_metrics, list)
            assert len(t.guardrail_metrics) > 0, (
                f"Template '{t.id}' has no guardrail metrics"
            )

    def test_all_templates_have_variant_descriptions(self):
        """All templates have at least 2 variant descriptions."""
        for t in TEMPLATE_LIBRARY:
            assert isinstance(t.variant_descriptions, list)
            assert len(t.variant_descriptions) >= 2, (
                f"Template '{t.id}' has fewer than 2 variant descriptions"
            )
