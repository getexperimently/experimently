defmodule ExperimentationPlatform.ClientTest do
  @moduledoc """
  Unit tests for the ExperimentationPlatform.Client GenServer.

  Uses mock HTTP client modules injected via config to avoid
  real network calls.
  """

  use ExUnit.Case, async: true

  alias ExperimentationPlatform.{Client, Config, HttpBehaviour}

  # --- Mock HTTP modules for client tests ---

  defmodule MockHttp do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, path) do
      cond do
        String.contains?(path, "feature-flags/dark-mode") ->
          {:ok, %{
            "key" => "dark-mode",
            "enabled" => true,
            "rollout_percentage" => 100,
            "variants" => [%{"name" => "enabled", "value" => "dark"}]
          }}

        String.contains?(path, "feature-flags/disabled-flag") ->
          {:ok, %{
            "key" => "disabled-flag",
            "enabled" => false,
            "rollout_percentage" => 100,
            "variants" => [%{"name" => "variant"}]
          }}

        String.contains?(path, "feature-flags/low-rollout") ->
          {:ok, %{
            "key" => "low-rollout",
            "enabled" => true,
            "rollout_percentage" => 1,
            "variants" => [%{"name" => "v"}]
          }}

        String.contains?(path, "experiments/checkout-exp") ->
          {:ok, %{
            "key" => "checkout-exp",
            "status" => "running",
            "traffic_allocation" => 1.0,
            "variants" => [%{"name" => "control"}, %{"name" => "treatment"}]
          }}

        String.contains?(path, "experiments/inactive-exp") ->
          {:ok, %{
            "key" => "inactive-exp",
            "status" => "paused",
            "traffic_allocation" => 1.0,
            "variants" => [%{"name" => "v"}]
          }}

        true ->
          {:error, {:api_error, 404, "Not found"}}
      end
    end

    @impl true
    def post(_config, _path, _body) do
      {:ok, %{"status" => "accepted"}}
    end
  end

  defmodule MockHttpError do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, _path), do: {:error, {:network_error, :econnrefused}}

    @impl true
    def post(_config, _path, _body), do: {:error, {:network_error, :econnrefused}}
  end

  # Track how many times get is called
  defmodule MockHttpSpy do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, path) do
      # Notify the test process via message
      send(:test_spy_receiver, {:get_called, path})

      {:ok, %{
        "key" => "spy-flag",
        "enabled" => true,
        "rollout_percentage" => 100,
        "variants" => [%{"name" => "v"}]
      }}
    end

    @impl true
    def post(_config, _path, _body) do
      send(:test_spy_receiver, :post_called)
      {:ok, %{"status" => "accepted"}}
    end
  end

  defp start_client(opts \\ []) do
    base_opts = [base_url: "http://localhost:8000", api_key: "test-key", http_client: MockHttp]
    config = Config.new(Keyword.merge(base_opts, opts))
    {:ok, pid} = Client.start_link(config)
    on_exit(fn ->
      if Process.alive?(pid), do: Client.stop(pid)
    end)
    pid
  end

  describe "evaluate_flag/4" do
    test "returns {:ok, variant} when user is in rollout" do
      pid = start_client()
      result = Client.evaluate_flag(pid, "dark-mode", "user-123")
      assert {:ok, variant} = result
      assert variant != nil
      assert variant["name"] == "enabled"
    end

    test "returns {:ok, nil} when flag is disabled" do
      pid = start_client()
      result = Client.evaluate_flag(pid, "disabled-flag", "user-123")
      assert {:ok, nil} = result
    end

    test "returns {:ok, nil} when user not in rollout" do
      pid = start_client()
      # low-rollout is 1%, most users won't be in it
      result = Client.evaluate_flag(pid, "low-rollout", "user-definitely-not-in-1pct")
      assert {:ok, nil} = result
    end

    test "returns {:error, reason} on HTTP error" do
      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttpError)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      result = Client.evaluate_flag(pid, "any-flag", "user-123")
      assert {:error, _reason} = result
    end

    test "caches flag — HTTP is only called once for two calls to same flag" do
      # Register this test process as spy receiver
      Process.register(self(), :test_spy_receiver)
      on_exit(fn ->
        # Unregister if still registered
        if Process.whereis(:test_spy_receiver) == self(), do: Process.unregister(:test_spy_receiver)
      end)

      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttpSpy)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      # First call — should hit HTTP
      {:ok, _} = Client.evaluate_flag(pid, "spy-flag", "user-1")
      # Second call — should use cache
      {:ok, _} = Client.evaluate_flag(pid, "spy-flag", "user-2")

      # Drain mailbox to count GET calls
      get_calls = collect_messages(:get_called, 100)
      assert length(get_calls) == 1, "Expected 1 HTTP call (cached), got #{length(get_calls)}"
    end

    test "skip_cache option fetches fresh data" do
      Process.register(self(), :test_spy_receiver)
      on_exit(fn ->
        if Process.whereis(:test_spy_receiver) == self(), do: Process.unregister(:test_spy_receiver)
      end)

      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttpSpy)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      {:ok, _} = Client.evaluate_flag(pid, "spy-flag", "user-1")
      {:ok, _} = Client.evaluate_flag(pid, "spy-flag", "user-1", skip_cache: true)

      get_calls = collect_messages(:get_called, 100)
      assert length(get_calls) == 2
    end
  end

  describe "get_assignment/4" do
    test "returns {:ok, variant} for a running experiment" do
      pid = start_client()
      result = Client.get_assignment(pid, "checkout-exp", "user-123")
      assert {:ok, variant} = result
      assert variant != nil
      assert variant["name"] in ["control", "treatment"]
    end

    test "returns {:ok, nil} for a paused experiment" do
      pid = start_client()
      result = Client.get_assignment(pid, "inactive-exp", "user-123")
      assert {:ok, nil} = result
    end

    test "returns {:error, reason} on HTTP error" do
      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttpError)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      result = Client.get_assignment(pid, "any-exp", "user-123")
      assert {:error, _} = result
    end

    test "assignment is deterministic for same user" do
      pid = start_client()
      {:ok, v1} = Client.get_assignment(pid, "checkout-exp", "stable-user")
      {:ok, v2} = Client.get_assignment(pid, "checkout-exp", "stable-user")
      assert v1 == v2
    end
  end

  describe "track/4" do
    test "returns :ok immediately (fire-and-forget)" do
      pid = start_client()
      result = Client.track(pid, "button_clicked", "user-123")
      assert result == :ok
    end

    test "returns :ok with properties" do
      pid = start_client()
      result = Client.track(pid, "purchase", "user-123", %{amount: 99.99, currency: "USD"})
      assert result == :ok
    end

    test "returns :ok even when HTTP client would error" do
      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttpError)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      # Should not crash or raise
      result = Client.track(pid, "event", "user-1", %{})
      assert result == :ok
    end

    test "client remains functional after track error" do
      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttp)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)

      Client.track(pid, "event1", "user-1")
      Client.track(pid, "event2", "user-2")
      :timer.sleep(50)

      # Client should still be alive and functional
      assert Process.alive?(pid)
      {:ok, _} = Client.evaluate_flag(pid, "dark-mode", "user-123")
    end
  end

  describe "stop/1" do
    test "stop terminates the client process" do
      pid = start_client()
      assert Process.alive?(pid)
      Client.stop(pid)
      :timer.sleep(10)
      refute Process.alive?(pid)
    end
  end

  describe "start_link/1" do
    test "accepts keyword list config" do
      {:ok, pid} = Client.start_link(base_url: "http://localhost", api_key: "k", http_client: MockHttp)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)
      assert Process.alive?(pid)
    end

    test "accepts Config struct" do
      config = Config.new(base_url: "http://localhost", api_key: "k", http_client: MockHttp)
      {:ok, pid} = Client.start_link(config)
      on_exit(fn -> if Process.alive?(pid), do: Client.stop(pid) end)
      assert Process.alive?(pid)
    end

    test "raises ArgumentError for missing base_url" do
      assert_raise ArgumentError, ~r/base_url required/, fn ->
        Client.start_link(api_key: "k")
      end
    end

    test "raises ArgumentError for missing api_key" do
      assert_raise ArgumentError, ~r/api_key required/, fn ->
        Client.start_link(base_url: "http://localhost")
      end
    end
  end

  # --- Helpers ---

  defp collect_messages(tag, timeout_ms) do
    receive do
      {^tag, _} = msg ->
        [msg | collect_messages(tag, 10)]
      ^tag ->
        [tag | collect_messages(tag, 10)]
    after
      timeout_ms -> []
    end
  end
end
