"""``ALARM_EMAIL``: the one address the monitoring topic emails (DECISIONS D21).

Every alarm publishes to the topic ``experimentation-alerts-<env>``, including
the two alarms that make CodeDeploy roll the API back by itself
(``experimentation-api-5xx-{blue,green}-<env>``). Its only subscriber used to be
the literal ``alerts@example.com``, so every alarm, rollbacks included, told
nobody.

The address is a setting, read by ``app.py`` from the environment, and never
written in code:

* **staging and prod:** required. Synth refuses to run without one.
* **dev and demo:** optional. Absent (or blank) means the topic has **no**
  subscription at all, not a placeholder.

Whenever a value is given, it is checked. It is refused when it is longer than
254 characters, contains whitespace, has other than exactly one ``@``, has an
empty part on either side of it, has a domain with no dot, or its domain is
``example.com``, ``example.net`` or ``example.org`` or a subdomain of one
(case-insensitive, a trailing dot ignored). These are deliberately plain string
checks, not a full address grammar: they exist to stop a placeholder or a typo
reaching a deployed topic, and AWS makes the final check when it sends the
confirmation mail.
"""

from __future__ import annotations

#: The environments that refuse to synthesise without ``ALARM_EMAIL``.
ALARM_EMAIL_REQUIRED = frozenset({"staging", "prod"})

#: RFC 5321's limit on a forward path, which is what an address can be.
MAX_LENGTH = 254

#: The documentation domains (RFC 2606). Mail to them goes nowhere.
EXAMPLE_DOMAINS = ("example.com", "example.net", "example.org")

HOW_TO_SET = (
    "Set it before any cdk synth, diff, deploy or destroy, e.g. "
    "`export ALARM_EMAIL=ops@your-domain.com`. SNS then mails that address a "
    "confirmation link; until it is confirmed (preferably with "
    "`aws sns confirm-subscription --authenticate-on-unsubscribe true`) no "
    "alarm reaches it. See docs/self-hosting/cdk.md."
)


def _refuse(env_name: str, why: str) -> ValueError:
    return ValueError(
        f"ALARM_EMAIL {why} (ENVIRONMENT={env_name}). It is the address every "
        "CloudWatch alarm, including an automatic API rollback, is emailed to. "
        + HOW_TO_SET
    )


def resolve_alarm_email(value: str | None, env_name: str) -> str | None:
    """The address to subscribe, ``None`` for no subscription, or ``ValueError``."""
    if value is None or not value.strip():
        if env_name in ALARM_EMAIL_REQUIRED:
            raise _refuse(env_name, f"is required in {env_name} and is not set")
        return None
    if len(value) > MAX_LENGTH:
        raise _refuse(env_name, f"is longer than {MAX_LENGTH} characters")
    if any(character.isspace() for character in value):
        raise _refuse(env_name, "contains whitespace")
    if value.count("@") != 1:
        raise _refuse(env_name, "must contain exactly one '@'")
    local, domain = value.split("@")
    if not local or not domain:
        raise _refuse(env_name, "needs a name before the '@' and a domain after it")
    if "." not in domain:
        raise _refuse(env_name, "has a domain with no dot")
    normalised = domain.lower().rstrip(".")
    for example in EXAMPLE_DOMAINS:
        if normalised == example or normalised.endswith("." + example):
            raise _refuse(
                env_name,
                f"is a placeholder address at {example}, which delivers to nobody",
            )
    return value
