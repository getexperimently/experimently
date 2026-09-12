"""
Lambda@Edge viewer-request handler for Split URL Testing — EP-036 Batch 1.

Deployed at a CloudFront viewer-request event to route users to different URLs
based on a deterministic hash of their client fingerprint (IP + User-Agent).

Experiment configuration is injected via a custom CloudFront header
``X-Split-URL-Config`` (set by the CDK CloudFront behaviour).

Flow:
1. Read experiment config from ``X-Split-URL-Config`` header.
2. If config is missing / invalid / has fewer than 2 variants → pass through.
3. Check for an existing assignment cookie.
   - If the cookie holds a known variant URL → pass through (no re-redirect).
   - If the cookie value is unknown → treat as a new user.
4. Hash client fingerprint to pick a variant.
5. If a holdout percentage is configured and the user falls inside it, redirect
   to the first (control) variant regardless of the normal assignment.
6. Return a 302 redirect to the assigned URL with:
   - ``Set-Cookie`` recording the assignment.
   - ``X-Split-URL-Variant`` naming the selected variant.
   - ``Cache-Control: no-store, no-cache`` to prevent CDN caching.
"""

import hashlib
import json
from typing import Any, Dict

COOKIE_PREFIX = "split_url_"


# ──────────────────────────────────────────────────────────────────────────
# Internal helpers (importable for unit testing)
# ──────────────────────────────────────────────────────────────────────────


def _parse_cookies(cookie_header: str) -> Dict[str, str]:
    """Parse a raw ``Cookie`` header string into a name→value dict.

    Args:
        cookie_header: The raw value of the ``Cookie`` HTTP header.

    Returns:
        A dictionary mapping cookie names to their values.
    """
    cookies: Dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def _hash_user(client_ip: str, user_agent: str, experiment_key: str) -> float:
    """Hash a viewer fingerprint to a float in [0, 1).

    Uses MD5 for speed (not security). The combination of IP, user-agent, and
    experiment key ensures independent bucketing across experiments.

    Args:
        client_ip: The viewer's IP address (from ``X-Forwarded-For``).
        user_agent: The viewer's ``User-Agent`` string.
        experiment_key: The experiment's unique key.

    Returns:
        A float in [0, 1) used for deterministic variant assignment.
    """
    fingerprint = f"{client_ip}:{user_agent}:{experiment_key}"
    digest = hashlib.md5(fingerprint.encode()).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def _pick_variant(user_hash: float, variants: list) -> dict:
    """Select a variant dict based on cumulative traffic allocation buckets.

    Args:
        user_hash: A float in [0, 1) representing the user's bucket.
        variants: List of variant dicts with a ``traffic_allocation`` key (0–100).

    Returns:
        The selected variant dict. Falls back to the last variant if floating-
        point rounding means no earlier bucket matched.
    """
    cumulative = 0.0
    for variant in variants:
        cumulative += variant.get("traffic_allocation", 0) / 100.0
        if user_hash < cumulative:
            return variant
    return variants[-1]


# ──────────────────────────────────────────────────────────────────────────
# Lambda entry-point
# ──────────────────────────────────────────────────────────────────────────


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda@Edge viewer-request handler.

    Args:
        event: CloudFront viewer-request event dict.
        context: Lambda execution context (unused).

    Returns:
        Either the original CloudFront request (pass-through) or a 302
        redirect response with assignment cookie and variant headers.
    """
    records = event.get("Records", [])
    if not records:
        return event

    request = records[0].get("cf", {}).get("request", {})
    headers = request.get("headers", {})

    # ── 1. Read experiment config ──────────────────────────────────────────
    config_header_entries = headers.get("x-split-url-config", [])
    if not config_header_entries:
        return request

    config_raw = config_header_entries[0].get("value", "")
    try:
        config: Dict[str, Any] = json.loads(config_raw)
    except (json.JSONDecodeError, ValueError):
        return request

    experiment_key: str = config.get("experiment_key", "")
    variants: list = config.get("variants", [])
    cookie_name: str = config.get("cookie_name") or f"{COOKIE_PREFIX}{experiment_key}"
    cookie_ttl_days: int = int(config.get("cookie_ttl_days", 30))
    holdout_percentage: float = float(config.get("holdout_percentage", 0))

    # ── 2. Guard: need at least 2 variants ────────────────────────────────
    if len(variants) < 2:
        return request

    # ── 3. Check for existing valid assignment cookie ──────────────────────
    cookie_str = (headers.get("cookie") or [{}])[0].get("value", "")
    cookies = _parse_cookies(cookie_str)

    if cookie_name in cookies:
        assigned_url = cookies[cookie_name]
        variant_urls = {v.get("url") for v in variants}
        if assigned_url in variant_urls:
            # Already assigned to a known variant → pass through
            return request
        # Cookie holds an unknown URL → fall through to re-assign

    # ── 4. Fingerprint-based hash ──────────────────────────────────────────
    client_ip = (headers.get("x-forwarded-for") or [{}])[0].get("value", "0.0.0.0")
    user_agent = (headers.get("user-agent") or [{}])[0].get("value", "")

    user_hash = _hash_user(client_ip, user_agent, experiment_key)

    # ── 5. Holdout check ──────────────────────────────────────────────────
    if holdout_percentage > 0:
        holdout_hash = _hash_user(client_ip, user_agent, f"{experiment_key}__holdout")
        if holdout_hash < holdout_percentage / 100.0:
            # User is in holdout → redirect to first (control) variant
            variant = variants[0]
            assigned_url = variant.get("url", "")
            variant_name = variant.get("name", "control")
        else:
            variant = _pick_variant(user_hash, variants)
            assigned_url = variant.get("url", "")
            variant_name = variant.get("name", "unknown")
    else:
        variant = _pick_variant(user_hash, variants)
        assigned_url = variant.get("url", "")
        variant_name = variant.get("name", "unknown")

    if not assigned_url:
        return request

    # ── 6. Build 302 redirect response ────────────────────────────────────
    max_age_seconds = cookie_ttl_days * 86400
    cookie_value = (
        f"{cookie_name}={assigned_url}; Max-Age={max_age_seconds}; Path=/; SameSite=Lax"
    )

    return {
        "status": "302",
        "statusDescription": "Found",
        "headers": {
            "location": [{"key": "Location", "value": assigned_url}],
            "set-cookie": [{"key": "Set-Cookie", "value": cookie_value}],
            "x-split-url-variant": [
                {"key": "X-Split-URL-Variant", "value": variant_name}
            ],
            "cache-control": [{"key": "Cache-Control", "value": "no-store, no-cache"}],
        },
    }
