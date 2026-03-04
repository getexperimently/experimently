# Go SDK

The Go SDK provides feature flag evaluation, experiment variant assignment, and event tracking for Go applications. It includes an LRU cache with TTL support, consistent MD5-based hash bucketing, local evaluation mode, and full context-cancellation support.

---

## Installation

```bash
go get github.com/amarkanday/experimentation-platform/sdk/go
```

Requires Go 1.19 or later.

---

## Quick Start

```go
import exp "github.com/amarkanday/experimentation-platform/sdk/go"

client, _ := exp.NewClient(
    exp.WithBaseURL("https://api.example.com"),
    exp.WithAPIKey("your-api-key"),
)
defer client.Close()

result, _ := client.EvaluateFlag(ctx, "my-flag", &exp.User{ID: "user-123"})
if result.Enabled {
    // show new feature
}
```

---

## Building the Client

```go
import exp "github.com/amarkanday/experimentation-platform/sdk/go"

client, err := exp.NewClient(
    exp.WithBaseURL("https://api.example.com"), // Required
    exp.WithAPIKey("your-api-key"),              // Required
)
if err != nil {
    log.Fatalf("failed to create client: %v", err)
}
defer client.Close()
```

### Configuration Options

All options are functional options passed to `NewClient`.

```go
client, err := exp.NewClient(
    exp.WithBaseURL("https://api.example.com"),
    exp.WithAPIKey("your-api-key"),
    exp.WithTimeout(2*time.Second),      // HTTP timeout (default: 5s)
    exp.WithCacheSize(1000),             // LRU cache capacity (default: 1000)
    exp.WithCacheTTL(60*time.Second),    // Cache entry TTL (default: 60s)
    exp.WithLocalEval(true),             // Use local hashing, skip network (default: false)
)
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `WithBaseURL(url string)` | `string` | *(required)* | Base URL of the platform API |
| `WithAPIKey(key string)` | `string` | *(required)* | API key for SDK authentication |
| `WithTimeout(d time.Duration)` | `Duration` | `5s` | HTTP request timeout |
| `WithCacheSize(n int)` | `int` | `1000` | Maximum LRU cache entries |
| `WithCacheTTL(d time.Duration)` | `Duration` | `60s` | Time before a cached result expires |
| `WithLocalEval(enabled bool)` | `bool` | `false` | Evaluate flags locally using downloaded rules |

Call `client.Close()` when shutting down to flush pending events and release the HTTP connection pool.

---

## Core Concepts

### Local Evaluation

When `WithLocalEval(true)` is set, the SDK periodically downloads experiment and flag configurations from the platform and evaluates them in-process without making a network call on every request. This is the recommended mode for high-traffic services.

```go
client, err := exp.NewClient(
    exp.WithBaseURL("https://api.example.com"),
    exp.WithAPIKey("your-api-key"),
    exp.WithLocalEval(true),
    exp.WithCacheTTL(30*time.Second), // How often to refresh the rule set
)
```

The SDK falls back to the remote API if local rule data is unavailable.

### Consistent Hashing

Variant assignment uses **MD5-based consistent hashing** on the string `"{experimentKey}:{userID}"`. This guarantees that the same user always receives the same variant for a given experiment, across all SDK instances and application restarts — no sticky session infrastructure is required.

The hash algorithm is identical across all platform SDKs (Go, Java, Python, JavaScript, React), so a user bucketed server-side will be in the same bucket client-side.

### Caching

The SDK maintains a thread-safe in-memory LRU cache. Every evaluation result is cached by `(flagKey, userID)`. Subsequent calls for the same user bypass the network entirely until the TTL expires. Adjust `WithCacheSize` and `WithCacheTTL` based on your traffic volume and acceptable staleness.

---

## Feature Flag Evaluation

### `EvaluateFlag`

```go
result, err := client.EvaluateFlag(ctx, "my-flag", &exp.User{ID: "user-123"})
if err != nil {
    // Errors are rare; the SDK returns a disabled result on network failures.
    log.Printf("flag evaluation error: %v", err)
}
if result.Enabled {
    showNewFeature()
}
```

Pass user attributes for targeting rules:

```go
user := &exp.User{
    ID: "user-123",
    Attributes: map[string]interface{}{
        "plan":    "enterprise",
        "country": "US",
        "beta":    true,
    },
}
result, err := client.EvaluateFlag(ctx, "new-dashboard", user)
```

### `FlagResult` Fields

| Field | Type | Description |
|-------|------|-------------|
| `Enabled` | `bool` | Whether the flag is on for this user |
| `FlagKey` | `string` | The evaluated flag key |
| `UserID` | `string` | The user ID used for evaluation |
| `EvaluatedAt` | `time.Time` | Timestamp of the evaluation |

---

## Experiment Assignment

### `GetAssignment`

Returns the full assignment including variant key, experiment metadata, and whether the user is in the control group.

```go
assignment, err := client.GetAssignment(ctx, "checkout-experiment", user)
if err != nil {
    log.Printf("assignment error: %v", err)
    // Fall back to control
}
fmt.Println(assignment.VariantKey) // "control" or "treatment"
```

Branching on the variant:

```go
switch assignment.VariantKey {
case "green-button":
    renderGreenButton(w)
case "red-button":
    renderRedButton(w)
default:
    renderDefaultButton(w)
}
```

### `Assignment` Fields

| Field | Type | Description |
|-------|------|-------------|
| `VariantKey` | `string` | Assigned variant (e.g., `"control"`, `"treatment"`) |
| `ExperimentKey` | `string` | The experiment key |
| `ExperimentID` | `string` | UUID of the experiment |
| `IsControl` | `bool` | `true` if this is the control variant |
| `AssignedAt` | `time.Time` | Assignment timestamp |

---

## Event Tracking

### `Track`

Records a conversion or behavioral event. Call this after meaningful user actions (purchases, clicks, form submissions).

```go
err := client.Track(ctx, &exp.TrackEvent{
    UserID:    "user-123",
    EventName: "purchase",
    Properties: map[string]interface{}{
        "amount":   99.99,
        "currency": "USD",
        "sku":      "pro-plan",
    },
})
```

For fire-and-forget tracking (does not block the request path):

```go
client.TrackAsync(&exp.TrackEvent{
    UserID:    "user-123",
    EventName: "page_view",
})
```

`TrackAsync` enqueues the event in an internal buffered channel. Events are flushed to the platform in batches. Call `client.Close()` before process exit to ensure the buffer is drained.

### `TrackEvent` Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `UserID` | `string` | Yes | The user who performed the action |
| `EventName` | `string` | Yes | Event identifier (e.g., `"purchase"`, `"signup"`) |
| `Value` | `float64` | No | Numeric value for the event (revenue, duration, count) |
| `Properties` | `map[string]interface{}` | No | Arbitrary key-value metadata |
| `Timestamp` | `time.Time` | No | Event time (defaults to `time.Now()` if zero) |

---

## Advanced Usage

### User Attributes for Targeting

User attributes are matched against targeting rules configured in the platform. Supported attribute value types are `string`, `int`, `float64`, and `bool`.

```go
user := &exp.User{
    ID: "user-456",
    Attributes: map[string]interface{}{
        "plan":       "pro",
        "country":    "CA",
        "age":        34,
        "beta_tester": true,
    },
}
```

Attributes are evaluated server-side (or locally if `WithLocalEval(true)`). They are never persisted by the SDK.

### Context Cancellation

All network operations respect `context.Context`. Use deadlines and cancellations to bound latency in request-handling code.

```go
ctx, cancel := context.WithTimeout(r.Context(), 100*time.Millisecond)
defer cancel()

