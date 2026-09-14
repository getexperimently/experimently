defmodule ExperimentlyTest do
  @moduledoc """
  Tests for the top-level Experimently facade module.

  These tests verify the public API surface delegates correctly to the
  Client and returns the documented shapes.
  """

  use ExUnit.Case, async: true

  alias Experimently.TestSupport.ProcessHelpers

  alias Experimently.{Assignment, BatchResult, FlagEvaluation, HttpBehaviour}

  @spy :experimently_facade_test_spy

  defmodule MockHttp do
    @moduledoc false
    @behaviour HttpBehaviour

    @spy :experimently_facade_test_spy

    @impl true
    def get(_config, "/api/v1/feature-flags/evaluate/my-flag?user_id=" <> _user_id) do
      {:ok, %{"key" => "my-flag", "enabled" => true, "config" => %{"variant" => "new"}}}
    end

    def get(_config, _path), do: {:error, {:api_error, 404, "Not found"}}

    @impl true
    def post(_config, "/api/v1/tracking/assign", %{experiment_key: "my-exp", user_id: user_id}) do
      {:ok,
       %{
         "experiment_key" => "my-exp",
         "user_id" => user_id,
         "variant_id" => "v-1",
         "variant_name" => "treatment",
         "is_control" => false,
         "configuration" => nil
       }}
    end

    def post(_config, "/api/v1/tracking/assign", _body) do
      {:error, {:api_error, 404, "Not found"}}
    end

    def post(_config, path, body) do
      if pid = Process.whereis(@spy), do: send(pid, {:post, path, body})
      {:ok, %{"success_count" => 1, "failure_count" => 0, "errors" => nil}}
    end
  end

  setup do
    ProcessHelpers.await_release(@spy)
    Process.register(self(), @spy)

    on_exit(fn ->
      if Process.whereis(@spy), do: Process.unregister(@spy)
    end)

    :ok
  end

  defp start_ep do
    {:ok, client} =
      Experimently.start(
        base_url: "http://localhost:8000",
        api_key: "test-key",
        http_client: MockHttp
      )

    on_exit(fn -> ProcessHelpers.stop_if_alive(client, &Experimently.stop/1) end)
    client
  end

  describe "start/1" do
    test "returns {:ok, pid} on success" do
      assert {:ok, pid} =
               Experimently.start(
                 base_url: "http://localhost",
                 api_key: "key",
                 http_client: MockHttp
               )

      assert is_pid(pid)
      Experimently.stop(pid)
    end

    test "raises ArgumentError when base_url is missing" do
      assert_raise ArgumentError, fn -> Experimently.start(api_key: "key") end
    end

    test "raises ArgumentError when api_key is missing" do
      assert_raise ArgumentError, fn ->
        Experimently.start(base_url: "http://localhost")
      end
    end
  end

  describe "evaluate_flag/4" do
    test "returns {:ok, %FlagEvaluation{}}" do
      client = start_ep()

      assert {:ok, %FlagEvaluation{key: "my-flag", enabled: true, config: %{"variant" => "new"}}} =
               Experimently.evaluate_flag(client, "my-flag", "user-1")
    end

    test "returns {:error, reason} for an unknown flag" do
      client = start_ep()

      assert {:error, {:api_error, 404, _}} =
               Experimently.evaluate_flag(client, "unknown-flag", "user-1")
    end

    test "accepts optional opts" do
      client = start_ep()

      assert {:ok, %FlagEvaluation{enabled: true}} =
               Experimently.evaluate_flag(client, "my-flag", "user-1",
                 attributes: %{country: "US"},
                 skip_cache: true
               )
    end
  end

  describe "feature_enabled?/3" do
    test "is a boolean view of evaluate_flag" do
      client = start_ep()
      assert Experimently.feature_enabled?(client, "my-flag", "user-1")
      refute Experimently.feature_enabled?(client, "unknown-flag", "user-1")
    end
  end

  describe "get_assignment/4" do
    test "returns {:ok, %Assignment{}}" do
      client = start_ep()

      assert {:ok,
              %Assignment{
                experiment_key: "my-exp",
                variant_id: "v-1",
                variant_name: "treatment",
                is_control: false,
                configuration: nil
              }} = Experimently.get_assignment(client, "my-exp", "user-1")
    end

    test "accepts attributes as the fourth argument" do
      client = start_ep()

      assert {:ok, %Assignment{variant_name: "treatment"}} =
               Experimently.get_assignment(client, "my-exp", "user-1", %{plan: "pro"})
    end

    test "returns {:error, reason} for an unknown experiment" do
      client = start_ep()

      assert {:error, {:api_error, 404, _}} =
               Experimently.get_assignment(client, "unknown-exp", "user-1")
    end
  end

  describe "track/5" do
    test "returns :ok immediately" do
      client = start_ep()
      assert :ok = Experimently.track(client, "page_view", "user-1")
    end

    test "accepts properties and options" do
      client = start_ep()

      assert :ok =
               Experimently.track(client, "click", "user-1", %{button: "cta"},
                 experiment_key: "my-exp",
                 value: 1
               )

      assert_receive {:post, "/api/v1/tracking/track", %{experiment_key: "my-exp", value: 1}}, 500
    end
  end

  describe "track_batch/2" do
    test "returns {:ok, %BatchResult{}}" do
      client = start_ep()

      assert {:ok, %BatchResult{success_count: 1, failure_count: 0}} =
               Experimently.track_batch(client, [
                 %{event_name: "purchase", user_id: "user-1", experiment_key: "my-exp"}
               ])

      assert_receive {:post, "/api/v1/tracking/batch", %{events: [_]}}
    end
  end

  describe "cache helpers" do
    test "assignments/2, evaluated_flags/2 and clear_cache/1" do
      client = start_ep()

      {:ok, assignment} = Experimently.get_assignment(client, "my-exp", "user-1")
      {:ok, _} = Experimently.evaluate_flag(client, "my-flag", "user-1")

      assert Experimently.assignments(client, "user-1") == [assignment]
      assert Experimently.evaluated_flags(client, "user-1") == ["my-flag"]

      assert :ok = Experimently.clear_cache(client)
      assert Experimently.assignments(client, "user-1") == []
      assert Experimently.evaluated_flags(client, "user-1") == []
    end
  end

  describe "stop/1" do
    test "terminates the client process" do
      {:ok, client} =
        Experimently.start(
          base_url: "http://localhost",
          api_key: "key",
          http_client: MockHttp
        )

      assert Process.alive?(client)
      assert :ok = Experimently.stop(client)
      refute Process.alive?(client)
    end
  end
end
