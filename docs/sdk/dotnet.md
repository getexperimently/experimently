# .NET SDK

The .NET SDK provides feature flag evaluation, experiment variant assignment, and event tracking for .NET applications. It targets `netstandard2.1` and `net6.0`, uses `System.Text.Json` for zero-dependency serialisation, `HttpClient` for network calls, and maintains an LRU cache with configurable TTL for low-latency repeated evaluations.

---

## Requirements

- .NET Standard 2.1 compatible runtime, or .NET 6.0+
- No additional NuGet dependencies beyond the SDK itself

---

## Installation

```bash
dotnet add package Experimently.SDK
```

Or add to your `.csproj`:

```xml
<PackageReference Include="Experimently.SDK" Version="1.*" />
```

---

## Quick Start

```csharp
using Experimently;

await using var client = new ExperimentlyClient(new SdkConfig
{
    BaseUrl = "https://api.example.com",
    ApiKey  = Environment.GetEnvironmentVariable("EXPERIMENTLY_API_KEY")!,
});

bool enabled = await client.EvaluateFlagAsync("new-checkout", "user-123", defaultValue: false);

if (enabled)
{
    // show new checkout experience
}
```

---

## Configuration

```csharp
var config = new SdkConfig
{
    BaseUrl   = "https://api.example.com",  // Required
    ApiKey    = "your-api-key",             // Required
    CacheTtl  = TimeSpan.FromSeconds(60),   // Default: 60 s
    Timeout   = TimeSpan.FromSeconds(5),    // Default: 5 s
    CacheSize = 1000,                       // Maximum LRU cache entries (default: 1000)
};

await using var client = new ExperimentlyClient(config);
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `BaseUrl` | `string` | *(required)* | Base URL of the platform API |
| `ApiKey` | `string` | *(required)* | API key for SDK authentication |
| `CacheTtl` | `TimeSpan` | `60s` | Time before a cached evaluation expires |
| `Timeout` | `TimeSpan` | `5s` | HTTP request timeout |
| `CacheSize` | `int` | `1000` | Maximum number of entries in the LRU cache |

The `ExperimentlyClient` implements both `IDisposable` and `IAsyncDisposable`. Prefer `await using` in async contexts so the client flushes pending events before disposal.

---

## Feature Flag Evaluation

### `EvaluateFlagAsync`

Returns the flag value for the given user. Returns `defaultValue` on any error so your application always has a safe fallback.

```csharp
bool enabled = await client.EvaluateFlagAsync("dark-mode", userId, defaultValue: false);

if (enabled)
{
    RenderDarkMode();
}
```

Pass user attributes for server-side targeting rules:

```csharp
bool enabled = await client.EvaluateFlagAsync(
    flagKey:      "enterprise-dashboard",
    userId:       userId,
    defaultValue: false,
    attributes: new Dictionary<string, object>
    {
        ["plan"]    = "enterprise",
        ["country"] = "US",
        ["beta"]    = true,
    }
);
```

---

## Experiment Assignment

### `GetAssignmentAsync`

Returns an `Assignment` record describing the variant assigned to the user.

```csharp
Assignment assignment = await client.GetAssignmentAsync("checkout-cta-copy", userId);

string view = assignment.VariantKey switch
{
    "control"     => "Views/Checkout/Original",
    "treatment-a" => "Views/Checkout/ShortCta",
    "treatment-b" => "Views/Checkout/UrgencyCta",
    _             => "Views/Checkout/Original",
};
```

The `Assignment` record exposes:

| Property | Type | Description |
|----------|------|-------------|
| `VariantKey` | `string` | Assigned variant (e.g., `"control"`, `"treatment"`) |
| `ExperimentKey` | `string` | The experiment key |
| `ExperimentId` | `Guid` | UUID of the experiment |
| `IsControl` | `bool` | `true` if this is the control variant |

---

## Event Tracking

### `TrackAsync`

Records a conversion or behavioural event. Call after meaningful user actions such as purchases, sign-ups, or form submissions.

```csharp
await client.TrackAsync("purchase", userId, new Dictionary<string, object>
{
    ["amount"]   = 99.99,
    ["currency"] = "USD",
    ["sku"]      = "pro-plan",
});
```

Fire-and-forget variant (non-blocking):

```csharp
client.TrackFireAndForget("page_view", userId);
```

`TrackFireAndForget` enqueues the event internally and returns immediately. Call `DisposeAsync()` (or `await using`) before process exit to ensure the buffer is flushed.

---

## Dependency Injection (ASP.NET Core)

### Register the Client

```csharp
// Program.cs
builder.Services.AddExperimently(options =>
{
    options.BaseUrl  = builder.Configuration["Experimently:BaseUrl"]!;
    options.ApiKey   = builder.Configuration["Experimently:ApiKey"]!;
    options.CacheTtl = TimeSpan.FromSeconds(30);
});
```

The `AddExperimently` extension registers `IExperimentlyClient` as a singleton and wires up graceful shutdown via `IHostApplicationLifetime`.

### Inject into Controllers

```csharp
[ApiController]
[Route("api/[controller]")]
public class CheckoutController : ControllerBase
{
    private readonly IExperimentlyClient _exp;

