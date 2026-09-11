# Experimently PHP SDK

PHP 8.1+ SDK for the Experimently A/B testing and feature flag platform.

Flag evaluation and experiment assignment are decided **by the server**: every call goes to the
public API with your `X-API-Key`, the server buckets the user (sticky per user + experiment), and
the SDK caches the answer per user + key for the current request/process. Nothing is bucketed
locally.

## Requirements

- PHP >= 8.1 (readonly properties)
- `ext-json`, `ext-curl` (built-in)
- Composer only for installation and PHPUnit — the SDK itself has no dependencies

## Installation

```bash
composer require experimently/experimentation-platform-sdk
```

Without composer, `require` the files under `src/` directly (see `examples/contract_smoke.php`).

## Quick Start

```php
use ExperimentationPlatform\ExperimentationClient;
use ExperimentationPlatform\SdkConfig;

$client = new ExperimentationClient(new SdkConfig(
    baseUrl: getenv('EXPERIMENTLY_API_URL') ?: 'http://localhost:8000',  // origin only
    apiKey:  getenv('EXPERIMENTLY_API_KEY'),                             // sent as X-API-Key
));

// Feature flag (GET /api/v1/feature-flags/evaluate/{key}?user_id=…)
$flag = $client->evaluateFlag('dark-mode', 'user-123');
$flag->enabled;   // bool
$flag->config;    // mixed|null — the flag's config payload
$client->isFeatureEnabled('dark-mode', 'user-123');   // bool

// Experiment assignment (POST /api/v1/tracking/assign — sticky on the server)
$assignment = $client->getAssignment('checkout-flow', 'user-123', ['country' => 'US']);
if ($assignment !== null) {
    $assignment->variantName;     // "control" / "treatment"
    $assignment->isControl;       // bool
    $assignment->configuration;   // array|null
}

// Events (never throw)
$client->track('purchase', 'user-123', ['sku' => 'pro'], 'checkout-flow', null, 49.0);
$client->track('page_view', 'user-123', ['page' => '/']);   // no key: fanned out, see below
```

## Configuration

| Parameter      | Type   | Default | Description                                                     |
|----------------|--------|---------|-----------------------------------------------------------------|
| `baseUrl`      | string | —       | Backend origin (required); the SDK appends `/api/v1/...`        |
| `apiKey`       | string | —       | API key (required), sent as `X-API-Key`                          |
| `cacheTtl`     | int    | 300     | Seconds a successful evaluation/assignment is reused             |
| `timeout`      | int    | 10      | HTTP connect/request timeout in seconds                          |
| `maxCacheSize` | int    | 1000    | Maximum cached entries (oldest evicted)                          |

## API

### `evaluateFlag(string $flagKey, string $userId): FlagEvaluation`

`GET /api/v1/feature-flags/evaluate/{flagKey}?user_id={userId}`. Returns a `FlagEvaluation`
with `key`, `enabled` and `config`. On any network/HTTP failure (transport error, 401, 404 when
the flag is not ACTIVE, 429, ...) the flag is reported as **disabled** (`config: null`); a cached
evaluation, when present, is returned instead. Failures are never cached. Never throws on
network/HTTP errors.

### `isFeatureEnabled(string $flagKey, string $userId): bool`

`evaluateFlag(...)->enabled`.

### `getAssignment(string $experimentKey, string $userId, array $attributes = []): ?Assignment`

`POST /api/v1/tracking/assign` with `{experiment_key, user_id, context: $attributes}`. The server
buckets the user, keeps the assignment sticky and records the exposure. Returns an `Assignment`
with `experimentKey`, `variantId`, `variantName`, `isControl` and `configuration`, or **`null`**
on any network/HTTP failure (including 404 when the experiment is not ACTIVE); a cached
assignment, when present, is returned instead. Failures are never cached. Never throws on
network/HTTP errors.

### `track(string $eventName, string $userId, array $properties = [], ?string $experimentKey = null, ?string $featureFlagKey = null, ?float $value = null, ?string $eventType = null): bool`

Never throws; returns `true` when every request succeeded.

