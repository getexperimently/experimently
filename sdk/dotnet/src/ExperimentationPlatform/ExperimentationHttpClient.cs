using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using ExperimentationPlatform.Exceptions;

namespace ExperimentationPlatform;

/// <summary>
/// Wraps <see cref="System.Net.Http.HttpClient"/> with authentication, serialisation,
/// and error mapping for the Experimentation Platform API.
/// </summary>
public class ExperimentationHttpClient : IDisposable
{
    private readonly SdkConfig _config;
    private readonly HttpClient _httpClient;
    private readonly bool _ownsHttpClient;
    private bool _disposed;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    /// <summary>
    /// Creates a new HTTP client wrapper.
    /// </summary>
    /// <param name="config">SDK configuration including base URL and API key.</param>
    /// <param name="httpClient">
    /// Optional pre-configured <see cref="HttpClient"/>. If not supplied a new instance is created
    /// (and will be disposed when this object is disposed).
    /// </param>
    public ExperimentationHttpClient(SdkConfig config, HttpClient? httpClient = null)
    {
        _config = config ?? throw new ArgumentNullException(nameof(config));

        if (httpClient != null)
        {
            _httpClient = httpClient;
            _ownsHttpClient = false;
        }
        else
        {
            _httpClient = new HttpClient
            {
                BaseAddress = new Uri(config.BaseUrl.TrimEnd('/') + "/"),
                Timeout = TimeSpan.FromSeconds(config.TimeoutSeconds)
            };
            _ownsHttpClient = true;
        }

        _httpClient.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", config.ApiKey);
        _httpClient.DefaultRequestHeaders.Accept.Add(
            new MediaTypeWithQualityHeaderValue("application/json"));
    }

    /// <summary>Sends a GET request and deserialises the JSON response.</summary>
    /// <typeparam name="T">The expected response type.</typeparam>
    /// <param name="path">The relative API path.</param>
    /// <returns>The deserialised response body.</returns>
    /// <exception cref="AuthException">Thrown for HTTP 401.</exception>
    /// <exception cref="ApiException">Thrown for other non-success HTTP codes.</exception>
    /// <exception cref="NetworkException">Thrown for connectivity / timeout errors.</exception>
    public async Task<T> GetAsync<T>(string path)
    {
        try
        {
            var response = await _httpClient.GetAsync(path).ConfigureAwait(false);
            return await HandleResponseAsync<T>(response).ConfigureAwait(false);
        }
        catch (ExperimentationException)
        {
            throw;
        }
        catch (HttpRequestException ex)
        {
            throw new NetworkException($"Network error calling GET {path}: {ex.Message}", ex);
        }
        catch (TaskCanceledException ex)
        {
            throw new NetworkException($"Request timed out calling GET {path}: {ex.Message}", ex);
        }
    }

    /// <summary>Sends a POST request with a JSON body and deserialises the JSON response.</summary>
    /// <typeparam name="T">The expected response type.</typeparam>
    /// <param name="path">The relative API path.</param>
    /// <param name="body">The request body (will be serialised to JSON).</param>
    /// <returns>The deserialised response body.</returns>
    /// <exception cref="AuthException">Thrown for HTTP 401.</exception>
    /// <exception cref="ApiException">Thrown for other non-success HTTP codes.</exception>
    /// <exception cref="NetworkException">Thrown for connectivity / timeout errors.</exception>
    public async Task<T> PostAsync<T>(string path, object body)
    {
        try
        {
            string json = JsonSerializer.Serialize(body, JsonOptions);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = await _httpClient.PostAsync(path, content).ConfigureAwait(false);
            return await HandleResponseAsync<T>(response).ConfigureAwait(false);
        }
        catch (ExperimentationException)
        {
            throw;
        }
        catch (HttpRequestException ex)
        {
            throw new NetworkException($"Network error calling POST {path}: {ex.Message}", ex);
        }
        catch (TaskCanceledException ex)
        {
            throw new NetworkException($"Request timed out calling POST {path}: {ex.Message}", ex);
        }
    }

    // -----------------------------------------------------------------
    // Private helpers
    // -----------------------------------------------------------------

    private static async Task<T> HandleResponseAsync<T>(HttpResponseMessage response)
    {
        string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);

        if (response.StatusCode == HttpStatusCode.Unauthorized)
            throw new AuthException($"Authentication failed (HTTP 401). Check your API key.");

        if (!response.IsSuccessStatusCode)
            throw new ApiException(
                (int)response.StatusCode,
                $"API request failed with status {(int)response.StatusCode} {response.ReasonPhrase}.",
                responseBody: body);

        if (typeof(T) == typeof(bool))
        {
            // Allow endpoints that return an empty 200/204 body to resolve as true.
            if (string.IsNullOrWhiteSpace(body))
                return (T)(object)true;
        }

        try
        {
            var result = JsonSerializer.Deserialize<T>(body, JsonOptions);
            return result ?? throw new ApiException(
                (int)response.StatusCode,
                "API returned a null response body.",
                responseBody: body);
        }
        catch (JsonException ex)
        {
            throw new ApiException(
                (int)response.StatusCode,
                $"Failed to deserialise API response: {ex.Message}",
                ex,
                responseBody: body);
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        if (_ownsHttpClient)
            _httpClient.Dispose();
    }
}
