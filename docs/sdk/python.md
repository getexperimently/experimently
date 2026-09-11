# Python SDK

`experimentation-sdk` (v1.0.0) is a synchronous, dependency-free Python client for the
Experimentation Platform public API: experiment assignment, feature-flag evaluation and event
tracking. Requires Python 3.9+; HTTP goes through the standard library (`urllib`).

Flag evaluation and experiment assignment are decided **by the server**: every call goes to the
public API with your `X-API-Key`, the server buckets the user (sticky per user + experiment), and
the SDK caches the answer per user + key. Nothing is bucketed locally.

Source: `sdk/python`. The OpenFeature provider in `sdk/openfeature-python` is built on top of this
client (see [openfeature.md](openfeature.md)).

---

## Installation

```bash
pip install experimentation-sdk        # once published
pip install -e sdk/python              # from this repository
```

---

## Quick start

```python
import os
from experimentation import ExperimentationClient, ExperimentationError

client = ExperimentationClient(
    api_url=os.environ.get("EXPERIMENTLY_API_URL", "http://localhost:8000"),  # origin only
    api_key=os.environ["EXPERIMENTLY_API_KEY"],
)

# Experiments — sticky assignment made by the server (POST /api/v1/tracking/assign)
variant = client.get_variant("checkout_flow", user_id="user-123", user_attributes={"plan": "pro"})
if variant == "treatment":
    render_new_checkout()

assignment = client.get_assignment("checkout_flow", "user-123")   # raises on failure
assignment.variant_name, assignment.is_control, assignment.configuration

# Feature flags (GET /api/v1/feature-flags/evaluate/{key}?user_id=…)
if client.is_feature_enabled("new_search", "user-123"):
    use_new_search()
flag = client.get_feature_flag("new_search", "user-123")          # FlagEvaluation(key, enabled, config)
flags = client.get_all_flags("user-123")                           # {"new_search": True, ...}

# Tracking (never raises)
client.track("user-123", "purchase", event_value=49.99, experiment_key="checkout_flow")
client.track("user-123", "page_view", properties={"page": "/"})   # no key: fanned out, see below
```

### Constructor

```python
ExperimentationClient(
    api_url: str,                    # backend origin, e.g. "https://api.example.com"; the SDK appends /api/v1/...
    api_key: str,                    # sent as X-API-Key
    timeout_seconds: float = 5.0,    # per request
    cache_ttl_seconds: float = 300,  # how long a successful assignment/evaluation is reused per user + key
    default_variant: str = "control",# what get_variant returns on failure
    transport: Transport | None = None,  # inject your own HTTP layer (tests use experimentation.testing.FakeTransport)
)
```

Instances are thread-safe and should be shared across your application (one per process is
typical): the per-user cache is what makes a key-less `track` count for every experiment the user
is in.

---

## API reference

| Method | Returns | Failure behaviour |
|---|---|---|
| `get_assignment(experiment_key, user_id, user_attributes=None)` | `Assignment(experiment_key, user_id, variant_id, variant_name, is_control, configuration)` | raises `ExperimentationError` (`status == 404` when the experiment is not ACTIVE or unknown) |
| `get_variant(experiment_key, user_id, user_attributes=None)` | `str` — the variant name | returns `default_variant` (`"control"`) |
| `get_feature_flag(flag_key, user_id)` | `FlagEvaluation(key, enabled, config)` | raises `ExperimentationError` (`status == 404` when the flag is not ACTIVE or unknown) |
| `is_feature_enabled(flag_key, user_id)` | `bool` | returns `False` |
| `get_all_flags(user_id)` | `dict[str, bool]` (not cached) | raises `ExperimentationError` |
| `track(user_id, event_name, event_value=None, properties=None, experiment_key=None, feature_flag_key=None, event_type=None, timestamp=None)` | `bool` — `True` when the server accepted it | never raises; `False` on failure or when nothing was sent |
| `track_batch(events)` | `BatchResult(success_count, failure_count, errors)`, `.ok` | never raises; sends chunks of 100, a failed chunk counts all its events as failures |
| `get_assignments(user_id, active_only=True)` | `list[dict]` — the user's assignments from the server (not cached) | raises `ExperimentationError` |
| `cached_assignments(user_id)` / `cached_flags(user_id)` | cached, unexpired entries for the user | — |
| `clear_cache()` | — | — |
| `consistent_hash(user_id, flag_key)` / `md5_hex(user_id, flag_key)` | cross-SDK MD5 bucket in `[0, 1)` / hex digest | pure functions; **not** used to decide variants |