result, err := client.EvaluateFlag(ctx, "my-flag", user)
if errors.Is(err, context.DeadlineExceeded) {
    // Context timed out; serve the default (disabled) value
}
```

### Goroutine Safety

`ExperimentationClient` is safe for concurrent use across goroutines. Create a single instance at application startup and share it for the process lifetime.

```go
// main.go — create once
var expClient *exp.Client

func main() {
    var err error
    expClient, err = exp.NewClient(
        exp.WithBaseURL(os.Getenv("EXP_BASE_URL")),
        exp.WithAPIKey(os.Getenv("EXP_API_KEY")),
    )
    if err != nil {
        log.Fatal(err)
    }
    defer expClient.Close()
    // ...
}

// handler.go — use from any goroutine
func handleRequest(w http.ResponseWriter, r *http.Request) {
    result, _ := expClient.EvaluateFlag(r.Context(), "feature-x", user)
    // ...
}
```

---

## Error Handling

The SDK uses typed errors for predictable error handling.

```go
result, err := client.EvaluateFlag(ctx, "my-flag", user)
if err != nil {
    var apiErr *exp.APIError
    if errors.As(err, &apiErr) {
        log.Printf("API error %d: %s", apiErr.StatusCode, apiErr.Message)
    }
    // EvaluateFlag always returns a usable result even on error (Enabled: false)
    // Safe to proceed with result.Enabled
}
```

| Error Type | Description |
|------------|-------------|
| `*exp.APIError` | Non-2xx HTTP response from the platform |
| `*exp.NetworkError` | Connection failure or timeout |
| `*exp.ValidationError` | Invalid input (empty user ID, empty flag key) |

`EvaluateFlag` and `GetAssignment` always return a usable zero-value result on error so callers never need to nil-check before reading fields.

---

## Testing

Use `net/http/httptest` to test code that calls the SDK without hitting the real API.

```go
import (
    "net/http"
    "net/http/httptest"
    "testing"

    exp "github.com/amarkanday/experimentation-platform/sdk/go"
)

