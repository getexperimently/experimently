# experimentation-sdk (Python)

Synchronous, dependency-free Python client for the Experimentation Platform public API.
Experiment assignment and feature-flag evaluation are decided **by the server** (sticky per
user + experiment); the SDK caches the answers per user + key and never buckets locally.

Requires Python 3.9+. HTTP goes through the standard library (`urllib`), so there is nothing
else to install.

## Install

```bash
pip install experimentation-sdk          # once published
pip install -e sdk/python                # from this repository
```

## Quick start

```python
from experimentation import ExperimentationClient

client = ExperimentationClient(
    api_url="http://localhost:8000",       # backend origin; the SDK appends /api/v1/...
    api_key=os.environ["EXPERIMENTLY_API_KEY"],
)

# Experiments — sticky assignment made by the server
variant = client.get_variant("checkout_flow", user_id="user-123", user_attributes={"plan": "pro"})
if variant == "treatment":
    ...

assignment = client.get_assignment("checkout_flow", "user-123")     # raises ExperimentationError on failure
assignment.variant_name, assignment.is_control, assignment.configuration

# Feature flags — user_attributes (optional) is sent as ?context=<url-encoded JSON> for targeting rules
if client.is_feature_enabled("new_search", "user-123", user_attributes={"plan": "pro"}):
    ...
flag = client.get_feature_flag("new_search", "user-123")            # FlagEvaluation(key, enabled, config, reason)
flags = client.get_all_flags("user-123", {"plan": "pro"})            # {"new_search": True, ...}

# Tracking (never raises)
client.track("user-123", "purchase", event_value=49.99, experiment_key="checkout_flow")
client.track("user-123", "page_view", properties={"page": "/"})     # no key: fanned out, see below
```

Constructor: `ExperimentationClient(api_url, api_key, timeout_seconds=5.0, cache_ttl_seconds=300,
default_variant="control", transport=None)`. Instances are thread-safe.

## API

| Method | Returns | Failure behaviour |
|---|---|---|
| `get_assignment(experiment_key, user_id, user_attributes=None)` | `Assignment(experiment_key, user_id, variant_id, variant_name, is_control, configuration)` | raises `ExperimentationError` (`status == 404` when the experiment is not ACTIVE) |
| `get_variant(experiment_key, user_id, user_attributes=None)` | `str` variant name | returns `default_variant` |
| `get_feature_flag(flag_key, user_id, user_attributes=None)` | `FlagEvaluation(key, enabled, config, reason)` | raises `ExperimentationError` (`status == 404` when the flag is not ACTIVE) |
| `is_feature_enabled(flag_key, user_id, user_attributes=None)` | `bool` | returns `False` |
| `get_all_flags(user_id, user_attributes=None)` | `dict[str, bool]` (not cached) | raises `ExperimentationError` |
| `track(user_id, event_name, event_value=None, properties=None, experiment_key=None, feature_flag_key=None, event_type=None, timestamp=None)` | `bool` — `True` when accepted | never raises; `False` on failure or when nothing was sent |
| `track_batch(events)` | `BatchResult(success_count, failure_count, errors)`; `.ok` | never raises; a failed chunk counts all its events as failures |
| `get_assignments(user_id, active_only=True)` | `list[dict]` from the server | raises `ExperimentationError` |
| `cached_assignments(user_id)` / `cached_flags(user_id)` | cached, unexpired entries | — |
| `clear_cache()` | — | — |
| `consistent_hash(user_id, flag_key)` / `md5_hex(user_id, flag_key)` | cross-SDK MD5 bucket in `[0, 1)` / hex digest | pure functions; **not** used to decide variants |

`ExperimentationError` carries `.status` (HTTP status, `None` for network errors/timeouts) and
`.body` (raw response text). Failures are never cached, so the next call retries. A `429` is
retried once after `Retry-After` seconds (capped at 5 s).

`user_attributes` is sent as `context` on assignment **and** on flag evaluation
(`&context=<url-encoded JSON>`, omitted when empty), so flag targeting rules evaluate against it
(`country` also matches `user.country`; nested dicts flatten to dotted keys such as `app.version`).
`FlagEvaluation.reason` (`targeting_rule` / `rollout` / `inactive` / `error`, or `None`) says why
the server decided. Caches are keyed by user + key only — call `clear_cache()` after changing a
user's attributes.

## Tracking fan-out rule

- **with** `experiment_key` and/or `feature_flag_key` → one `POST /api/v1/tracking/track`;
- **without** a key → one `POST /api/v1/tracking/batch` (chunks of 100) containing one entry per
  experiment the user has been assigned to in this client (`experiment_key`) plus one per flag
  evaluated for the user (`feature_flag_key`), taken from the cache (successful, unexpired only);
- nothing cached for the user → nothing is sent and `track` returns `False`.

`event_type` defaults to `event_name`; `properties` is sent as `metadata`; `timestamp` may be a
`datetime` (naive values are treated as UTC) or an ISO-8601 string.

## Backend endpoints used

Every request carries `X-API-Key: <key>`, `Content-Type: application/json` and `Accept: application/json`.

| SDK call | Method and path | Body / query | Response used |
|---|---|---|---|
| `get_assignment`, `get_variant` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}`; 404 when not ACTIVE |
| `get_feature_flag`, `is_feature_enabled` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…&context=<url-encoded JSON>` | `context` = `user_attributes` (omitted when empty) | `{key, enabled, config, reason}`; off with `reason: "inactive"` when the flag exists but is not ACTIVE; 404 only for an unknown key |
| `get_all_flags` | `GET /api/v1/feature-flags/user/{user_id}?context=<url-encoded JSON>` | `context` = `user_attributes` (omitted when empty) | `{"<flag_key>": bool, …}` |
| `track` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `track` without keys, `track_batch` | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (≤ 100 per request) | `{success_count, failure_count, errors}` |
| `get_assignments` | `GET /api/v1/tracking/assignments/{user_id}?active_only=true` | — | list of dicts |

## Contract smoke

```bash
EXPERIMENTLY_API_KEY=<key> python sdk/python/examples/contract_smoke.py
# {"sdk":"python","assign":{"variant_name":"treatment","is_control":false,"sticky":true},"flag":{"enabled":true},"track":{"ok":true},"fanout":{"ok":true}}
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (default `sdk_contract_ab`), `CONTRACT_FLAG_KEY` (default `sdk_contract_flag`),
`CONTRACT_USER_ID` (default random `smoke-<uuid>`).

Verified against a live backend: **yes (2026-09-11)** — `sdk_contract_ab` / `sdk_contract_flag`
seeded with `backend/scripts/seed_sdk_contract.py`, run via
`python tests/sdk-contract/live/run_live_contract.py --sdk python --strict`.

## Testing your own code

`experimentation.testing.FakeTransport` records requests and serves canned responses:

```python
from experimentation import ExperimentationClient
from experimentation.testing import FakeTransport

transport = FakeTransport().route("GET", "/api/v1/feature-flags/evaluate/new_search",
                                  json={"key": "new_search", "enabled": True, "config": None})
client = ExperimentationClient("http://test", "key", transport=transport)
assert client.is_feature_enabled("new_search", "user-1")
assert transport.last.query == {"user_id": "user-1"}
```

## Development

```bash
source venv/bin/activate
python -m pytest sdk/python/tests -q -o addopts="" -p no:cacheprovider   # 97 tests, HTTP is faked
```