`Assignment` and `FlagEvaluation` are frozen dataclasses. `ExperimentationError` carries
`.status` (HTTP status, `None` for network errors and timeouts) and `.body` (raw response text).
`user_attributes` is sent as `context` on assignment and is what targeting rules evaluate.

### Caching and retries

- Successful assignments and evaluations are cached per user + key for `cache_ttl_seconds`
  (default 300 s). Failures are never cached, so the next call retries.
- A `429` is retried once after `Retry-After` seconds (capped at 5 s; 1 s when the header is
  missing or unparseable). Any other non-2xx status raises immediately.
- The cache is checked before any request, so a cached value is returned even if the backend is
  currently unreachable.

### Tracking fan-out rule

- **With** `experiment_key` and/or `feature_flag_key` → one `POST /api/v1/tracking/track`.
- **Without** a key → one `POST /api/v1/tracking/batch` (chunks of 100) containing one entry per
  experiment the user has been assigned to through this client (`experiment_key`) plus one per flag
  evaluated for the user (`feature_flag_key`), taken from the cache (successful, unexpired only).
- Nothing cached for the user → nothing is sent and `track` returns `False`.

`event_type` defaults to `event_name`; `properties` is sent as `metadata`; `timestamp` may be a
`datetime` (naive values are treated as UTC) or an ISO-8601 string. Conversions are matched to
experiment metrics by **event name**.

---

## Backend endpoints used

Every request carries `X-API-Key: <key>`, `Content-Type: application/json` and
`Accept: application/json`.

| SDK call | Method and path | Body / query | Response used |
|---|---|---|---|
| `get_assignment`, `get_variant` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}`; 404 when the experiment is not ACTIVE |
| `get_feature_flag`, `is_feature_enabled` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}`; 404 when the flag is not ACTIVE |
| `get_all_flags` | `GET /api/v1/feature-flags/user/{user_id}` | — | `{"<flag_key>": bool, …}` |
| `track` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `track` without keys, `track_batch` | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (max 100 per request) | `{success_count, failure_count, errors}` |
| `get_assignments` | `GET /api/v1/tracking/assignments/{user_id}?active_only=true` | — | list of dicts |

These SDK paths share a per-IP rate-limit ceiling of `SDK_RATE_LIMIT_PER_MINUTE` requests
(default 6000) on the backend; the SDK honours `Retry-After` on `429` as described above.

---

## Testing your own code

`experimentation.testing.FakeTransport` records requests and serves canned responses, so unit
tests can assert the exact request without a network:

```python
from experimentation import ExperimentationClient
from experimentation.testing import FakeTransport

transport = FakeTransport().route(
    "GET", "/api/v1/feature-flags/evaluate/new_search",
    json={"key": "new_search", "enabled": True, "config": None},
)
client = ExperimentationClient("http://test", "key", transport=transport)
assert client.is_feature_enabled("new_search", "user-1")
assert transport.last.query == {"user_id": "user-1"}
assert transport.last.headers["X-API-Key"] == "key"
```

---

## Contract smoke

Runs the four contract steps (sticky assignment, flag evaluation, keyed track, key-less fan-out
plus a 2-event batch) against a live backend and prints one JSON line:

```bash
EXPERIMENTLY_API_KEY=<key> python sdk/python/examples/contract_smoke.py
# {"sdk":"python","assign":{"variant_name":"control","is_control":true,"sticky":true},"flag":{"enabled":true},"track":{"ok":true},"fanout":{"ok":true}}
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (default `sdk_contract_ab`), `CONTRACT_FLAG_KEY` (default
`sdk_contract_flag`), `CONTRACT_USER_ID` (default random `smoke-<uuid>`). No install is needed;
the script adds `sdk/python` to `sys.path`.

Verified against a live backend: **yes (2026-09-11)** — fixtures seeded with
`backend/scripts/seed_sdk_contract.py`, run via
`python tests/sdk-contract/live/run_live_contract.py --sdk python --strict`.

---

## Development

```bash
source venv/bin/activate
python -m pytest sdk/python/tests -q -o addopts="" -p no:cacheprovider   # 87 tests, HTTP is faked
python -m pytest tests/sdk-contract/test_python_sdk.py -q               # cross-SDK hash golden vectors
```
