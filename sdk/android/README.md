# Experimentation Platform Android SDK

Kotlin client for the Experimently A/B testing and feature flag platform. Coroutine-based,
OkHttp under the hood, `SharedPreferences`-backed offline fallback, `minSdk 21`.

Flag evaluation and experiment assignment are decided **by the server**: every call goes to the
public API with your `X-API-Key`, the server buckets the user (sticky per user + experiment), and
the SDK caches the answer per user + key for a TTL. Nothing is bucketed locally.

Full reference: [`docs/sdk/android.md`](../../docs/sdk/android.md).

> Toolchain note: the rewire onto the public API was done by inspection only. No gradle / Android
> SDK is installed on the development machine, so the module has **not been compiled or its unit
> tests executed** there. There is no contract smoke for Android (it needs a device runtime);
> unit tests only.

## Installation

```kotlin
// settings.gradle.kts
include(":sdk")
project(":sdk").projectDir = file("../experimentation-platform/sdk/android/sdk")

// build.gradle.kts (app module)
dependencies {
    implementation(project(":sdk"))
}
```

Requires Kotlin 1.9, coroutines 1.7 and OkHttp 4.12 (declared by the module). Package:
`com.experimentationplatform.android`.

## Quick Start

```kotlin
import com.experimentationplatform.android.ExperimentationClient
import com.experimentationplatform.android.SdkConfig
import com.experimentationplatform.android.TrackEvent
import com.experimentationplatform.android.User

val client = ExperimentationClient(
    SdkConfig(
        baseUrl = "http://10.0.2.2:8000",   // origin only; 10.0.2.2 = host localhost from the emulator
        apiKey = BuildConfig.EXPERIMENTLY_API_KEY   // sent as X-API-Key
    )
)

lifecycleScope.launch {
    val user = User(id = "user-123", attributes = mapOf("plan" to "pro", "country" to "US"))

    // Experiment assignment — POST /api/v1/tracking/assign (sticky on the server)
    val assignment = client.getAssignment("checkout_flow", user)
    assignment.variantName      // "control" / "treatment"
    assignment.configuration    // Map<String, Any?>? from the variant definition

    // Feature flag — GET /api/v1/feature-flags/evaluate/new_search?user_id=user-123
    val flag = client.evaluateFlag("new_search", user)
    if (flag.enabled) { /* flag.config holds the server's config payload */ }

    // Track with a key — one POST /api/v1/tracking/track
    client.track(TrackEvent(user.id, "purchase", mapOf("currency" to "USD"),
        experimentKey = "checkout_flow", value = 49.99))

    // Track without a key — fanned out to every cached assignment + flag for the user
    client.track(TrackEvent(user.id, "page_view"))
}
```

## Configuration

| Property | Type | Default | Description |
|---|---|---|---|
| `baseUrl` | `String` | `http://localhost:8000` | Backend origin; the SDK appends `/api/v1/...` |
| `apiKey` | `String` | *(required)* | Sent as `X-API-Key` on every request |
| `timeoutMs` | `Long` | `10000` | OkHttp connect/read/write timeout |
| `cacheSize` | `Int` | `1000` | Max cached evaluations (and, separately, assignments), LRU eviction |
| `cacheTtlMs` | `Long` | `300000` | How long a successful evaluation/assignment is reused |
| `enableLocalEval` | `Boolean` | — | Deprecated no-op kept for source compatibility |

`ExperimentationClient` also accepts an `HttpClient`, two `ResultCache`s and an `OfflineStore`
for injection; pass `OfflineStore(prefsAdapter)` wrapping `context.getSharedPreferences(...)`
to persist results across process restarts.

## API

| Method | Returns | On failure |
|---|---|---|
| `suspend evaluateFlag(flagKey, user)` | `EvalResult(key, enabled, config)` | Last offline value if any, else throws `FlagNotFoundException` (404) / `ServerException` / `NetworkException` |
| `suspend getAssignment(experimentKey, user)` | `Assignment(experimentKey, userId, variantId, variantName, isControl, configuration)` | Last offline value if any, else throws `ServerException` (404 not ACTIVE) / `NetworkException` |
| `suspend track(event)` | `Unit` | Never throws; runs in the background |
| `suspend trackBatch(events)` | `Unit` | Never throws; ≤ 100 events per request |
| `getCachedAssignments(userId)`, `getCachedFlagKeys(userId)` | cached, unexpired entries | — |
| `invalidateCache(userId, key)`, `clearCache()`, `getCacheSize()`, `close()` | — | — |
| `ConsistentHash.compute(userId, key)` | `Double` in `[0, 1)` | Pure function (parity utility) |

## Caching and failure behaviour

- Successful evaluations and assignments are cached in memory per **user + key** for
  `cacheTtlMs` and written to the `OfflineStore`. A cache hit makes no request.
- **Failures are never cached.** On a network/HTTP failure the last successful value from the
  offline store is returned (not re-cached, so the next call retries); with nothing stored the
  call throws, exactly as the SDK did before the rewire.
- `track` / `trackBatch` never throw: the request is launched on a background `Dispatchers.IO`
  scope and failures are swallowed.

## Tracking fan-out

With `experimentKey` and/or `featureFlagKey` set, `track` sends one `POST /api/v1/tracking/track`.
Without a key it sends one `POST /api/v1/tracking/batch` containing one entry per experiment the
user was assigned to through this client (`experiment_key`) plus one per flag evaluated for the
user (`feature_flag_key`), taken from the in-memory cache. Nothing cached → nothing is sent.
`event_type` defaults to the event name; `properties` is sent as `metadata`.

## Consistent hash (compatibility utility)

`ConsistentHash.compute(userId, key)` computes `MD5("{userId}:{key}")`, reads the first 4 bytes as
a little-endian uint32 and divides by 2^32 — `0.6927449859213084` for `("user-123", "my-flag")`.
It is exported only so the golden vectors in `tests/sdk-contract/` keep passing; nothing in the SDK
buckets locally. The former `FeatureFlagEvaluator.hashUser` is a deprecated alias.

## Backend endpoints used

Every request carries `X-API-Key`, `Content-Type: application/json` and `Accept: application/json`.

| SDK call | Method and path | Body / query | Response used |
|---|---|---|---|
| `evaluateFlag` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}`; 404 when the flag is not ACTIVE |
| `getAssignment` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}`; 404 when the experiment is not ACTIVE |
| `track` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `track` without keys, `trackBatch` | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (max 100 per request) | ignored |

## Tests

```bash
cd sdk/android && gradle :sdk:test   # JUnit 5 + MockWebServer, 78 tests (no wrapper checked in; needs Gradle 8 + Android SDK)
```

Unit tests only (JUnit 5 + MockWebServer); there is no contract smoke for Android because it
needs a device runtime, and the live runner manifest
(`tests/sdk-contract/live/run_live_contract.py`) has no `android` entry.

Verified against a live backend: **not yet (toolchain unavailable — no gradle/Android SDK on the
development machine)**. The tests above have not been executed here either.
