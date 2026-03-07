defmodule ExperimentationPlatform do
  @moduledoc """
  Elixir SDK for the Experimentation Platform.

  Provides A/B testing and feature flag evaluation with:
  - Cross-SDK consistent hashing (MD5-based, compatible with JS/Python/Java/Go SDKs)
  - ETS-backed in-process caching with configurable TTL
  - OTP `:httpc`-based HTTP (zero external runtime deps beyond Jason)
  - GenServer-based client lifecycle management

  ## Quick Start

      # Start a client
      {:ok, client} = ExperimentationPlatform.start(
        base_url: "https://api.example.com",
        api_key: "your-api-key"
      )

      # Evaluate a feature flag
      case ExperimentationPlatform.evaluate_flag(client, "dark-mode", "user-123") do
        {:ok, nil} ->
          # User not in rollout — show default
          render_default()

        {:ok, %{"name" => "enabled"}} ->
          render_dark_mode()

        {:error, reason} ->
          Logger.warning("Flag evaluation failed: \#{inspect(reason)}")
          render_default()
      end

      # Get experiment assignment
      {:ok, variant} = ExperimentationPlatform.get_assignment(client, "checkout-experiment", "user-123")

      # Track an event
      ExperimentationPlatform.track(client, "button_clicked", "user-123", %{page: "checkout"})

  ## Configuration Options

  | Option           | Type    | Required | Default | Description                              |
  |------------------|---------|----------|---------|------------------------------------------|
  | `:base_url`      | string  | yes      | —       | API base URL                             |
  | `:api_key`       | string  | yes      | —       | API key for authentication               |
  | `:cache_ttl`     | integer | no       | 300     | Cache TTL in seconds                     |
  | `:timeout`       | integer | no       | 10_000  | HTTP timeout in milliseconds             |
  | `:max_cache_size`| integer | no       | 1_000   | Maximum number of cached entries         |

  ## Architecture

  Each call to `start/1` creates:
  1. A `Client` GenServer managing config and HTTP
  2. A `Cache` GenServer (child of Client's init) backed by ETS

  The client PID is passed to all subsequent API calls. Multiple independent
  clients can be created (e.g., for different environments or configurations).

  ## Hash Compatibility

  The SDK uses MD5-based consistent hashing compatible with all platform SDKs:

      ExperimentationPlatform.Evaluator.hash_user("user-123", "my-flag")
      # => 0.6927449859213084

  This value is identical across JavaScript, Python, Java, Go, Ruby, and Go SDKs.
  """

  alias ExperimentationPlatform.Client

  @doc """
  Start a new ExperimentationPlatform client.

  ## Parameters
  - `config_opts` - Keyword list or map of configuration options

  ## Returns
  - `{:ok, pid}` on success
  - `{:error, reason}` on failure

  ## Examples

      {:ok, client} = ExperimentationPlatform.start(
        base_url: "https://api.example.com",
        api_key: "sk-prod-abc123"
      )

      {:ok, client} = ExperimentationPlatform.start(
        base_url: "https://api.example.com",
        api_key: "sk-prod-abc123",
        cache_ttl: 60,
        timeout: 5_000
      )
  """
  @spec start(keyword() | map() | ExperimentationPlatform.Config.t()) :: {:ok, pid()} | {:error, term()}
  def start(config_opts) do
    Client.start_link(config_opts)
  end

  @doc """
  Evaluate a feature flag for a user.

  ## Parameters
  - `client` - The client PID returned by `start/1`
  - `flag_key` - The unique key of the feature flag
  - `user_id` - The user identifier
  - `opts` - Options (`:attributes`, `:skip_cache`)

  ## Returns
  - `{:ok, variant_map}` if user is in rollout
  - `{:ok, nil}` if user is not in rollout or flag not found
  - `{:error, reason}` on error
  """
  @spec evaluate_flag(pid(), String.t(), String.t(), keyword()) ::
          {:ok, map() | nil} | {:error, term()}
  def evaluate_flag(client, flag_key, user_id, opts \\ []) do
    Client.evaluate_flag(client, flag_key, user_id, opts)
  end

  @doc """
  Get experiment assignment for a user.

  ## Parameters
  - `client` - The client PID returned by `start/1`
  - `experiment_key` - The unique key of the experiment
  - `user_id` - The user identifier
  - `opts` - Options (`:attributes`, `:skip_cache`)

  ## Returns
  - `{:ok, variant_map}` if user is assigned to a variant
  - `{:ok, nil}` if user is not assigned
  - `{:error, reason}` on error
  """
  @spec get_assignment(pid(), String.t(), String.t(), keyword()) ::
          {:ok, map() | nil} | {:error, term()}
  def get_assignment(client, experiment_key, user_id, opts \\ []) do
    Client.get_assignment(client, experiment_key, user_id, opts)
  end

  @doc """
  Track an event for analytics (fire-and-forget).

  The event is sent asynchronously. This function always returns `:ok` immediately.
  Network or API errors are logged as warnings but do not raise.

  ## Parameters
  - `client` - The client PID returned by `start/1`
  - `event_name` - Name of the event (e.g., "purchase_completed")
  - `user_id` - The user identifier
  - `properties` - Optional map of event properties
  """
  @spec track(pid(), String.t(), String.t(), map()) :: :ok
  def track(client, event_name, user_id, properties \\ %{}) do
    Client.track(client, event_name, user_id, properties)
  end

  @doc "Stop the client and free associated resources."
  @spec stop(pid()) :: :ok
  def stop(client) do
    Client.stop(client)
  end
end
