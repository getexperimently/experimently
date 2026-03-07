# Basic Usage Example — ExperimentationPlatform Elixir SDK
#
# This example demonstrates the core functionality of the SDK.
# In a real application, replace the base_url and api_key with your actual values.
#
# Run with:
#   cd sdk/elixir
#   mix deps.get
#   mix run examples/basic_usage.exs

# -------------------------------------------------------------------
# 1. Start the client
# -------------------------------------------------------------------
IO.puts("Starting ExperimentationPlatform client...")

{:ok, client} = ExperimentationPlatform.start(
  base_url: "https://api.example.com",
  api_key: "your-api-key-here",
  cache_ttl: 300,          # Cache flags for 5 minutes
  timeout: 10_000,         # 10 second HTTP timeout
  max_cache_size: 1_000    # Keep up to 1000 entries in cache
)

IO.puts("Client started: #{inspect(client)}\n")

# -------------------------------------------------------------------
# 2. Evaluate a feature flag
# -------------------------------------------------------------------
user_id = "user-#{System.unique_integer([:positive])}"

IO.puts("Evaluating feature flag 'dark-mode' for user #{user_id}...")

case ExperimentationPlatform.evaluate_flag(client, "dark-mode", user_id) do
  {:ok, nil} ->
    IO.puts("  => User not in rollout — showing default light mode")

  {:ok, %{"name" => variant_name} = variant} ->
    IO.puts("  => User in rollout! Variant: #{variant_name}")
    IO.puts("     Full variant: #{inspect(variant)}")

  {:error, {:auth_error, 401}} ->
    IO.puts("  => Authentication failed — check your API key")

  {:error, {:network_error, reason}} ->
    IO.puts("  => Network error: #{inspect(reason)} — using default")

  {:error, reason} ->
    IO.puts("  => Error: #{inspect(reason)} — using default")
end

IO.puts("")

# -------------------------------------------------------------------
# 3. Evaluate with user attributes (for targeting rules)
# -------------------------------------------------------------------
IO.puts("Evaluating 'premium-features' flag with attributes...")

case ExperimentationPlatform.evaluate_flag(
  client,
  "premium-features",
  user_id,
  attributes: %{
    plan: "pro",
    country: "US",
    account_age_days: 180
  }
) do
  {:ok, nil} ->
    IO.puts("  => Not eligible for premium features")

  {:ok, variant} ->
    IO.puts("  => Premium features enabled! Variant: #{inspect(variant)}")

  {:error, reason} ->
    IO.puts("  => Could not evaluate: #{inspect(reason)}")
end

IO.puts("")

# -------------------------------------------------------------------
# 4. Get experiment assignment
# -------------------------------------------------------------------
IO.puts("Getting experiment assignment for 'checkout-flow-experiment'...")

case ExperimentationPlatform.get_assignment(client, "checkout-flow-experiment", user_id) do
  {:ok, nil} ->
    IO.puts("  => User not in experiment — showing default checkout")

  {:ok, %{"name" => "control"}} ->
    IO.puts("  => User in CONTROL group — showing existing checkout")

  {:ok, %{"name" => "treatment_v1"}} ->
    IO.puts("  => User in TREATMENT V1 — showing new streamlined checkout")

  {:ok, variant} ->
    IO.puts("  => User assigned to: #{inspect(variant)}")

  {:error, reason} ->
    IO.puts("  => Assignment error: #{inspect(reason)}")
end

IO.puts("")

# -------------------------------------------------------------------
# 5. Track events (fire-and-forget)
# -------------------------------------------------------------------
IO.puts("Tracking events...")

# Basic event
:ok = ExperimentationPlatform.track(client, "page_viewed", user_id)
IO.puts("  => Tracked: page_viewed")

# Event with properties
:ok = ExperimentationPlatform.track(client, "button_clicked", user_id, %{
  button_id: "cta-primary",
  page: "checkout",
  position: "above_fold"
})
IO.puts("  => Tracked: button_clicked (with properties)")

# Conversion event
:ok = ExperimentationPlatform.track(client, "purchase_completed", user_id, %{
  order_id: "ord-12345",
  amount: 99.99,
  currency: "USD",
  items_count: 3
})
IO.puts("  => Tracked: purchase_completed")

IO.puts("")

# -------------------------------------------------------------------
# 6. Direct hash inspection (cross-SDK compatibility check)
# -------------------------------------------------------------------
IO.puts("Cross-SDK hash check:")
h = ExperimentationPlatform.Evaluator.hash_user("user-123", "my-flag")
expected = 0.6927449859213084
diff = abs(h - expected)
IO.puts("  hash_user(\"user-123\", \"my-flag\") = #{h}")
IO.puts("  expected:                           #{expected}")
IO.puts("  diff:                               #{diff}")
IO.puts("  parity: #{if diff < 1.0e-10, do: "OK (matches all SDKs)", else: "MISMATCH!"}")

IO.puts("")

# -------------------------------------------------------------------
# 7. Stop the client
# -------------------------------------------------------------------
IO.puts("Stopping client...")
ExperimentationPlatform.stop(client)
IO.puts("Done.")
