# Experimentation Platform — .NET/C# SDK

Official .NET SDK for the Experimentation Platform. Supports feature flag evaluation,
experiment assignment, and analytics event tracking.

**Target frameworks**: `netstandard2.1` / `net6.0`
**NuGet package**: `ExperimentationPlatform.SDK`
**Version**: 0.1.0

---

## Installation

```bash
dotnet add package ExperimentationPlatform.SDK
```

Or via the NuGet Package Manager:

```
Install-Package ExperimentationPlatform.SDK
```

---

## Quick Start

```csharp
using ExperimentationPlatform;

var config = new SdkConfig("https://your-api.example.com", "your-api-key");
using var client = new ExperimentationClient(config);

// Evaluate a feature flag
var result = await client.EvaluateFlagAsync("new-checkout-ui", userId: "user-42");
if (result.Enabled)
{
    Console.WriteLine($"Variant: {result.Variant}");
}

// Get an experiment assignment
var assignment = await client.GetAssignmentAsync("checkout-cta-test", userId: "user-42");
Console.WriteLine($"In experiment: {assignment?.IsInExperiment}");

// Track an event
await client.TrackAsync("purchase_completed", userId: "user-42",
    properties: new Dictionary<string, object> { { "amount", 49.99 } });
```

---

## Configuration

```csharp
var config = new SdkConfig("https://api.example.com", "your-api-key")
{
    CacheTtlSeconds = 300,   // Cache feature flags for 5 minutes (default: 300)
    TimeoutSeconds  = 10,    // HTTP timeout in seconds (default: 10)
    MaxCacheSize    = 1000   // Max in-memory cached entries (default: 1000)
};
```

---

## API Reference

### `ExperimentationClient`

| Method | Description |
|--------|-------------|
| `EvaluateFlagAsync(flagKey, userId, attributes?, defaultValue?)` | Evaluate a feature flag locally (cached). Never throws. |
| `GetAssignmentAsync(experimentKey, userId, attributes?)` | Retrieve experiment assignment from the API. |
| `TrackAsync(eventName, userId, properties?)` | Send an analytics event. Returns `true` on success. |
| `Dispose()` | Release HTTP resources. |

### `FeatureFlagEvaluator` (static)

| Method | Description |
|--------|-------------|
| `HashUser(userId, flagKey)` | Returns a deterministic bucket value in `[0.0, 1.0)`. |
| `Evaluate(flag, userId, attributes?)` | Evaluate a `FeatureFlag` object locally. |

---

## Consistent Hashing

All Experimentation Platform SDKs use the same hash formula to ensure users are
assigned to the same variant regardless of which SDK is used.

```
MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → / 2^32
```

**Cross-SDK canonical test vector:**

```
HashUser("user-123", "my-flag") == 0.6927449859213084
```

---

## Running Tests

```bash
# Build and test (requires .NET 6 SDK)
cd sdk/dotnet
dotnet test tests/ExperimentationPlatform.Tests/ -v

# Run a specific test class
dotnet test --filter "FullyQualifiedName~HashCompatibilityTests"
```

**Test coverage**: 63 xUnit test methods across 5 test classes:

| Test class | Tests | Coverage |
|------------|-------|----------|
| `HashCompatibilityTests` | 13 | Hash algorithm + cross-SDK parity |
| `FeatureFlagEvaluatorTests` | 15 | Local evaluation logic |
| `CacheTests` | 15 | TTL, LRU eviction, thread safety |
| `ExperimentationHttpClientTests` | 10 | HTTP success/error mapping |
| `ExperimentationClientTests` | 10 | High-level SDK behaviour |

---

## Standalone Hash Verification (no .NET required)

```bash
python3 sdk/dotnet/verify_hash.py
```

This Python script independently computes the same hash and verifies the canonical
test vector matches `0.6927449859213084`.

---

## Project Structure

```
sdk/dotnet/
  ExperimentationPlatform.sln
  src/ExperimentationPlatform/        # SDK source (netstandard2.1 + net6.0)
    SdkConfig.cs
    FeatureFlagEvaluator.cs
    Cache.cs
    ExperimentationHttpClient.cs
    ExperimentationClient.cs
    Models/                           # FeatureFlag, Variant, Assignment, TrackEvent
    Exceptions/                       # ExperimentationException, NetworkException, ApiException, AuthException
  tests/ExperimentationPlatform.Tests/  # xUnit test project (net6.0)
  examples/BasicUsage/                  # Runnable example app
  verify_hash.py                        # Cross-SDK hash parity script
```

---

## Error Handling

The SDK maps HTTP errors to typed exceptions:

| Scenario | Exception |
|----------|-----------|
| HTTP 401 | `AuthException` |
| HTTP 4xx / 5xx | `ApiException` (with `.StatusCode` and `.ResponseBody`) |
| Network / timeout | `NetworkException` |

`EvaluateFlagAsync` and `TrackAsync` **never throw** — they return safe defaults on any error.

---

## License

Apache 2.0 — see the root `LICENSE` file.
