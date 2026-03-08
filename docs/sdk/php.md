# PHP SDK

The PHP SDK provides feature flag evaluation, experiment variant assignment, and event tracking for PHP applications. It requires only the `ext-json` and `ext-curl` PHP extensions (both enabled by default in standard PHP installations) and is compatible with any PSR-compliant application stack.

---

## Requirements

- PHP 7.4 or later
- `ext-json` (standard)
- `ext-curl` (standard)

---

## Installation

```bash
composer require experimently/sdk
```

---

## Quick Start

```php
<?php

use Experimently\Client;

$client = new Client([
    'base_url' => 'https://api.example.com',
    'api_key'  => getenv('EXPERIMENTLY_API_KEY'),
]);

$enabled = $client->evaluateFlag('new-checkout', 'user-123', false);

if ($enabled) {
    // show new checkout experience
}
```

---

## Configuration

```php
$client = new Client([
    'base_url'   => 'https://api.example.com',  // Required
    'api_key'    => 'your-api-key',              // Required
    'cache_ttl'  => 60,                          // Seconds before a cached result expires (default: 60)
    'timeout'    => 5,                           // cURL timeout in seconds (default: 5)
    'cache_size' => 1000,                        // Maximum number of entries in the cache (default: 1000)
]);
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `base_url` | `string` | *(required)* | Base URL of the platform API |
| `api_key` | `string` | *(required)* | API key for SDK authentication |
| `cache_ttl` | `int` | `60` | Seconds before a cached evaluation expires |
| `timeout` | `int` | `5` | cURL HTTP timeout in seconds |
| `cache_size` | `int` | `1000` | Maximum LRU cache entries |

---

## Feature Flag Evaluation

### `evaluateFlag($flagKey, $userId, $default, $attributes = [])`

Returns the flag value for the given user. Returns `$default` on any error so your application always gets a usable answer.

```php
$enabled = $client->evaluateFlag('dark-mode', 'user-456', false);

if ($enabled) {
    $this->renderDarkMode();
}
```

Pass user attributes for server-side targeting rules:

```php
$enabled = $client->evaluateFlag(
    'enterprise-dashboard',
    'user-789',
    false,
    [
        'plan'    => 'enterprise',
        'country' => 'US',
        'beta'    => true,
    ]
);
```

---

## Experiment Assignment

### `getAssignment($experimentKey, $userId, $attributes = [])`

Returns an associative array describing the variant assigned to the user.

```php
$assignment = $client->getAssignment('checkout-cta-copy', 'user-123');

switch ($assignment['variant_key']) {
    case 'control':
        $this->renderOriginalCta();
        break;
    case 'treatment-a':
        $this->renderShortCta();
        break;
    case 'treatment-b':
        $this->renderUrgencyCta();
        break;
    default:
        $this->renderOriginalCta();
}
```

The returned array includes:

| Key | Type | Description |
|-----|------|-------------|
| `variant_key` | `string` | Assigned variant (e.g., `"control"`, `"treatment"`) |
| `experiment_key` | `string` | The experiment key |
| `experiment_id` | `string` | UUID of the experiment |
| `is_control` | `bool` | `true` if this is the control variant |

---

## Event Tracking

### `track($eventName, $userId, $properties = [])`

Records a conversion or behavioural event. Call this after meaningful user actions such as purchases, sign-ups, or form submissions.

```php
$client->track('purchase', 'user-123', [
    'amount'   => 99.99,
    'currency' => 'USD',
    'sku'      => 'pro-plan',
]);
```

Properties are arbitrary key-value pairs. Numeric values are used as the metric measurement for statistical analysis.

---

## Consistent Hash Algorithm

Variant assignment uses MD5-based consistent hashing. The hash input is the string `"{userId}:{flagKey}"`. The first 4 bytes of the raw MD5 digest are unpacked as a little-endian unsigned 32-bit integer, then divided by `4294967296.0` to produce a value in `[0, 1)`.

```php
function bucket(string $userId, string $key): float
{
    $raw = md5("{$userId}:{$key}", true); // raw binary output
    $int = unpack('V', substr($raw, 0, 4))[1];
    return $int / 4294967296.0;
}
```

This algorithm is identical across all platform SDKs. A user bucketed in PHP will always fall in the same bucket as one evaluated in Go, Java, Ruby, or any other SDK.

---

## Laravel Service Provider

### Register the Provider

```php
// config/app.php
'providers' => [
    // ...
    Experimently\Laravel\ExperimentlyServiceProvider::class,
],
```

### Publish Configuration

```bash
php artisan vendor:publish --provider="Experimently\Laravel\ExperimentlyServiceProvider"
```

This creates `config/experimently.php`:

```php
<?php

return [
    'base_url' => env('EXPERIMENTLY_BASE_URL', 'https://api.example.com'),
    'api_key'  => env('EXPERIMENTLY_API_KEY'),
    'cache_ttl' => env('EXPERIMENTLY_CACHE_TTL', 60),
    'timeout'   => env('EXPERIMENTLY_TIMEOUT', 5),
];
```

### Inject the Client

```php
<?php

namespace App\Http\Controllers;

use Experimently\Client as ExperimentlyClient;
use Illuminate\Http\Request;

class CheckoutController extends Controller
{
    public function __construct(private readonly ExperimentlyClient $exp) {}

    public function show(Request $request)
    {
        $userId = (string) auth()->id() ?? 'anonymous';

        $enabled = $this->exp->evaluateFlag('new-checkout', $userId, false, [
            'plan'    => auth()->user()?->plan,
            'country' => $request->header('CF-IPCountry', 'XX'),
        ]);

        return view($enabled ? 'checkout.new' : 'checkout.legacy');
    }
}
```

### Blade Directive

The service provider registers a `@feature` Blade directive:

```blade
@feature('new-nav')
    @include('partials.new-nav')
@else
    @include('partials.nav')
@endfeature
```

---

## Testing

### Using the Stub Client

```php
use Experimently\Testing\StubClient;

$stub = new StubClient();
$stub->setFlag('new-checkout', true);
$stub->setVariant('cta-copy-test', 'treatment-b');

// Inject stub into your code under test
$controller = new CheckoutController($stub);
```

### PHPUnit Example

```php
<?php

use PHPUnit\Framework\TestCase;
use Experimently\Testing\StubClient;
use App\Http\Controllers\CheckoutController;

class CheckoutControllerTest extends TestCase
{
    public function test_shows_new_checkout_when_flag_enabled(): void
    {
        $stub = new StubClient();
        $stub->setFlag('new-checkout', true);

        $controller = new CheckoutController($stub);
        $response   = $controller->show($this->createMockRequest());

        $this->assertStringContainsString('checkout.new', $response->getOriginalContent()->getName());
    }
}
```

---

## SDK Compatibility

All platform SDKs produce identical variant assignments for the same `(userId, flagKey)` pair.

| SDK | Hash Algorithm | Assignment Parity |
|-----|---------------|-------------------|
| PHP | MD5 | Yes |
| Ruby | MD5 | Yes |
| Go | MD5 | Yes |
| Java | MD5 | Yes |
| Python | MD5 | Yes |
| JavaScript | MD5 | Yes |
| .NET | MD5 | Yes |
| Elixir | MD5 | Yes |
