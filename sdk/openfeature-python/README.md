# experimentation-openfeature (Python)

[OpenFeature](https://openfeature.dev) provider for the Experimentation Platform. Flags are
evaluated **by the server** through the [`experimentation`](../python) Python SDK
(`GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=<targeting_key>`) and cached per
user + flag; nothing is bucketed locally.

## Install

```bash
pip install openfeature-sdk experimentation-sdk experimentation-openfeature   # once published
pip install -e sdk/python -e sdk/openfeature-python                          # from this repository
```

Requires Python 3.9+ and `openfeature-sdk >= 0.9.0` (the version that added the tracking API).
The only other dependency is [`experimentation-sdk`](../python), which itself has none.

## Quick start

```python
import os
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from experimentation_openfeature import ExperimentationProvider

provider = ExperimentationProvider(
    api_key=os.environ["EXPERIMENTLY_API_KEY"],
    base_url=os.environ.get("EXPERIMENTLY_API_URL", "http://localhost:8000"),
    cache_ttl=300,   # seconds a successful evaluation is reused per user + flag
    timeout=10,      # seconds
)
api.set_provider(provider)
client = api.get_client()

ctx = EvaluationContext(targeting_key="user-12345")          # targeting_key == platform user_id (required)
enabled = client.get_boolean_value("dark-mode", False, ctx)
variant = client.get_string_value("checkout-experiment", "control", ctx)   # config["variant"]
limit = client.get_integer_value("cart-max-items", 10, ctx)                # config["value"]
config = client.get_object_value("feature-config", {}, ctx)                # whole config

# Experiments and event tracking are not part of OpenFeature: use the SDK client underneath.
assignment = provider.client.get_assignment("checkout_flow", "user-12345")
provider.client.track("user-12345", "purchase", event_value=49.99, experiment_key="checkout_flow")
```

Constructor: `ExperimentationProvider(api_key, base_url="http://localhost:8000", cache_ttl=300,
timeout=10, *, client=None, transport=None)`. Pass `client=` to share one
`experimentation.ExperimentationClient` (and its cache) with the rest of your application.

## Resolution rules

| OpenFeature call | Value | When absent |
|---|---|---|
| `get_boolean_*` | `enabled` | — |
| `get_string_*` | `config["variant"]` (or `config` itself when it is a string) | default, reason `DEFAULT` |
| `get_integer_*` / `get_float_*` | `config["value"]` (or `config` itself when numeric; `bool` never counts) | default, reason `DEFAULT` |
| `get_object_*` | `config` when it is a dict or list | default, reason `DEFAULT` |

- `targeting_key` → `user_id`. It is required: without it you get the default value with
  `TARGETING_KEY_MISSING`. **Context attributes are not sent** — the evaluate endpoint has no
  context parameter.
- A disabled flag resolves non-boolean calls to the default with reason `DISABLED`.
- Reasons: `TARGETING_MATCH` (fresh from the server, on), `DISABLED`, `CACHED` (from the SDK
  cache), `DEFAULT`, `ERROR` (`FLAG_NOT_FOUND` on 404 — flag unknown or not ACTIVE — otherwise
  `GENERAL`). Errors never raise and are never cached.
- `variant` on the details is `config["variant"]` when it is a string.
- `client.track(event_name, ctx, TrackingEventDetails(value=…))` forwards to
  `ExperimentationClient.track` (fans out to the user's cached assignments and flags).

## Backend endpoints used

Every request carries `X-API-Key: <key>`, `Content-Type: application/json`, `Accept: application/json`.

| Call | Method and path | Response used |
|---|---|---|
| every `resolve_*_details` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | `{key, enabled, config}`; off with `reason: "inactive"` when the flag exists but is not ACTIVE; 404 only for an unknown key |
| `provider.track` / `provider.client.track` | `POST /api/v1/tracking/track` (with a key) or `POST /api/v1/tracking/batch` (fan-out) | ignored / `{success_count, failure_count, errors}` |
| `provider.client.get_assignment` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}` |

## Contract smoke

```bash
EXPERIMENTLY_API_KEY=<key> python sdk/openfeature-python/examples/contract_smoke.py
# {"sdk":"openfeature-python","assign":{"variant_name":"control","is_control":true,"sticky":true},"flag":{"enabled":true},"track":{"ok":true},"fanout":{"ok":true}}
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (default `sdk_contract_ab`), `CONTRACT_FLAG_KEY` (default `sdk_contract_flag`),
`CONTRACT_USER_ID` (default random `smoke-<uuid>`). The flag is resolved through the OpenFeature
API; assignment and tracking use `provider.client`.

Verified against a live backend: **yes (2026-09-11)** — via
`python tests/sdk-contract/live/run_live_contract.py --sdk openfeature-python --strict`.

## Development

```bash
source venv/bin/activate && pip install openfeature-sdk
python -m pytest sdk/openfeature-python/tests -q -o addopts="" -p no:cacheprovider
```

`tests/conftest.py` puts `sdk/python` and `src/` on `sys.path`, so neither package needs to be installed.
