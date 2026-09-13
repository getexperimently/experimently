"""Authenticating an inbound integration webhook.

``POST /api/v1/integrations/webhooks/{jira,salesforce,github}`` are the only
routes in the platform an anonymous caller can reach with a body of its own
choosing, so the *sender* is authenticated here before anything reads the
payload.

The shared secret is the ``webhook_secret`` key of
:attr:`IntegrationConfig.encrypted_config` — the field GitHub's signature
check already used; nothing new is stored.  A sender presents it one of two
ways:

signature
    HMAC-SHA256 over the **raw** request body, hex, prefixed ``sha256=``, in
    ``X-Hub-Signature-256`` (GitHub) or ``X-Hub-Signature`` (Jira Cloud).
    This is the only form GitHub sends and the only one accepted for it.

shared secret
    The secret itself, in ``X-Experimently-Webhook-Secret``.  A Salesforce
    outbound message cannot compute an HMAC over the body it sends, and
    neither can a Jira Server webhook; a custom header is what they *can*
    set.  It is weaker than a signature — replayable, and it puts the secret
    on the wire — so only those two providers accept it, and only over TLS.

Both comparisons are constant-time (:func:`hmac.compare_digest`, the way
``backend/app/core/security.py`` and ``backend/app/core/health.py`` do it) and
run on **bytes**: Starlette decodes headers as latin-1 and ``compare_digest``
raises ``TypeError`` on a non-ASCII ``str``, so comparing the decoded header
directly would let any sender turn a header into a 500.

An integration with no ``webhook_secret`` configured cannot authenticate
anybody: every function here answers ``False``, and the route answers 401.
That is deliberate — an unauthenticated webhook is an anonymous write path
into the platform, so "no secret configured" must fail closed.
"""

from __future__ import annotations

import hashlib
import hmac

#: The only digest a signature header may name.
SIGNATURE_PREFIX = "sha256="

#: Header a sender that cannot sign its body presents the shared secret in.
SHARED_SECRET_HEADER = "X-Experimently-Webhook-Secret"

#: Signature headers, in the order they are consulted.  GitHub sends
#: ``X-Hub-Signature-256``; Jira Cloud sends ``X-Hub-Signature``.  (GitHub
#: also sends a SHA-1 ``X-Hub-Signature``, which fails the prefix check —
#: SHA-1 is not accepted.)
SIGNATURE_HEADERS = ("X-Hub-Signature-256", "X-Hub-Signature")


def expected_signature(secret: str, payload_body: bytes) -> str:
    """The ``sha256=…`` header value a sender holding ``secret`` would send."""
    digest = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256)
    return SIGNATURE_PREFIX + digest.hexdigest()


def verify_signature(secret: str, payload_body: bytes, signature_header: str) -> bool:
    """True when ``signature_header`` is the HMAC-SHA256 of ``payload_body``."""
    if not secret or not signature_header:
        return False
    if not signature_header.startswith(SIGNATURE_PREFIX):
        return False
    expected = expected_signature(secret, payload_body)
    return hmac.compare_digest(
        expected.encode("utf-8"), signature_header.encode("utf-8")
    )


def verify_shared_secret(secret: str, presented: str) -> bool:
    """True when ``presented`` is the shared secret itself."""
    if not secret or not presented:
        return False
    return hmac.compare_digest(secret.encode("utf-8"), presented.encode("utf-8"))


def verify_webhook(
    secret: str,
    payload_body: bytes,
    signature_header: str = "",
    secret_header: str = "",
) -> bool:
    """Authenticate a webhook that accepts either form of the secret.

    A sender that presented a signature is judged on that signature alone: a
    wrong signature is a rejection, not an invitation to try the weaker
    header.
    """
    if not secret:
        return False
    if signature_header:
        return verify_signature(secret, payload_body, signature_header)
    return verify_shared_secret(secret, secret_header)
