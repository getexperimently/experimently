# Go SDK

`github.com/amarkanday/experimentation-platform/sdk/go` (package `experimentation`) provides
feature flag evaluation, experiment assignment and event tracking for Go services. Standard
library only, goroutine-safe, context-aware.

Flag evaluation and experiment assignment are decided **by the server**: every call goes to the
public API with your `X-API-Key`, the server buckets the user (sticky per user + experiment), and
the SDK caches the answer per user + key for a TTL. Nothing is bucketed locally.

Source: `sdk/go`. Requires Go 1.21+.

---

## Installation

```bash
go get github.com/amarkanday/experimentation-platform/sdk/go
```

```go
import exp "github.com/amarkanday/experimentation-platform/sdk/go"
```

---

## Quick Start

```go
client, err := exp.New(
    exp.WithBaseURL("http://localhost:8000"),          // origin only; the SDK appends /api/v1/...
    exp.WithAPIKey(os.Getenv("EXPERIMENTLY_API_KEY")), // sent as X-API-Key
    exp.WithTimeout(5*time.Second),
)
if err != nil {
    log.Fatal(err)
}
defer client.Close()

ctx := context.Background()
user := &exp.User{ID: "user-123", Attributes: map[string]interface{}{"plan": "pro"}}

// 1. Assignment (POST /api/v1/tracking/assign — sticky, records the exposure)
a, err := client.GetAssignment(ctx, "checkout_flow", user)
if err != nil {
    // nil assignment: not ACTIVE (404), bad key (401), network error ... fall back to control
}
headline := "Buy now"
if a != nil && a.Configuration["headline"] != nil {
    headline = a.Configuration["headline"].(string)
}

// 2. Feature flag (GET /api/v1/feature-flags/evaluate/new_search?user_id=user-123)
flag, _ := client.EvaluateFlag(ctx, "new_search", user) // disabled result on failure
if flag.Enabled { /* ... */ }

// 3. Track with a key → one POST /api/v1/tracking/track
_ = client.Track(ctx, &exp.TrackEvent{
    UserID: user.ID, EventName: "purchase", ExperimentKey: "checkout_flow",
    Value: exp.Float64(49.99), Properties: map[string]interface{}{"sku": "pro-plan"},
})

// 4. Track without a key → fanned out to every cached assignment + flag of this user
_ = client.Track(ctx, &exp.TrackEvent{UserID: user.ID, EventName: "page_view"})
```

---

## Configuration

| Option | Type | Default | Description |
|---|---|---|---|
| `WithBaseURL(url)` | `string` | `http://localhost:8000` | Backend origin. Trailing `/` stripped; empty → `New` returns an error |
| `WithAPIKey(key)` | `string` | `""` | Sent as `X-API-Key` (header omitted when empty) |
| `WithTimeout(d)` | `time.Duration` | `10s` | `http.Client` timeout; requests also stop when `ctx` is cancelled |
| `WithCacheTTL(d)` | `time.Duration` | `5m` | Lifetime of a cached evaluation/assignment; `<= 0` never expires |
| `WithCacheSize(n)` | `int` | `1000` | Max entries across evaluations + assignments, LRU eviction (`<= 0` → 1) |
| `WithLocalEval(bool)` | — | — | **Deprecated** no-op; the server evaluates everything |

---

## API Reference

```go
type Client interface {
    EvaluateFlag(ctx context.Context, flagKey string, user *User) (*EvalResult, error)
    GetAssignment(ctx context.Context, experimentKey string, user *User) (*Assignment, error)
    Track(ctx context.Context, event *TrackEvent) error
    TrackBatch(ctx context.Context, events []*TrackEvent) error
    Close() error
}
func New(opts ...Option) (Client, error)
func ConsistentHash(userID, key string) float64
func Float64(v float64) *float64
```

| Method | Endpoint | Returns | On failure |
|---|---|---|---|
| `EvaluateFlag` | `GET /feature-flags/evaluate/{key}?user_id=` | `*EvalResult` | `&EvalResult{Key: flagKey, Enabled: false}` **and** `error`. Only invalid arguments (empty `flagKey`, nil user / empty `user.ID`) return a `nil` result |
| `GetAssignment` | `POST /tracking/assign` | `*Assignment` | `(nil, error)` |
| `Track` | `/tracking/track` or `/tracking/batch` | `error` | Never panics; validation errors (nil event, empty `UserID`, no `EventName`/`EventType`) are returned before any request |
| `TrackBatch` | `/tracking/batch` (chunks of 100) | `error` | As `Track`; keyed events are batched as-is, unkeyed ones fanned out |
| `Close` | — | `nil` | Clears the cache and idle connections; safe to call twice |

### Types

