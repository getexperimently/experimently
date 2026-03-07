defmodule ExperimentationPlatform.HttpBehaviour do
  @moduledoc """
  Behaviour defining the HTTP client interface.

  Implement this to provide a custom or mock HTTP client.
  """

  @callback get(config :: ExperimentationPlatform.Config.t(), path :: String.t()) ::
              {:ok, map()} | {:error, term()}

  @callback post(
              config :: ExperimentationPlatform.Config.t(),
              path :: String.t(),
              body :: map()
            ) :: {:ok, map()} | {:error, term()}
end

defmodule ExperimentationPlatform.HttpClient do
  @moduledoc """
  HTTP client using OTP's built-in `:httpc` (from `:inets`) for zero external dependencies.

  Handles JSON encoding/decoding via Jason, authentication via API key header,
  and maps HTTP status codes to structured error tuples.

  ## Error Tuples

  - `{:error, {:auth_error, status_code}}` — 401 Unauthorized
  - `{:error, {:api_error, status_code, body}}` — Other 4xx/5xx errors
  - `{:error, {:network_error, reason}}` — Connection failures
  """

  @behaviour ExperimentationPlatform.HttpBehaviour

  alias ExperimentationPlatform.Config

  @doc """
  Perform a GET request to the given path.

  ## Returns
  - `{:ok, map()}` on success (2xx)
  - `{:error, {:auth_error, 401}}` on authentication failure
  - `{:error, {:api_error, status_code, body}}` on other HTTP errors
  - `{:error, {:network_error, reason}}` on network failure
  """
  @impl true
  @spec get(Config.t(), String.t()) :: {:ok, map()} | {:error, term()}
  def get(%Config{} = config, path) do
    url = build_url(config.base_url, path)
    headers = build_headers(config.api_key)
    timeout = config.timeout

    request = {url, headers}

    case :httpc.request(:get, request, [timeout: timeout, connect_timeout: timeout], []) do
      {:ok, {{_version, status, _reason}, _resp_headers, body}} ->
        handle_response(status, body)

      {:error, reason} ->
        {:error, {:network_error, reason}}
    end
  end

  @doc """
  Perform a POST request to the given path with a JSON body.

  ## Returns
  - `{:ok, map()}` on success (2xx)
  - `{:error, {:auth_error, 401}}` on authentication failure
  - `{:error, {:api_error, status_code, body}}` on other HTTP errors
  - `{:error, {:network_error, reason}}` on network failure
  """
  @impl true
  @spec post(Config.t(), String.t(), map()) :: {:ok, map()} | {:error, term()}
  def post(%Config{} = config, path, body) do
    url = build_url(config.base_url, path)
    headers = build_headers(config.api_key)
    timeout = config.timeout

    encoded_body =
      case Jason.encode(body) do
        {:ok, json} -> json
        {:error, reason} -> raise ArgumentError, "Failed to encode request body: #{inspect(reason)}"
      end

    request = {url, headers, ~c"application/json", encoded_body}

    case :httpc.request(:post, request, [timeout: timeout, connect_timeout: timeout], []) do
      {:ok, {{_version, status, _reason}, _resp_headers, resp_body}} ->
        handle_response(status, resp_body)

      {:error, reason} ->
        {:error, {:network_error, reason}}
    end
  end

  # --- Private Helpers ---

  defp build_url(base_url, path) do
    base = String.trim_trailing(base_url, "/")
    normalized_path = if String.starts_with?(path, "/"), do: path, else: "/" <> path
    to_charlist("#{base}#{normalized_path}")
  end

  defp build_headers(api_key) do
    [
      {~c"X-API-Key", to_charlist(api_key)},
      {~c"Content-Type", ~c"application/json"},
      {~c"Accept", ~c"application/json"},
      {~c"User-Agent", ~c"ExperimentationPlatform-Elixir-SDK/0.1.0"}
    ]
  end

  defp handle_response(status, body) when status >= 200 and status < 300 do
    body_str = to_string(body)

    case Jason.decode(body_str) do
      {:ok, decoded} -> {:ok, decoded}
      {:error, _} -> {:ok, %{"raw" => body_str}}
    end
  end

  defp handle_response(401, _body) do
    {:error, {:auth_error, 401}}
  end

  defp handle_response(status, body) do
    {:error, {:api_error, status, to_string(body)}}
  end
end
