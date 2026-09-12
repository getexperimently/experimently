"""
Service layer for Split URL Testing — EP-036 Batch 1.

Provides deterministic, consistent user assignment to URL variants using
MD5 hashing of the user ID combined with the experiment key.
"""

import hashlib

from backend.app.schemas.split_url import SplitUrlConfig, SplitUrlVariant


def get_cookie_name(experiment_key: str) -> str:
    """Generate a deterministic cookie name from an experiment key.

    Args:
        experiment_key: The unique key identifying the experiment.

    Returns:
        A cookie name string prefixed with ``split_url_``.
    """
    return f"split_url_{experiment_key}"


def hash_user(user_id: str, experiment_key: str) -> float:
    """Hash a user ID + experiment key to a float in [0, 1).

    Uses MD5 for speed (not security); the combination of user_id and
    experiment_key ensures independent bucketing across experiments.

    Args:
        user_id: Unique identifier for the user.
        experiment_key: The experiment's unique key.

    Returns:
        A float in [0, 1) used for deterministic variant assignment.
    """
    raw = f"{user_id}:{experiment_key}".encode()
    digest = hashlib.md5(raw, usedforsecurity=False).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def get_url_variant(
    user_id: str, experiment_key: str, config: SplitUrlConfig
) -> SplitUrlVariant:
    """Deterministically assign a user to a URL variant.

    The assignment is stable: the same (user_id, experiment_key) pair always
    yields the same variant, enabling consistent redirect behaviour across
    requests without requiring server-side session storage.

    Args:
        user_id: Unique identifier for the user.
        experiment_key: The experiment's unique key.
        config: The split URL experiment configuration.

    Returns:
        The :class:`SplitUrlVariant` assigned to this user.
    """
    user_hash = hash_user(user_id, experiment_key)
    cumulative = 0.0
    for variant in config.variants:
        cumulative += variant.traffic_allocation / 100.0
        if user_hash < cumulative:
            return variant
    # Fallback — handles floating-point edge cases where cumulative never exceeds hash
    return config.variants[-1]
