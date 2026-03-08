# Elixir SDK

The Elixir SDK provides feature flag evaluation, experiment variant assignment, and event tracking for Elixir and Phoenix applications. It is built as an OTP application: a `GenServer` process manages configuration and coordinates cache refresh, while an ETS table provides zero-allocation concurrent lookups. HTTP calls use Erlang's built-in `:httpc` client, and JSON encoding/decoding relies on the `Jason` library. The SDK ships with 93 ExUnit tests.

---

## Requirements

- Elixir 1.13 or later
- OTP 24 or later
- `Jason` hex package (listed as a dependency automatically)

---

## Installation

Add to your `mix.exs` dependencies:

```elixir
defp deps do
  [
    {:experimently, "~> 0.1"},
  ]
end
```

Then fetch dependencies:

```bash
mix deps.get
```

---

## Quick Start

```elixir
# In your application code (after the client is started — see Supervision Tree below)
enabled = Experimently.Client.evaluate_flag("new-checkout", "user-123", false)

if enabled do
  render_new_checkout()
end
```

---

## Application Configuration

Add configuration to `config/config.exs` (or environment-specific config files):

```elixir
# config/config.exs
config :experimently,
  base_url:  System.get_env("EXPERIMENTLY_BASE_URL", "https://api.example.com"),
  api_key:   System.get_env("EXPERIMENTLY_API_KEY"),
  cache_ttl: 60,      # seconds before a cached result expires (default: 60)
  timeout:   5_000    # HTTP timeout in milliseconds (default: 5000)
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `:base_url` | `string` | *(required)* | Base URL of the platform API |
| `:api_key` | `string` | *(required)* | API key for SDK authentication |
| `:cache_ttl` | `integer` | `60` | Seconds before a cached evaluation expires |
| `:timeout` | `integer` | `5000` | HTTP request timeout in milliseconds |

---

## Supervision Tree

Add `Experimently.Client` to your application's supervision tree so it starts automatically with your app:

```elixir
# lib/my_app/application.ex
defmodule MyApp.Application do
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      # ... your other children ...
      Experimently.Client,
    ]

    opts = [strategy: :one_for_one, name: MyApp.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
```

The `Experimently.Client` GenServer initialises an ETS table on startup and begins serving requests immediately.

---

## Feature Flag Evaluation

### `Experimently.Client.evaluate_flag/3`

Returns the flag's value for the given user. Returns the `default` value on any error.

```elixir
enabled = Experimently.Client.evaluate_flag("dark-mode", "user-456", false)

if enabled do
  render_dark_mode()
end
```

Pass user attributes for server-side targeting rules:

```elixir
enabled = Experimently.Client.evaluate_flag(
  "enterprise-dashboard",
  "user-789",
  false,
  %{plan: "enterprise", country: "US", beta: true}
)
```

---

## Experiment Assignment

### `Experimently.Client.get_assignment/2`

Returns a map describing the variant assigned to the user.

```elixir
assignment = Experimently.Client.get_assignment("checkout-cta-copy", "user-123")

case assignment.variant_key do
  "control"     -> render_original_cta()
  "treatment-a" -> render_short_cta()
  "treatment-b" -> render_urgency_cta()
  _             -> render_original_cta()
end
```

The returned map includes:

| Key | Type | Description |
|-----|------|-------------|
| `:variant_key` | `String.t()` | Assigned variant (e.g., `"control"`, `"treatment"`) |
| `:experiment_key` | `String.t()` | The experiment key |
| `:experiment_id` | `String.t()` | UUID of the experiment |
| `:is_control` | `boolean()` | `true` if this is the control variant |

---

## Event Tracking

### `Experimently.Client.track/3`

Records a conversion or behavioural event. Call after meaningful user actions.

```elixir
Experimently.Client.track("purchase", "user-123", %{
  amount:   99.99,
  currency: "USD",
  sku:      "pro-plan"
})
```

`track/3` is asynchronous by default: the event is cast to the GenServer and the call returns immediately. The GenServer batches events and forwards them to the platform API.

---

## GenServer + ETS Architecture

The SDK uses two OTP primitives:

1. **GenServer** — owns the lifecycle, configuration, and periodic cache refresh. Handles `cast` messages for tracking events and batching them for upload.
2. **ETS table** — stores evaluated flag results indexed by `{flag_key, user_id}`. ETS allows concurrent reads from any process without going through the GenServer, giving O(1) lookup with no message passing overhead.

```
Request process          GenServer              ETS table
─────────────            ─────────              ─────────
evaluate_flag/3 ──────────────────────────────> :ets.lookup/2
                         (miss) ──HTTP──> API
                                          │
                         <─ result ───────┘
                         :ets.insert ──────────> cached entry
evaluate_flag/3 ──────────────────────────────> :ets.lookup/2  (hit, no GenServer call)
```

---

## Consistent Hash Algorithm

Variant assignment uses MD5-based consistent hashing. The hash input is the string `"#{user_id}:#{flag_key}"`. The first 4 bytes of the digest are decoded as a little-endian unsigned 32-bit integer, then divided by `4294967296.0` to produce a value in `[0, 1)`.

```elixir
defp bucket(user_id, flag_key) do
  :crypto.hash(:md5, "#{user_id}:#{flag_key}")
  |> binary_part(0, 4)
  |> :binary.decode_unsigned(:little)
  |> Kernel./(4_294_967_296.0)
end
```

This algorithm is identical across all platform SDKs. A user bucketed server-side (Elixir) will always fall in the same bucket as one evaluated in Go, Java, Ruby, PHP, .NET, or any other SDK.

---

## Phoenix Controller Integration

```elixir
defmodule MyAppWeb.CheckoutController do
  use MyAppWeb, :controller

  def show(conn, _params) do
    user_id = get_session(conn, :user_id) || "anonymous"

    enabled    = Experimently.Client.evaluate_flag("new-checkout", user_id, false)
    assignment = Experimently.Client.get_assignment("checkout-cta-copy", user_id)

    Experimently.Client.track("checkout_view", user_id, %{path: conn.request_path})

    render(conn, :show,
      new_checkout: enabled,
      cta_variant:  assignment.variant_key
    )
  end
end
```

### Template Usage

```heex
<%= if @new_checkout do %>
  <%= render("new_checkout.html", cta: @cta_variant) %>
<% else %>
  <%= render("checkout.html", []) %>
<% end %>
```

---

## Testing with ExUnit

### Using the Stub Module

```elixir
defmodule MyApp.CheckoutControllerTest do
  use MyAppWeb.ConnCase

  import Experimently.Testing

  setup do
    stub_flag("new-checkout", true)
    stub_variant("checkout-cta-copy", "treatment-b")
    :ok
  end

  test "shows new checkout when flag is enabled", %{conn: conn} do
    conn = get(conn, ~p"/checkout")
    assert html_response(conn, 200) =~ "new-checkout"
  end
end
```

### Manual Mocking with Mox

```elixir
# test/support/mocks.ex
Mox.defmock(Experimently.MockClient, for: Experimently.ClientBehaviour)

# test/my_app/checkout_test.exs
defmodule MyApp.CheckoutTest do
  use ExUnit.Case, async: true
  import Mox

  setup :verify_on_exit!

  test "evaluate_flag returns true for enabled flag" do
    expect(Experimently.MockClient, :evaluate_flag, fn "new-checkout", _user_id, _default ->
      true
    end)

    assert MyApp.Checkout.show_new_flow?("user-123") == true
  end
end
```

---

## OTP Supervision and Fault Tolerance

The `Experimently.Client` GenServer will restart automatically under `:one_for_one` supervision if it crashes. The ETS table is owned by the GenServer process; on restart, the table is recreated and populated from the API. Requests served during the restart window fall back to the configured `default` values.

To increase resilience in high-availability deployments, run multiple application nodes — each maintains its own local cache and makes independent API calls.

---

## SDK Compatibility

All platform SDKs produce identical variant assignments for the same `(user_id, flag_key)` pair.

| SDK | Hash Algorithm | Assignment Parity |
|-----|---------------|-------------------|
| Elixir | MD5 | Yes |
| Ruby | MD5 | Yes |
| PHP | MD5 | Yes |
| Go | MD5 | Yes |
| Java | MD5 | Yes |
| Python | MD5 | Yes |
| JavaScript | MD5 | Yes |
| .NET | MD5 | Yes |
