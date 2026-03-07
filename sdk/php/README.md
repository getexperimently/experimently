# Experimently PHP SDK

PHP 8.0+ SDK for the Experimently A/B testing and feature flag platform.

## Requirements

- PHP >= 8.0
- `ext-json` (built-in)
- `ext-curl` (built-in)
- Composer (for installation and running PHPUnit tests)

## Installation

```bash
composer require experimently/experimentation-platform-sdk
```

## Quick Start

```php
use ExperimentationPlatform\ExperimentationClient;
use ExperimentationPlatform\SdkConfig;

$config = new SdkConfig(
    baseUrl: 'https://api.example.com',
    apiKey:  'your-api-key',
);

$client = new ExperimentationClient($config);

// Evaluate a feature flag
$result = $client->evaluateFlag('dark-mode', 'user-123');
if ($result['enabled']) {
    // Show dark mode — $result['variant'] and $result['value'] are available
}
```

## Configuration

| Parameter      | Type   | Default | Description                                    |
|----------------|--------|---------|------------------------------------------------|
| `baseUrl`      | string | —       | API base URL (required)                        |
| `apiKey`       | string | —       | SDK API key (required)                         |
| `cacheTtl`     | int    | 300     | Flag cache TTL in seconds                      |
| `timeout`      | int    | 10      | HTTP request timeout in seconds                |
| `maxCacheSize` | int    | 1000    | Maximum cached flag definitions                |

## API

### `evaluateFlag(string $flagKey, string $userId, array $attributes = [], mixed $default = false): array`

Evaluates a feature flag for a user. Returns an array:

```php
[
    'enabled' => true,           // bool — whether the user is in the rollout
    'variant' => 'treatment',   // string|null — assigned variant key
    'value'   => 'on',          // mixed — variant value or $default
]
```

Flag data is fetched from the API once and cached locally. Evaluation is performed client-side using a consistent MD5 hash that matches all other Experimently SDKs (JS, Python, Java, React).

### `getAssignment(string $experimentKey, string $userId, array $attributes = []): ?array`

Fetches the experiment assignment for a user. Returns the assignment array from the API, or `null` if the user is unassigned or an error occurs.

### `track(string $eventName, string $userId, array $properties = []): bool`

Sends a tracking event. Always returns `bool` — never throws. Returns `true` on success, `false` on any error (including network failures), so tracking never interrupts your application.

## Hash Algorithm

The PHP SDK uses the same cross-SDK consistent hash algorithm as all other Experimently SDKs:

```
MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → divide by 2^32
```

Known test vector: `FeatureFlagEvaluator::hashUser("user-123", "my-flag") === 0.6927449859213084`

You can verify locally without composer:

```bash
php sdk/php/test_standalone.php
```

## Error Handling

| Exception              | Extends              | When thrown                          |
|------------------------|----------------------|--------------------------------------|
| `ExperimentationException` | `\RuntimeException` | Base class for all SDK errors       |
| `NetworkException`     | `ExperimentationException` | cURL transport errors, timeouts |
| `ApiException`         | `ExperimentationException` | HTTP 4xx/5xx responses          |
| `AuthException`        | `ApiException`       | HTTP 401 — invalid API key          |

`evaluateFlag()` and `getAssignment()` return safe defaults on error. Only throw if you call `HttpClient` directly.

## Running Tests

```bash
cd sdk/php
composer install
./vendor/bin/phpunit
```

For a quick smoke-test without composer:

```bash
php test_standalone.php
```

## Development

```bash
# Install dependencies
composer install

# Run full test suite
./vendor/bin/phpunit --colors=always

# Run a specific test file
./vendor/bin/phpunit tests/HashCompatibilityTest.php
```

## License

MIT
