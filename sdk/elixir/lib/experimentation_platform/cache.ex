defmodule ExperimentationPlatform.Cache do
  @moduledoc """
  ETS-backed GenServer cache for feature flags and experiment data.

  Provides a thread-safe, TTL-aware in-memory cache with configurable
  maximum size. When the cache reaches `max_cache_size`, the oldest
  entries are evicted to make room for new ones.

  ## Storage Format

  Each ETS entry is stored as: `{key, value, expires_at_ms}`
  where `expires_at_ms` is a monotonic millisecond timestamp.

  ## Usage

      # Start cache (usually done by ExperimentationPlatform.Client)
      {:ok, _pid} = Cache.start_link(config)

      # Store a value (uses config.cache_ttl as default TTL)
      Cache.put("flag:my-flag", flag_data)

      # Store with a custom TTL (in seconds)
      Cache.put("flag:my-flag", flag_data, 60)

      # Retrieve a value
      case Cache.get("flag:my-flag") do
        nil -> # cache miss
        value -> # cache hit
      end
  """

  use GenServer

  alias ExperimentationPlatform.Config

  @table_name :experimentation_platform_cache

  # --- Client API ---

  @doc "Start the Cache GenServer. Usually called by ExperimentationPlatform.Client."
  @spec start_link(Config.t()) :: GenServer.on_start()
  def start_link(config) do
    GenServer.start_link(__MODULE__, config, name: __MODULE__)
  end

  @doc "Start a Cache GenServer without registering a global name. Useful for tests."
  @spec start_link_unnamed(Config.t()) :: GenServer.on_start()
  def start_link_unnamed(config) do
    GenServer.start_link(__MODULE__, config)
  end

  @doc "Retrieve a cached value. Returns nil if missing or expired."
  @spec get(pid() | atom(), any()) :: any()
  def get(server \\ __MODULE__, key) do
    GenServer.call(server, {:get, key})
  end

  @doc "Store a value with an optional TTL override in seconds. Uses config.cache_ttl if nil."
  @spec put(pid() | atom(), any(), any(), non_neg_integer() | nil) :: :ok
  def put(server \\ __MODULE__, key, value, ttl_seconds \\ nil) do
    GenServer.cast(server, {:put, key, value, ttl_seconds})
  end

  @doc "Delete a specific cache entry."
  @spec delete(pid() | atom(), any()) :: :ok
  def delete(server \\ __MODULE__, key) do
    GenServer.cast(server, {:delete, key})
  end

  @doc "Clear all cache entries."
  @spec clear(pid() | atom()) :: :ok
  def clear(server \\ __MODULE__) do
    GenServer.cast(server, :clear)
  end

  @doc "Return the number of entries currently in the cache (including potentially expired ones)."
  @spec size(pid() | atom()) :: non_neg_integer()
  def size(server \\ __MODULE__) do
    GenServer.call(server, :size)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(%Config{} = config) do
    table = :ets.new(@table_name, [:set, :private])
    state = %{table: table, config: config}
    {:ok, state}
  end

  @impl true
  def handle_call({:get, key}, _from, %{table: table, config: config} = state) do
    result = lookup(table, key, config.cache_ttl)
    {:reply, result, state}
  end

  def handle_call(:size, _from, %{table: table} = state) do
    n = :ets.info(table, :size)
    {:reply, n, state}
  end

  @impl true
  def handle_cast({:put, key, value, ttl_override}, %{table: table, config: config} = state) do
    ttl = ttl_override || config.cache_ttl
    expires_at = mono_ms() + ttl * 1_000
    evict_if_needed(table, config.max_cache_size)
    :ets.insert(table, {key, value, expires_at})
    {:noreply, state}
  end

  def handle_cast({:delete, key}, %{table: table} = state) do
    :ets.delete(table, key)
    {:noreply, state}
  end

  def handle_cast(:clear, %{table: table} = state) do
    :ets.delete_all_objects(table)
    {:noreply, state}
  end

  # --- Private Helpers ---

  defp lookup(table, key, _default_ttl) do
    case :ets.lookup(table, key) do
      [{^key, value, expires_at}] ->
        if mono_ms() < expires_at do
          value
        else
          :ets.delete(table, key)
          nil
        end

      [] ->
        nil
    end
  end

  defp evict_if_needed(table, max_size) do
    current_size = :ets.info(table, :size)

    if current_size >= max_size do
      # Evict the entry with the smallest (oldest) expires_at
      # Build a list of {expires_at, key} and delete the minimum
      oldest =
        :ets.foldl(
          fn {key, _value, expires_at}, acc ->
            case acc do
              nil -> {expires_at, key}
              {min_exp, _} when expires_at < min_exp -> {expires_at, key}
              _ -> acc
            end
          end,
          nil,
          table
        )

      case oldest do
        {_exp, key} -> :ets.delete(table, key)
        nil -> :ok
      end
    end
  end

  defp mono_ms do
    System.monotonic_time(:millisecond)
  end
end
