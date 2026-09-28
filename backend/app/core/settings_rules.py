"""The rules the settings enforce, with no settings object behind them.

``backend.app.core.config`` builds its settings when it is imported, so
importing it in a deployment with a bad secret raises before the importer can
do anything else.  The container's start-up check
(``backend.app.core.preflight``) has to apply the *same* rules to an
environment that may be that deployment, so the rules live here, in a module
whose import does nothing but define them.  ``config.py`` and
``modules/backend/app/settings.py`` use these definitions, so the start-up
check and the settings cannot disagree about what a placeholder is.

Standard library only: this is imported by a process that has not yet
decided whether the environment is fit to start.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

#: Minimum length of SECRET_KEY and AUDIT_HMAC_KEY in staging/production.
MIN_SECRET_KEY_LENGTH = 32

#: Minimum length of FIRST_SUPERUSER_PASSWORD in staging/production.
MIN_SUPERUSER_PASSWORD_LENGTH = 8

#: Environments that must not run with placeholder secrets or demo passwords.
HARDENED_ENVIRONMENTS: tuple = ("staging", "production")

#: The canonical environment names.
CANONICAL_ENVIRONMENTS: tuple = ("development", "test", "staging", "production")

#: Environments in which a weak first-administrator password is accepted, and
#: then only when ENVIRONMENT was set rather than defaulted.
WEAK_SUPERUSER_PASSWORD_ENVIRONMENTS: tuple = ("development", "test")

#: What the API says, and then stops, when ENVIRONMENT was never set.
ENVIRONMENT_NOT_SET_MESSAGE = (
    "ENVIRONMENT is not set: set it to development, test, staging or "
    "production before starting the API."
)

#: What the bootstrap says when it will not create the first administrator.
WEAK_FIRST_SUPERUSER_PASSWORD_MESSAGE = (
    "FIRST_SUPERUSER_PASSWORD is a well-known default or shorter than "
    f"{MIN_SUPERUSER_PASSWORD_LENGTH} characters, which is accepted only with "
    "ENVIRONMENT=development or ENVIRONMENT=test. Set a stronger "
    "FIRST_SUPERUSER_PASSWORD, or set ENVIRONMENT."
)

#: Legacy spelling -> canonical spelling.
LEGACY_ENVIRONMENT_ALIASES: Dict[str, str] = {
    "dev": "development",
    "prod": "production",
    # The AWS demo stack (`ENVIRONMENT=demo cdk deploy`, infrastructure/cdk/
    # app.py) runs with APP_ENV=demo: a public, seeded development-grade
    # deployment.
    "demo": "development",
}

#: The dotenv file each environment's settings class reads.
ENV_FILES: Dict[str, str] = {
    "development": ".env.dev",
    "test": ".env.test",
    "staging": ".env.prod",
    "production": ".env.prod",
}

# Placeholder secrets that ship in the repository (class defaults,
# docker-compose.yml, .env.example) or are otherwise well known.  Any secret
# equal to one of these, or starting with one of the prefixes, is refused in
# HARDENED_ENVIRONMENTS regardless of its length.
PLACEHOLDER_SECRETS: frozenset = frozenset(
    {
        "",
        "secret",
        "changeme",
        "change-me",
        "password",
        "supersecret",
        "default-secret-key-for-testing",
        "development_secret_key_change_in_production",
        "dev-audit-key-change-in-production",
    }
)
PLACEHOLDER_SECRET_PREFIXES: tuple = (
    "dev-only-",
    "dev-audit-",
    "development_secret",
    "default-secret",
    "ci-only-",
    "test-",
)

#: First-administrator passwords refused in staging/production whatever their
#: length.  ``Demo1234!`` is the seeded demo password and appears in the
#: public docs and docker-compose.yml.  Compared lower-cased.
WEAK_SUPERUSER_PASSWORDS: frozenset = frozenset(
    {"admin", "password", "changeme", "admin123", "", "demo1234!"}
)

#: The example PUBLIC_BASE_URL every message gives: the dashboard's URL, which
#: is also where the API is served (under /api).  Never an ``api.`` host.
PUBLIC_BASE_URL_EXAMPLE = "https://experimently.example.com"


#: The strings pydantic's ``bool`` reads as False (case-insensitive, exact).
#: backend/tests/unit/core/test_settings_rules_testing_flag.py pins this
#: against pydantic itself.
_FALSE_WORDS: frozenset = frozenset({"0", "off", "f", "false", "n", "no"})


def testing_flag_is_set(value: Optional[str]) -> bool:
    """Whether a raw ``TESTING`` value turns the test runner's flag on.

    Unset or empty is off, and so is anything pydantic's ``bool`` reads as
    False (``0``, ``off``, ``f``, ``false``, ``n``, ``no``, in any case).
    Everything else is on: what pydantic reads as True (``1``, ``true``,
    ``on``, ``t``, ``y``, ``yes``, in any case) and, failing closed, any other
    non-empty value, such as ``" true"`` or ``enabled``.
    """
    if value is None or value == "":
        return False
    return value.lower() not in _FALSE_WORDS


def testing_refusal(environment: Any, testing: Optional[str]) -> Optional[str]:
    """The refusal for ``TESTING`` with a staging/production environment, or None.

    *environment* is the canonical name; *testing* the raw ``TESTING`` value
    from the process environment. The settings (``config.Settings``) raise
    with this message and the container's start-up check prints it, so the
    two cannot disagree.
    """
    if environment not in HARDENED_ENVIRONMENTS or not testing_flag_is_set(testing):
        return None
    return (
        f"TESTING is for the test runner and cannot be combined with "
        f"ENVIRONMENT={environment}. Remove TESTING from this deployment's "
        "configuration."
    )


def secret_is_placeholder(value: Optional[str]) -> bool:
    """True when *value* is a committed/well-known placeholder secret."""
    normalised = (value or "").strip().lower()
    if normalised in PLACEHOLDER_SECRETS:
        return True
    return any(normalised.startswith(prefix) for prefix in PLACEHOLDER_SECRET_PREFIXES)


def secret_is_weak(value: Optional[str]) -> bool:
    """A SECRET_KEY or AUDIT_HMAC_KEY that staging/production refuse."""
    return secret_is_placeholder(value) or len(value or "") < MIN_SECRET_KEY_LENGTH


def superuser_password_is_weak(value: Optional[str]) -> bool:
    """A FIRST_SUPERUSER_PASSWORD that staging/production refuse."""
    value = value or ""
    return (
        value.lower() in WEAK_SUPERUSER_PASSWORDS
        or len(value) < MIN_SUPERUSER_PASSWORD_LENGTH
    )


def canonical_environment_quiet(value: str) -> str:
    """The canonical spelling of an environment name, without a warning."""
    normalised = value.strip().lower()
    return LEGACY_ENVIRONMENT_ALIASES.get(normalised, normalised)


def public_base_url_error(value: str) -> Optional[str]:
    """Why *value* is not a usable PUBLIC_BASE_URL, or ``None`` if it is.

    A scheme and a host, no path.  *value* is non-empty; the caller decides
    what an empty one means.
    """
    candidate = value.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return (
            "PUBLIC_BASE_URL must be an absolute http(s) URL with a host, "
            f"e.g. {PUBLIC_BASE_URL_EXAMPLE} (the dashboard's URL) -- got {value!r}"
        )
    if parsed.path:
        return (
            "PUBLIC_BASE_URL must not carry a path; it is the origin the "
            f"service is reached at -- got {value!r}"
        )
    return None


def parse_allowed_hosts(value: Any) -> List[str]:
    """ALLOWED_HOSTS as a list: comma-separated or a JSON array.

    The spelling CORS_ORIGINS also takes. Blank entries are dropped. Raises
    ``ValueError`` (``json.JSONDecodeError``) on a value that starts like a
    JSON array but is not one.
    """
    if isinstance(value, str) and value.strip().startswith("["):
        value = json.loads(value)
    if isinstance(value, str) and value:
        return [i.strip() for i in value.split(",") if i.strip()]
    if isinstance(value, list):
        return [str(i).strip() for i in value if str(i).strip()]
    return []


def allowed_host_pattern_error(pattern: str) -> Optional[str]:
    """Why an ALLOWED_HOSTS entry can never match, or ``None`` if it can.

    A wildcard written `*example.com` (no dot) is not a wildcard: it is a
    literal hostname containing an asterisk, it matches nothing, and a
    deployment configured with it refuses every request while every health
    check stays green -- because the probes are exempt.

    Accepted: `example.com`, `*.example.com`, and `*` (meaningful, "allow
    anything"; staging and production refuse it separately). Refused in every
    environment: any other `*`, and a leading dot.
    """
    if pattern == "*":
        return None
    if pattern.startswith("*."):
        rest = pattern[2:]
        if rest and "*" not in rest:
            return None
    elif "*" not in pattern and not pattern.startswith("."):
        return None
    return (
        f"ALLOWED_HOSTS entry {pattern[:200]!r} is not a hostname or a `*.` "
        "wildcard and would match nothing, refusing every request while "
        "the health probes -- which are exempt -- stayed green. Write "
        "`example.com` or `*.example.com`."
    )