- With `$experimentKey` and/or `$featureFlagKey`: one `POST /api/v1/tracking/track`.
- Without a key: one `POST /api/v1/tracking/batch` containing one entry per experiment the user
  has been assigned to through this client plus one per flag evaluated for the user (both from the
  cache). If nothing is cached for the user, nothing is sent and `true` is returned.

`$properties` is sent as `metadata`; `$eventType` defaults to `$eventName`; the timestamp is now
(UTC).

### `trackBatch(array $events): BatchResult`

`POST /api/v1/tracking/batch` in chunks of at most 100 events. Each event is an array with
`event_name` and `user_id` plus at least one of `experiment_key` / `feature_flag_key` (the server
rejects key-less events); optional `properties`, `value`, `event_type`, `timestamp`. Malformed
events are counted as failures without being sent. Returns a `BatchResult` (`successCount`,
`failureCount`, `errors`, `isOk()`). Never throws.

### Cache helpers

`getAssignments(string $userId): Assignment[]`, `getEvaluatedFlags(string $userId): string[]`,
`clearCache(): void`.

## Backend endpoints used

Every request carries `X-API-Key`, `Content-Type: application/json` and `Accept: application/json`.

| SDK call | Method and path | Body / query | Response used |
|---|---|---|---|
| `evaluateFlag`, `isFeatureEnabled` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}`; off with `reason: "inactive"` when the flag exists but is not ACTIVE; 404 only for an unknown key |
| `getAssignment` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}`; 404 when the experiment is not ACTIVE |
| `track` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `track` without keys, `trackBatch` | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (max 100 per request) | `{success_count, failure_count, errors}` |

## Error Handling

`evaluateFlag()`, `getAssignment()`, `track()` and `trackBatch()` never throw — they return a
disabled flag / `null` / `false` / a `BatchResult` with failures. Only `HttpClient` throws:

| Exception                  | Extends                    | When                                          |
|----------------------------|----------------------------|-----------------------------------------------|
| `ExperimentationException` | `\RuntimeException`        | Base class for all SDK errors                 |
| `NetworkException`         | `ExperimentationException` | cURL transport errors, timeouts               |
| `ApiException`             | `ExperimentationException` | HTTP 4xx/5xx (`getStatusCode()`)              |
| `AuthException`            | `ApiException`             | HTTP 401 — invalid API key                    |

## Hash Utility

`FeatureFlagEvaluator::hashUser($userId, $key)` implements the cross-SDK formula
`MD5("{userId}:{key}")` → first 4 bytes as little-endian uint32 / 2^32 and is pinned by the
golden-vector tests in `tests/sdk-contract/`:

```php
FeatureFlagEvaluator::hashUser('user-123', 'my-flag');   // 0.6927449859213084
```

It is exported as a utility only — nothing in the SDK uses it to decide a variant.

## Contract smoke

```bash
EXPERIMENTLY_API_KEY=<key> php sdk/php/examples/contract_smoke.php
# {"sdk":"php","assign":{"variant_name":"control","is_control":true,"sticky":true},"flag":{"enabled":true},"track":{"ok":true},"fanout":{"ok":true}}
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (default `sdk_contract_ab`), `CONTRACT_FLAG_KEY` (default
`sdk_contract_flag`), `CONTRACT_USER_ID` (default random `smoke-<uuid>`). Works without
`composer install` (it `require`s `src/` directly when `vendor/` is absent).

Verified against a live backend: **not yet (toolchain unavailable — no `php` on the
development machine)**. Run `python tests/sdk-contract/live/run_live_contract.py --sdk php --strict`
on a machine with PHP 8.1+.

## Running Tests

```bash
cd sdk/php
composer install
./vendor/bin/phpunit            # PHPUnit 10; HTTP is faked (tests/FakeHttpClient.php)

php test_standalone.php         # no composer needed: hash vector, types, cache, client request shapes
```

The PHPUnit suite (client, cache, HTTP client, hash tests) and `test_standalone.php` were reviewed
line by line for the server-side rewire but **not executed** on the development machine (no
`php`/`composer` installed); run them on a machine with PHP 8.1+.

## License

MIT
