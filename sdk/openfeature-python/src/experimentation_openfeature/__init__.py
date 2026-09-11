"""
experimentation-openfeature: OpenFeature provider for the Experimentation Platform.

Flags are evaluated by the server through the ``experimentation`` SDK
(``GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=<targeting_key>``).

Usage:
    from openfeature import api
    from openfeature.evaluation_context import EvaluationContext
    from experimentation_openfeature import ExperimentationProvider

    api.set_provider(ExperimentationProvider(api_key="your-api-key"))
    client = api.get_client()
    enabled = client.get_boolean_value("my-flag", False, EvaluationContext("user-123"))
"""

from .evaluator import hash_user
from .provider import PROVIDER_NAME, ExperimentationProvider
from .types import ProviderConfig

__all__ = ["ExperimentationProvider", "PROVIDER_NAME", "ProviderConfig", "hash_user"]
__version__ = "1.0.0"
