"""
experimentation-openfeature: OpenFeature provider for the Experimentation Platform.

Usage:
    from openfeature import api
    from experimentation_openfeature import ExperimentationProvider

    api.set_provider(ExperimentationProvider(api_key="your-api-key"))
    client = api.get_client()
    enabled = client.get_boolean_value("my-flag", False)
"""

from .provider import ExperimentationProvider
from .types import ProviderConfig

__all__ = ["ExperimentationProvider", "ProviderConfig"]
__version__ = "0.1.0"
