defmodule ExperimentationPlatform.Client do
  @moduledoc """
  GenServer client for the Experimentation Platform SDK.

  Manages configuration, an in-process ETS cache, and HTTP communication
  with the Experimentation Platform API.

  ## Usage

      # Start a client
      {:ok, client} = ExperimentationPlatform.Client.start_link(
        base_url: "https://api.example.com",
        api_key: "your-api-key"
      )

      # Evaluate a feature flag
      {:ok, result} = ExperimentationPlatform.Client.evaluate_flag(client, "my-flag", "user-123")

      # Get experiment assignment
      {:ok, assignment} = ExperimentationPlatform.Client.get_assignment(client, "experiment-key", "user-123")

      # Track an event (fire-and-forget)
      :ok = ExperimentationPlatform.Client.track(client, "button_clicked", "user-123", %{page: "home"})

      # Stop the client
      ExperimentationPlatform.Client.stop(client)
  """

  use GenServer, restart: :temporary

  alias ExperimentationPlatform.{Config, Evaluator, Cache}

  # --- Client API ---

  @doc "Start a new Client GenServer with the given config options."
  @spec start_link(keyword() | map() | Config.t()) :: GenServer.on_start()
  def start_link(%Config{} = config) do
    GenServer.start_link(__MODULE__, config)
  end

  def start_link(config_opts) do
    config = Config.new(config_opts)
    GenServer.start_link(__MODULE__, config)
  end

  @doc """
  Evaluate a feature flag for a user.

  Returns `{:ok, result}` where result is either:
  - A variant map (e.g., `%{"name" => "treatment"}`) if the user is in the rollout
  - `nil` if the user is not in the rollout or the flag doesn't exist

  Results are cached based on the config `cache_ttl`.

  ## Options
  - `:attributes` - Map of user attributes for targeting rules (default: `%{}`)
  - `:skip_cache` - If true, bypass cache and fetch fresh data (default: false)
  """
  @spec evaluate_flag(pid(), String.t(), String.t(), keyword()) ::
          {:ok, map() | nil} | {:error, term()}
  def evaluate_flag(pid, flag_key, user_id, opts \\ []) do
    GenServer.call(pid, {:evaluate_flag, flag_key, user_id, opts})
  end

  @doc """
  Get experiment assignment for a user.

  Returns `{:ok, assignment}` where assignment is either:
  - A variant/treatment map if the user is assigned to the experiment
  - `nil` if the user is not assigned or the experiment doesn't exist

  ## Options
  - `:attributes` - Map of user attributes for targeting rules (default: `%{}`)
  - `:skip_cache` - If true, bypass cache and fetch fresh data (default: false)
  """
  @spec get_assignment(pid(), String.t(), String.t(), keyword()) ::
          {:ok, map() | nil} | {:error, term()}
  def get_assignment(pid, experiment_key, user_id, opts \\ []) do
    GenServer.call(pid, {:get_assignment, experiment_key, user_id, opts})
  end

  @doc """
  Track an event (fire-and-forget).

  Sends the event to the API asynchronously. Always returns `:ok` immediately.
  Errors are logged but do not propagate to the caller.
  """
  @spec track(pid(), String.t(), String.t(), map()) :: :ok
  def track(pid, event_name, user_id, properties \\ %{}) do
    GenServer.cast(pid, {:track, event_name, user_id, properties})
  end

  @doc "Stop the Client GenServer."
  @spec stop(pid()) :: :ok
  def stop(pid) do
    GenServer.stop(pid)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(%Config{} = config) do
    # Each client has its own ETS-backed cache (not the global named one)
    {:ok, cache_pid} = Cache.start_link_unnamed(config)

    http_client = config.http_client || ExperimentationPlatform.HttpClient

    state = %{
      config: config,
      cache_pid: cache_pid,
      http_client: http_client
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:evaluate_flag, flag_key, user_id, opts}, _from, state) do
    attributes = Keyword.get(opts, :attributes, %{})
    skip_cache = Keyword.get(opts, :skip_cache, false)
    cache_key = "flag:#{flag_key}"

    result =
      if not skip_cache do
        case Cache.get(state.cache_pid, cache_key) do
          nil -> fetch_and_cache_flag(state, flag_key, cache_key)
          flag -> {:ok, flag}
        end
      else
        fetch_and_cache_flag(state, flag_key, cache_key)
      end

    case result do
      {:ok, flag} ->
        variant = Evaluator.evaluate(flag, user_id, attributes)
        {:reply, {:ok, variant}, state}

      {:error, reason} ->
        {:reply, {:error, reason}, state}
    end
  end

  def handle_call({:get_assignment, experiment_key, user_id, opts}, _from, state) do
    attributes = Keyword.get(opts, :attributes, %{})
    skip_cache = Keyword.get(opts, :skip_cache, false)
    cache_key = "experiment:#{experiment_key}"

    result =
      if not skip_cache do
        case Cache.get(state.cache_pid, cache_key) do
          nil -> fetch_and_cache_experiment(state, experiment_key, cache_key)
          experiment -> {:ok, experiment}
        end
      else
        fetch_and_cache_experiment(state, experiment_key, cache_key)
      end

    case result do
      {:ok, experiment} ->
        variant = Evaluator.evaluate_experiment(experiment, user_id, attributes)
        {:reply, {:ok, variant}, state}

      {:error, reason} ->
        {:reply, {:error, reason}, state}
    end
  end

  @impl true
  def handle_cast({:track, event_name, user_id, properties}, state) do
    # Fire-and-forget: send asynchronously in a spawned task
    config = state.config
    http_client = state.http_client

    spawn(fn ->
      payload = %{
        event: event_name,
        user_id: user_id,
        properties: properties,
        timestamp: DateTime.utc_now() |> DateTime.to_iso8601()
      }

      case http_client.post(config, "/api/v1/events", payload) do
        {:ok, _} ->
          :ok

        {:error, reason} ->
          require Logger
          Logger.warning("ExperimentationPlatform: Failed to track event #{event_name}: #{inspect(reason)}")
      end
    end)

    {:noreply, state}
  end

  # --- Private Helpers ---

  defp fetch_and_cache_flag(state, flag_key, cache_key) do
    case state.http_client.get(state.config, "/api/v1/feature-flags/#{flag_key}") do
      {:ok, flag} ->
        Cache.put(state.cache_pid, cache_key, flag)
        {:ok, flag}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp fetch_and_cache_experiment(state, experiment_key, cache_key) do
    case state.http_client.get(state.config, "/api/v1/experiments/#{experiment_key}") do
      {:ok, experiment} ->
        Cache.put(state.cache_pid, cache_key, experiment)
        {:ok, experiment}

      {:error, reason} ->
        {:error, reason}
    end
  end
end
