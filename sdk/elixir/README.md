# ExperimentationPlatform Elixir SDK

Elixir SDK for the Experimentation Platform — A/B testing and feature flag evaluation.

## Features

- Cross-SDK consistent hashing (MD5, compatible with JS/Python/Java/Go/Ruby SDKs)
- ETS-backed in-process cache with configurable TTL and max size
- OTP-native HTTP via `:httpc` (zero external runtime deps beyond Jason)
- GenServer-based client for supervised process lifecycle
- Behaviour-based HTTP client for easy testing with mock modules
- Full ExUnit test suite (60+ tests)

## Installation

Add to your `mix.exs`:

```elixir
defp deps do
  [
    {:experimentation_platform, "~> 0.1.0"}
  ]
end
```

## Quick Start

```elixir
# Start a client
{:ok, client} = ExperimentationPlatform.start(
  base_url: "https://api.example.com",
  api_key: "your-api-key"
)

# Evaluate a feature flag
case ExperimentationPlatform.evaluate_flag(client, "dark-mode", "user-123") do
  {:ok, nil}     -> render_default()
  {:ok, variant} -> render_variant(variant)
  {:error, _}    -> render_default()
end

# Get experiment assignment
{:ok, variant} = ExperimentationPlatform.get_assignment(client, "checkout-exp", "user-123")

# Track an event (fire-and-forget)
ExperimentationPlatform.track(client, "purchase_completed", "user-123", %{amount: 49.99})

# Stop the client
ExperimentationPlatform.stop(client)
```

## Configuration

| Option            | Type    | Required | Default  | Description                         |
|-------------------|---------|----------|----------|-------------------------------------|
| `:base_url`       | string  | yes      | —        | API base URL                        |
| `:api_key`        | string  | yes      | —        | API key for authentication          |
| `:cache_ttl`      | integer | no       | 300      | Cache TTL in seconds                |
| `:timeout`        | integer | no       | 10_000   | HTTP timeout in milliseconds        |
| `:max_cache_size` | integer | no       | 1_000    | Maximum cached entries              |
| `:http_client`    | module  | no       | HttpClient | HTTP module (for testing)         |

## Architecture

```
ExperimentationPlatform          <- Public facade
  └── Client (GenServer)         <- Manages config, HTTP, cache lifecycle
        └── Cache (GenServer)    <- ETS-backed TTL cache (per-client)
              └── :ets table     <- Actual storage

ExperimentationPlatform.Evaluator  <- Pure functions (hash + flag eval)
ExperimentationPlatform.HttpClient <- :httpc-based HTTP (implements HttpBehaviour)
```

## Hash Compatibility

The SDK uses MD5-based consistent hashing compatible with all platform SDKs:

```elixir
ExperimentationPlatform.Evaluator.hash_user("user-123", "my-flag")
# => 0.6927449859213084
```

Formula: `MD5("{userId}:{flagKey}") -> first 4 bytes as little-endian uint32 / 2^32`

Verify cross-SDK parity:

```bash
python3 sdk/elixir/verify_hash.py
```

## Testing

```bash
cd sdk/elixir
mix deps.get
mix test
```

Run with coverage:

```bash
mix test --cover
```

## Testing Your Integration

Inject a mock HTTP client via the `:http_client` config option:

```elixir
defmodule MyMockHttp do
  @behaviour ExperimentationPlatform.HttpBehaviour

  @impl true
  def get(_config, "/api/v1/feature-flags/my-flag") do
    {:ok, %{"key" => "my-flag", "enabled" => true,
            "rollout_percentage" => 100, "variants" => [%{"name" => "treatment"}]}}
  end

  @impl true
  def post(_config, _path, _body), do: {:ok, %{}}
end

# In your test:
{:ok, client} = ExperimentationPlatform.start(
  base_url: "http://localhost",
  api_key: "test",
  http_client: MyMockHttp
)
```

## License

MIT