func TestCheckoutFeature(t *testing.T) {
    server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(http.StatusOK)
        w.Write([]byte(`{"enabled": true, "flag_key": "new-checkout"}`))
    }))
    defer server.Close()

    client, err := exp.NewClient(
        exp.WithBaseURL(server.URL),
        exp.WithAPIKey("test-key"),
    )
    if err != nil {
        t.Fatal(err)
    }
    defer client.Close()

    user := &exp.User{ID: "test-user"}
    result, err := client.EvaluateFlag(t.Context(), "new-checkout", user)
    if err != nil {
        t.Fatalf("unexpected error: %v", err)
    }
    if !result.Enabled {
        t.Error("expected flag to be enabled")
    }
}
```

For unit tests that do not need HTTP at all, use `exp.NewMockClient()` which returns a client with a configurable in-memory stub:

```go
mock := exp.NewMockClient()
mock.SetFlag("my-flag", true)
mock.SetVariant("checkout-experiment", "treatment")

result, _ := mock.EvaluateFlag(ctx, "my-flag", user)
// result.Enabled == true
```

---

## Full Working Example

```go
package main

import (
    "context"
    "fmt"
    "log"
    "net/http"
    "os"
    "time"

    exp "github.com/amarkanday/experimentation-platform/sdk/go"
)

var expClient *exp.Client

func init() {
    var err error
    expClient, err = exp.NewClient(
        exp.WithBaseURL(os.Getenv("EXP_BASE_URL")),
        exp.WithAPIKey(os.Getenv("EXP_API_KEY")),
        exp.WithTimeout(2*time.Second),
        exp.WithCacheSize(5000),
        exp.WithCacheTTL(30*time.Second),
        exp.WithLocalEval(true),
    )
    if err != nil {
        log.Fatalf("failed to init experimentation client: %v", err)
    }
}

func checkoutHandler(w http.ResponseWriter, r *http.Request) {
    userID := r.Header.Get("X-User-ID")
    if userID == "" {
        userID = "anonymous"
    }

    ctx, cancel := context.WithTimeout(r.Context(), 100*time.Millisecond)
    defer cancel()

    user := &exp.User{
        ID: userID,
        Attributes: map[string]interface{}{
            "plan":    r.Header.Get("X-User-Plan"),
            "country": r.Header.Get("X-User-Country"),
        },
    }

    // Feature flag gate
    flagResult, _ := expClient.EvaluateFlag(ctx, "new-checkout-flow", user)

    // Experiment variant
    assignment, _ := expClient.GetAssignment(ctx, "checkout-cta-copy", user)

    fmt.Fprintf(w, "newFlow=%v cta=%s", flagResult.Enabled, assignment.VariantKey)

    // Track the page view (fire and forget)
    expClient.TrackAsync(&exp.TrackEvent{
        UserID:    userID,
        EventName: "checkout_page_view",
    })
}

func main() {
    defer expClient.Close()
    http.HandleFunc("/checkout", checkoutHandler)
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

---

## SDK Compatibility

| Platform SDK | Hash Algorithm | Assignment Parity |
|--------------|---------------|-------------------|
| Go | MD5 | Yes |
| Java | MD5 | Yes |
| Python | MD5 | Yes |
| JavaScript | MD5 | Yes |
| React | MD5 | Yes |

All SDKs produce identical variant assignments for the same `(experimentKey, userID)` pair.
