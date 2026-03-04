"""
Basic usage example: Experimentation Platform OpenFeature Python Provider.

Run with the virtual environment activated:
    source venv/bin/activate
    python examples/basic_usage.py
"""
from __future__ import annotations

import sys
import os

# Add src to path for running outside of an installed package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from openfeature import api
from openfeature.evaluation_context import EvaluationContext

from experimentation_openfeature import ExperimentationProvider


def main() -> None:
    # 1. Create and register the provider.
    provider = ExperimentationProvider(
        api_key=os.environ.get("EP_API_KEY", "your-api-key"),
        base_url=os.environ.get("EP_BASE_URL", "http://localhost:8000"),
        cache_ttl=300,   # Cache flags for 5 minutes.
        timeout=10,
    )
    api.set_provider(provider)

    # 2. Get a client.
    client = api.get_client()

    # 3. Build evaluation context for the current user.
    ctx = EvaluationContext(
        targeting_key="user-12345",
        attributes={
            "country": "US",
            "plan": "pro",
            "accountAge": 365,
        },
    )

    # 4. Evaluate flags — same API regardless of provider.
    dark_mode = client.get_boolean_value("dark-mode", False, ctx)
    print(f"dark-mode enabled: {dark_mode}")

    checkout_variant = client.get_string_value("checkout-experiment", "control", ctx)
    print(f"checkout-experiment variant: {checkout_variant}")

    max_items = client.get_integer_value("cart-max-items", 10, ctx)
    print(f"cart-max-items: {max_items}")

    price = client.get_float_value("feature-price-multiplier", 1.0, ctx)
    print(f"feature-price-multiplier: {price}")

    config = client.get_object_value("feature-config", {}, ctx)
    print(f"feature-config: {config}")


if __name__ == "__main__":
    main()