| Type | Fields |
|---|---|
| `User` | `ID string` (required), `Attributes map[string]interface{}` — sent as `context` on assignment |
| `EvalResult` | `Key string`, `Enabled bool`, `Config map[string]any` — `nil` when the server returned `null` or a non-object |
| `Assignment` | `ExperimentKey`, `UserID`, `VariantID` (UUID), `VariantName` (`"control"`, `"treatment"`, …), `IsControl bool`, `Configuration map[string]any` |
| `TrackEvent` | `UserID`, `EventName`, `EventType` (→ `event_type`, defaults to `EventName`), `ExperimentKey`, `FeatureFlagKey`, `Value *float64`, `Properties` (→ `metadata`), `Timestamp time.Time` (→ RFC 3339 when non-zero, else server-stamped) |
| `APIError` | `StatusCode int`, `Message string` (response body), `RetryAfter string` (raw header on 429) |

```go
var apiErr *exp.APIError
if _, err := client.GetAssignment(ctx, "exp", user); errors.As(err, &apiErr) && apiErr.StatusCode == 404 {
    // experiment unknown or not ACTIVE
}
```

---

## Caching and failure behaviour

- Successful results are cached per **user + key** (namespaced by kind, so a flag and an
  experiment with the same key never collide) for `CacheTTL`. A cache hit makes **no** request.
- **Failures are never cached** — the next call retries.
- Network/timeout, `401`, `404`, `422`, `429`, `5xx`: `EvaluateFlag` degrades to a disabled result
  with the error attached; `GetAssignment` returns `nil` and the error. Non-2xx responses are
  `*APIError` (`RetryAfter` set on 429); transport errors wrap the `net/http` error.
- `Track`/`TrackBatch` never panic; treat the error as informational.
- The client is safe for concurrent use: the cache is mutex-protected and `net/http` pools
  connections. Pass a cancellable `ctx` to bound latency per call.

---

## Tracking fan-out

With `ExperimentKey` and/or `FeatureFlagKey` set, `Track` sends one `POST /api/v1/tracking/track`.
Without a key it sends one `POST /api/v1/tracking/batch` with one entry per experiment the user
was assigned to through this client (`experiment_key`) plus one per flag evaluated for the user
(`feature_flag_key`), all taken from the cache. Nothing cached → nothing is sent and `nil` is
returned. Batches are chunked at 100 events.

Conversions are matched to metrics by **event name**: a metric whose `event_name` is `purchase`
counts every `purchase` event regardless of `event_type`.

---

## Consistent hash (compatibility utility)

`ConsistentHash(userID, key)` = `MD5("{userID}:{key}")`, first 4 bytes as little-endian uint32,
divided by 2^32. It exists only so the golden vectors in `tests/sdk-contract/golden-vectors.json`
stay identical across SDKs. **Nothing in the SDK calls it to pick a variant** — the server decides.

```go
exp.ConsistentHash("user-123", "my-flag") // 0.6927449859213084
```

---

## Backend endpoints used

Every request carries `X-API-Key`, `Content-Type: application/json` and `Accept: application/json`.

| SDK call | Method and path | Body / query | Response used |
|---|---|---|---|
| `EvaluateFlag` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}`; 404 when the flag is not ACTIVE |
| `GetAssignment` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}`; 404 when the experiment is not ACTIVE |
| `Track` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `Track` without keys, `TrackBatch` | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (max 100 per request) | ignored |

Errors: 401 bad key, 404 experiment/flag unknown or not ACTIVE, 422 event without any key, 429
rate limited (`Retry-After`). These paths share the backend's per-IP `SDK_RATE_LIMIT_PER_MINUTE`
ceiling (default 6000).

---

## Contract smoke

```bash
cd sdk/go && go run ./examples/contract_smoke
# {"sdk":"go","assign":{"variant_name":"control","is_control":true,"sticky":true},"flag":{"enabled":true},"track":{"ok":true},"fanout":{"ok":true}}
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (default `sdk_contract_ab`), `CONTRACT_FLAG_KEY` (default
`sdk_contract_flag`), `CONTRACT_USER_ID` (default random `smoke-<uuid>`). The smoke assigns
three times (twice on one client, once on a fresh client) to prove server-side stickiness,
evaluates the flag, tracks `purchase` with the experiment key, tracks `page_view` without a key
and sends a 2-event `TrackBatch`. Fixtures: `backend/scripts/seed_sdk_contract.py`; repo-wide
runner: `python tests/sdk-contract/live/run_live_contract.py --sdk go --strict`.

Verified against a live backend: yes (2026-09-11)

---

## Development

```bash
cd sdk/go
go vet ./... && go test -race ./...   # 51 tests, HTTP mocked with net/http/httptest
go run ./examples                     # examples/main.go walkthrough against a running backend
```
