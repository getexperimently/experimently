"""
Experiment Template Library.

Pre-built experiment designs for common use-cases.
Each template provides a starting point with sensible defaults
for metrics, sample size, and variant descriptions.
"""

from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ExperimentTemplate:
    """A pre-built experiment design template."""

    id: str
    name: str
    description: str
    experiment_type: str  # checkout | onboarding | pricing | email | landing_page
    primary_metric: str
    guardrail_metrics: List[str]
    recommended_duration_days: int
    minimum_sample_size: int
    expected_effect_size: float  # typical MDE for this type
    variant_descriptions: List[str]
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------

TEMPLATE_LIBRARY: List[ExperimentTemplate] = [
    ExperimentTemplate(
        id="checkout-cta",
        name="Checkout CTA Button Test",
        description="Test different call-to-action button text/colour on checkout page",
        experiment_type="checkout",
        primary_metric="conversion_rate",
        guardrail_metrics=["revenue_per_user", "cart_abandonment_rate"],
        recommended_duration_days=14,
        minimum_sample_size=1000,
        expected_effect_size=0.02,
        variant_descriptions=["Control: current CTA", "Variant A: new CTA text/style"],
        tags=["ecommerce", "conversion", "ux", "checkout"],
    ),
    ExperimentTemplate(
        id="onboarding-flow",
        name="Onboarding Flow Optimisation",
        description="Test streamlined vs. detailed onboarding for new users",
        experiment_type="onboarding",
        primary_metric="activation_rate",
        guardrail_metrics=["day7_retention", "support_tickets"],
        recommended_duration_days=21,
        minimum_sample_size=500,
        expected_effect_size=0.05,
        variant_descriptions=[
            "Control: 5-step onboarding",
            "Variant A: 3-step onboarding",
        ],
        tags=["onboarding", "activation", "retention"],
    ),
    ExperimentTemplate(
        id="pricing-display",
        name="Pricing Page Layout Test",
        description="Test different pricing page layouts and feature highlighting",
        experiment_type="pricing",
        primary_metric="conversion_rate",
        guardrail_metrics=["churn_rate", "revenue_per_user"],
        recommended_duration_days=14,
        minimum_sample_size=2000,
        expected_effect_size=0.01,
        variant_descriptions=[
            "Control: current pricing layout",
            "Variant A: new layout with value props",
        ],
        tags=["pricing", "revenue", "saas"],
    ),
    ExperimentTemplate(
        id="email-subject",
        name="Email Subject Line Test",
        description="Test personalised vs. generic email subject lines",
        experiment_type="email",
        primary_metric="open_rate",
        guardrail_metrics=["click_through_rate", "unsubscribe_rate"],
        recommended_duration_days=7,
        minimum_sample_size=5000,
        expected_effect_size=0.02,
        variant_descriptions=[
            "Control: generic subject",
            "Variant A: personalised subject",
        ],
        tags=["email", "engagement", "marketing"],
    ),
    ExperimentTemplate(
        id="landing-page-hero",
        name="Landing Page Hero Section Test",
        description="Test different hero images/headlines on main landing page",
        experiment_type="landing_page",
        primary_metric="conversion_rate",
        guardrail_metrics=["bounce_rate", "time_on_page"],
        recommended_duration_days=14,
        minimum_sample_size=3000,
        expected_effect_size=0.02,
        variant_descriptions=[
            "Control: current hero",
            "Variant A: new hero with social proof",
        ],
        tags=["landing-page", "acquisition", "conversion"],
    ),
]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class ExperimentTemplateService:
    """Service for querying and recommending experiment templates."""

    @staticmethod
    def list_templates(
        experiment_type: Optional[str] = None,
    ) -> List[ExperimentTemplate]:
        """
        List all templates, optionally filtered by experiment type.

        Args:
            experiment_type: If provided, only templates of this type are returned.

        Returns:
            List of matching ExperimentTemplate objects.
        """
        if experiment_type:
            return [t for t in TEMPLATE_LIBRARY if t.experiment_type == experiment_type]
        return list(TEMPLATE_LIBRARY)

    @staticmethod
    def get_template(template_id: str) -> Optional[ExperimentTemplate]:
        """
        Retrieve a single template by its ID.

        Args:
            template_id: Unique template identifier (e.g. 'checkout-cta').

        Returns:
            ExperimentTemplate if found, else None.
        """
        return next((t for t in TEMPLATE_LIBRARY if t.id == template_id), None)

    @staticmethod
    def recommend_template(description: str) -> Optional[ExperimentTemplate]:
        """
        Recommend a template based on keyword matching in the description.

        Searches each template's tags and experiment_type for keyword hits.
        Falls back to the first template in the library if no match is found.

        Args:
            description: Natural language experiment description.

        Returns:
            Best-matching ExperimentTemplate, or the first template as default.
        """
        desc_lower = description.lower()
        for template in TEMPLATE_LIBRARY:
            # Check tags
            if any(tag in desc_lower for tag in template.tags):
                return template
            # Also check experiment_type keyword
            if template.experiment_type in desc_lower:
                return template
        # Default: return the first template
        return TEMPLATE_LIBRARY[0] if TEMPLATE_LIBRARY else None
