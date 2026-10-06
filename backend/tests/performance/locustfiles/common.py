"""What the locustfiles share: the seeded fixtures, the logins, the verdict.

Every locustfile calls only what ``backend/scripts/seed_sdk_contract.py``
creates, which the weekly Performance Tests workflow runs before Locust starts:

* the SDK routes (``/tracking/*``, ``/feature-flags/evaluate/*``,
  ``/feature-flags/user/*``) use the seed's API key, the experiment
  ``sdk_contract_ab`` and the flag ``sdk_contract_flag``;
* the management routes answer 401 to any API key, so they sign in with
  ``POST /api/v1/auth/login`` as the seed's developer account (not a
  superuser) and send the bearer token;
* experiments and flags a task changes or deletes are ones that user created
  in the same run, so nothing depends on IDs that exist only somewhere else.

Every request is made as ``with self.client.<method>(..., catch_response=True)
as response:`` and decided by :func:`expect`. Locust records a
``catch_response=True`` request only when its ``with`` block exits, so the bare
form sends the request and never counts it -- which is how the weekly run once
recorded 0 requests and passed.

This module imports only the standard library: the unit tests import it, and
importing Locust into a pytest process patches it with gevent.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

# The fixtures backend/scripts/seed_sdk_contract.py creates (its EXPERIMENT_KEY
# and FLAG_KEY); backend/tests/unit/scripts/test_load_test_runner.py pins them.
EXPERIMENT_KEY = "sdk_contract_ab"
FLAG_KEY = "sdk_contract_flag"

# The developer account the same seed creates (backend/scripts/seed_demo_data.py,
# DEMO_USERS): role DEVELOPER, not a superuser, so the management tasks run
# with the permissions a dashboard user has.
DEFAULT_EMAIL = "dev@demo.com"
DEFAULT_PASSWORD = "Demo1234!"

LOGIN_PATH = "/api/v1/auth/login"


def api_key() -> str:
    """The seeded API key, from ``LOAD_TEST_API_KEY`` or the file it was written to.

    ``LOAD_TEST_API_KEY_FILE`` is the seed's ``.api_key`` file; the workflow
    passes the path so the key never appears in the job's environment or log.
    There is no default: a made-up key is answered 401 or 400, and the run
    would measure error handling.
    """
    key = os.environ.get("LOAD_TEST_API_KEY", "").strip()
    if key:
        return key
    path = os.environ.get("LOAD_TEST_API_KEY_FILE", "").strip()
    if path:
        key = Path(path).read_text(encoding="utf-8").strip()
        if key:
            return key
    raise RuntimeError(
        "No API key: set LOAD_TEST_API_KEY, or LOAD_TEST_API_KEY_FILE to the "
        "file backend/scripts/seed_sdk_contract.py writes (tests/sdk-contract/"
        "live/.api_key by default)."
    )


def sdk_headers() -> dict[str, str]:
    """Headers for the SDK routes."""
    return {"X-API-Key": api_key(), "Content-Type": "application/json"}


_token_lock = threading.Lock()  # a gevent lock once Locust has patched threading
_token = ""


def login(client: Any) -> dict[str, str]:
    """Sign in as the seeded developer and return bearer headers.

    One login per Locust process, shared by every user: the spike and
    breakpoint shapes start up to 2,000 users, and a password check each
    would load the server with logins instead of the traffic being measured.
    The token lives 12 hours (``LOCAL_AUTH_TOKEN_TTL_MINUTES``).

    The login is itself a recorded request (it matches no target). A refused
    login is recorded as a failure, and every management task after it fails
    with 401, so a wrong account turns the run red instead of quietly
    measuring nothing.
    """
    global _token
    with _token_lock:
        if not _token:
            body = {
                "email": os.environ.get("LOAD_TEST_EMAIL", DEFAULT_EMAIL),
                "password": os.environ.get("LOAD_TEST_PASSWORD", DEFAULT_PASSWORD),
            }
            with client.post(
                LOGIN_PATH, json=body, name=LOGIN_PATH, catch_response=True
            ) as response:
                if expect(response, 200):
                    _token = (response.json() or {}).get("access_token", "")
    return {"Authorization": f"Bearer {_token}", "Content-Type": "application/json"}


_experiment_lock = threading.Lock()
_experiment_id = ""


def seeded_experiment_id(client: Any, headers: dict[str, str]) -> str:
    """The ID of the seeded ``sdk_contract_ab`` experiment, looked up once per process.

    It is ACTIVE, so its results can be read (a DRAFT experiment's answer
    400). The lookup is recorded under its own name, so it does not count as
    a ``list_experiments`` request.
    """
    global _experiment_id
    with _experiment_lock:
        if not _experiment_id:
            with client.get(
                "/api/v1/experiments/",
                params={"status_filter": "active", "limit": 100},
                headers=headers,
                name="/api/v1/experiments (seed lookup)",
                catch_response=True,
            ) as response:
                if expect(response, 200):
                    items = (response.json() or {}).get("items", [])
                    found = [i["id"] for i in items if i.get("key") == EXPERIMENT_KEY]
                    if found:
                        _experiment_id = found[0]
                    else:
                        response.failure(f"no active experiment {EXPERIMENT_KEY}")
    return _experiment_id


def expect(response: Any, *statuses: int) -> bool:
    """Mark *response* a success if its status is one of *statuses*, else a failure.

    Returns whether it succeeded, so a task can read the body only then. The
    failure message is the status alone: no body, no URL beyond the request's
    name, which Locust already records.
    """
    if response.status_code in statuses:
        response.success()
        return True
    expected = "/".join(str(s) for s in statuses)
    # Locust reports a connection error or timeout as status 0.
    got = f"HTTP {response.status_code}" if response.status_code else "no response"
    response.failure(f"{got}, expected {expected}")
    return False
