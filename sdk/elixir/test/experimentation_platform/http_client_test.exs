defmodule ExperimentationPlatform.HttpClientTest do
  @moduledoc """
  Unit tests for the HTTP client behaviour and mock implementation.

  Rather than testing the real :httpc calls (which require a live server),
  these tests use a mock HTTP client module that implements the HttpBehaviour.
  This validates the client contract and how errors are propagated.
  """

  use ExUnit.Case, async: true

  alias ExperimentationPlatform.{Config, HttpBehaviour}

  # --- Mock HTTP client modules ---

  defmodule MockHttpSuccess do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, path) do
      cond do
        String.contains?(path, "feature-flags") ->
          {:ok, %{"key" => "test-flag", "enabled" => true, "rollout_percentage" => 100, "variants" => []}}

        String.contains?(path, "experiments") ->
          {:ok, %{"key" => "test-exp", "status" => "running", "traffic_allocation" => 0.5, "variants" => []}}

        true ->
          {:ok, %{"result" => "ok", "path" => path}}
      end
    end

    @impl true
    def post(_config, _path, body) do
      {:ok, Map.merge(body, %{"status" => "accepted"})}
    end
  end

  defmodule MockHttpAuth401 do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, _path), do: {:error, {:auth_error, 401}}

    @impl true
    def post(_config, _path, _body), do: {:error, {:auth_error, 401}}
  end

  defmodule MockHttp404 do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, _path), do: {:error, {:api_error, 404, "Not found"}}

    @impl true
    def post(_config, _path, _body), do: {:error, {:api_error, 404, "Not found"}}
  end

  defmodule MockHttpNetworkError do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, _path), do: {:error, {:network_error, :econnrefused}}

    @impl true
    def post(_config, _path, _body), do: {:error, {:network_error, :timeout}}
  end

  defmodule MockHttpServerError do
    @behaviour HttpBehaviour

    @impl true
    def get(_config, _path), do: {:error, {:api_error, 500, "Internal Server Error"}}

    @impl true
    def post(_config, _path, _body), do: {:error, {:api_error, 503, "Service Unavailable"}}
  end

  defp base_config do
    Config.new(base_url: "http://localhost:8000", api_key: "test-key")
  end

  describe "MockHttpSuccess (GET)" do
    test "successful GET returns {:ok, map}" do
      result = MockHttpSuccess.get(base_config(), "/api/v1/feature-flags/my-flag")
      assert {:ok, data} = result
      assert is_map(data)
      assert data["key"] == "test-flag"
    end

    test "successful GET for experiments returns experiment map" do
      result = MockHttpSuccess.get(base_config(), "/api/v1/experiments/my-exp")
      assert {:ok, data} = result
      assert data["key"] == "test-exp"
      assert data["status"] == "running"
    end

    test "GET passes config to the client" do
      config = Config.new(base_url: "http://api.example.com", api_key: "real-key", timeout: 5_000)
      result = MockHttpSuccess.get(config, "/api/v1/any")
      assert {:ok, _} = result
    end
  end

  describe "MockHttpSuccess (POST)" do
    test "successful POST returns {:ok, map} with response" do
      body = %{event: "click", user_id: "user-1"}
      result = MockHttpSuccess.post(base_config(), "/api/v1/events", body)
      assert {:ok, data} = result
      assert data["status"] == "accepted"
    end

    test "successful POST echoes back sent body merged with response" do
      body = %{user_id: "u1", event: "test"}
      {:ok, data} = MockHttpSuccess.post(base_config(), "/api/v1/events", body)
      assert data["status"] == "accepted"
    end
  end

  describe "MockHttpAuth401 (authentication errors)" do
    test "GET returns {:error, {:auth_error, 401}} on 401" do
      result = MockHttpAuth401.get(base_config(), "/api/v1/feature-flags/f")
      assert {:error, {:auth_error, 401}} = result
    end

    test "POST returns {:error, {:auth_error, 401}} on 401" do
      result = MockHttpAuth401.post(base_config(), "/api/v1/events", %{})
      assert {:error, {:auth_error, 401}} = result
    end
  end

  describe "MockHttp404 (not found errors)" do
    test "GET returns {:error, {:api_error, 404, _}} on 404" do
      result = MockHttp404.get(base_config(), "/api/v1/feature-flags/nonexistent")
      assert {:error, {:api_error, 404, _body}} = result
    end

    test "POST returns {:error, {:api_error, 404, _}} on 404" do
      result = MockHttp404.post(base_config(), "/api/v1/something", %{})
      assert {:error, {:api_error, 404, _body}} = result
    end
  end

  describe "MockHttpNetworkError (network failures)" do
    test "GET returns {:error, {:network_error, _}} on connection refused" do
      result = MockHttpNetworkError.get(base_config(), "/api/v1/feature-flags/f")
      assert {:error, {:network_error, :econnrefused}} = result
    end

    test "POST returns {:error, {:network_error, _}} on timeout" do
      result = MockHttpNetworkError.post(base_config(), "/api/v1/events", %{})
      assert {:error, {:network_error, :timeout}} = result
    end
  end

  describe "MockHttpServerError (5xx errors)" do
    test "GET returns {:error, {:api_error, 500, _}} on server error" do
      result = MockHttpServerError.get(base_config(), "/api/v1/feature-flags/f")
      assert {:error, {:api_error, 500, _}} = result
    end

    test "POST returns {:error, {:api_error, 503, _}} on service unavailable" do
      result = MockHttpServerError.post(base_config(), "/api/v1/events", %{})
      assert {:error, {:api_error, 503, _}} = result
    end
  end

  describe "HttpBehaviour contract" do
    test "MockHttpSuccess implements HttpBehaviour" do
      behaviours = MockHttpSuccess.__info__(:attributes)[:behaviour] || []
      assert HttpBehaviour in behaviours
    end

    test "MockHttpAuth401 implements HttpBehaviour" do
      behaviours = MockHttpAuth401.__info__(:attributes)[:behaviour] || []
      assert HttpBehaviour in behaviours
    end

    test "MockHttp404 implements HttpBehaviour" do
      behaviours = MockHttp404.__info__(:attributes)[:behaviour] || []
      assert HttpBehaviour in behaviours
    end
  end
end