    public CheckoutController(IExperimentlyClient exp)
    {
        _exp = exp;
    }

    [HttpGet]
    public async Task<IActionResult> Get()
    {
        string userId = User.FindFirst("sub")?.Value ?? "anonymous";

        bool newFlow = await _exp.EvaluateFlagAsync("new-checkout", userId, false);
        var  assignment = await _exp.GetAssignmentAsync("checkout-cta-test", userId);

        await _exp.TrackAsync("checkout_view", userId);

        return Ok(new { newFlow, cta = assignment.VariantKey });
    }
}
```

### appsettings.json

```json
{
  "Experimently": {
    "BaseUrl": "https://api.example.com",
    "ApiKey":  "your-api-key",
    "CacheTtlSeconds": 30,
    "TimeoutSeconds":  5
  }
}
```

---

## Consistent Hash Algorithm

Variant assignment uses MD5-based consistent hashing. The hash input is the string `"{userId}:{flagKey}"`. The first 4 bytes of the MD5 digest are converted to a little-endian unsigned 32-bit integer with `BitConverter.ToUInt32`, then divided by `4294967296.0` to produce a value in `[0, 1)`.

```csharp
using System.Security.Cryptography;
using System.Text;

static double Bucket(string userId, string flagKey)
{
    byte[] input  = Encoding.UTF8.GetBytes($"{userId}:{flagKey}");
    byte[] digest = MD5.HashData(input);
    // BitConverter.ToUInt32 reads little-endian on all .NET platforms
    uint value = BitConverter.ToUInt32(digest, 0);
    return value / 4_294_967_296.0;
}
```

This algorithm is identical across all platform SDKs. A user bucketed server-side (.NET) will always fall in the same bucket as one evaluated in Go, Java, Ruby, PHP, or any other SDK.

---

## LRU Cache

The SDK maintains an internal LRU cache keyed by `(flagKey, userId)`. Cache entries expire after `CacheTtl`. The cache is thread-safe; concurrent reads do not block each other.

To bypass the cache for a single call (e.g., in tests):

```csharp
bool enabled = await client.EvaluateFlagAsync(
    "my-flag", userId, false, skipCache: true);
```

---

## Testing with xUnit

```csharp
using Experimently.Testing;
using Xunit;

public class CheckoutControllerTests
{
    [Fact]
    public async Task Shows_new_flow_when_flag_is_enabled()
    {
        var stub = new StubExperimentlyClient();
        stub.SetFlag("new-checkout", true);
        stub.SetVariant("cta-test", "treatment-b");

        var controller = new CheckoutController(stub);
        var result     = await controller.Get() as OkObjectResult;

        Assert.NotNull(result);
        dynamic body = result!.Value!;
        Assert.True((bool)body.newFlow);
        Assert.Equal("treatment-b", (string)body.cta);
    }
}
```

`StubExperimentlyClient` implements `IExperimentlyClient` and lets you pre-configure flag values and variant assignments without any HTTP calls.

---

## Cleanup

`ExperimentlyClient` implements `IAsyncDisposable`:

```csharp
await using var client = new ExperimentlyClient(config);
// ... use client ...
// Disposal flushes pending events automatically
```

When using dependency injection, disposal is handled automatically by the ASP.NET Core host on shutdown.

---

## SDK Compatibility

All platform SDKs produce identical variant assignments for the same `(userId, flagKey)` pair.

| SDK | Hash Algorithm | Assignment Parity |
|-----|---------------|-------------------|
| .NET | MD5 | Yes |
| Ruby | MD5 | Yes |
| PHP | MD5 | Yes |
| Go | MD5 | Yes |
| Java | MD5 | Yes |
| Python | MD5 | Yes |
| JavaScript | MD5 | Yes |
| Elixir | MD5 | Yes |
