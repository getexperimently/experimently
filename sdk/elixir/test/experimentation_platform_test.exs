defmodule ExperimentationPlatformTest do
  @moduledoc """
  Integration-style tests for the top-level ExperimentationPlatform facade module.

  These tests verify the public API surface delegates correctly to the Client.
  """

  use ExUnit.Case, async: true

  alias ExperimentationPlatform.{Config, HttpBehaviour}

  defmodule MockHttp do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, path) do
      cond do
        String.contains?(path, "feature-flags/my-flag") ->
          {:ok, %{
            "key" => "my-flag",
            "enabled" => true,
            "rollout_percentage" => 100,
            "variants" => [%{"name" => "treatment", "value" => "new"}]
          }}

        String.contains?(path, "experiments/my-exp") ->
          {:ok, %{
            "key" => "my-exp",
            "status" => "running",
            "traffic_allocation" => 1.0,
            "variants" => [%{"name" => "control"}, %{"name" => "treatment"}]
          }}

        true ->
          {:error, {:api_error, 404, "Not found"}}
      end
    end

    @impl true
    def post(_config, _path, _body), do: {:ok, %{"status" => "accepted"}}
  end

  defp start_ep do
    {:ok, client} = ExperimentationPlatform.start(
      base_url: "http://localhost:8000",
      api_key: "test-key",
      http_client: MockHttp
    )
    on_exit(fn -> if Process.alive?(client), do: ExperimentationPlatform.stop(client) end)
    client
  end

  describe "start/1" do
    test "returns {:ok, pid} on success" do
      result = ExperimentationPlatform.start(
        base_url: "http://localhost",
        api_key: "key",
        http_client: MockHttp
      )
      assert {:ok, pid} = result
      assert is_pid(pid)
      ExperimentationPlatform.stop(pid)
    end

    test "raises ArgumentError when base_url is missing" do
      assert_raise ArgumentError, fn ->
        ExperimentationPlatform.start(api_key: "key")
      end
    end

    test "raises ArgumentError when api_key is missing" do
      assert_raise ArgumentError, fn ->
        ExperimentationPlatform.start(base_url: "http://localhost")
      end
    end
  end

  describe "evaluate_flag/4" do
    test "delegates to Client and returns variant" do
      client = start_ep()
      {:ok, variant} = ExperimentationPlatform.evaluate_flag(client, "my-flag", "user-1")
      assert variant != nil
      assert variant["name"] == "treatment"
    end

    test "returns {:ok, nil} for unknown flag" do
      client = start_ep()
      {:ok, result} = ExperimentationPlatform.evaluate_flag(client, "unknown-flag", "user-1")
      assert result == nil
    end

    test "accepts optional opts" do
      client = start_ep()
      {:ok, result} = ExperimentationPlatform.evaluate_flag(client, "my-flag", "user-1", attributes: %{country: "US"})
      assert result != nil
    end
  end

  describe "get_assignment/4" do
    test "delegates to Client and returns assignment" do
      client = start_ep()
      {:ok, assignment} = ExperimentationPlatform.get_assignment(client, "my-exp", "user-1")
      assert assignment != nil
      assert assignment["name"] in ["control", "treatment"]
    end

    test "returns {:ok, nil} for unknown experiment" do
      client = start_ep()
      {:ok, result} = ExperimentationPlatform.get_assignment(client, "unknown-exp", "user-1")
      assert result == nil
    end
  end

  describe "track/4" do
    test "returns :ok immediately" do
      client = start_ep()
      result = ExperimentationPlatform.track(client, "page_view", "user-1")
      assert result == :ok
    end

    test "accepts optional properties" do
      client = start_ep()
      result = ExperimentationPlatform.track(client, "click", "user-1", %{button: "cta", page: "home"})
      assert result == :ok
    end
  end

  describe "stop/1" do
    test "terminates the client process" do
      {:ok, client} = ExperimentationPlatform.start(
        base_url: "http://localhost",
        api_key: "key",
        http_client: MockHttp
      )
      assert Process.alive?(client)
      ExperimentationPlatform.stop(client)
      :timer.sleep(10)
      refute Process.alive?(client)
    end
  end
end
