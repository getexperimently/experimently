namespace ExperimentationPlatform;

/// <summary>
/// Configuration for the ExperimentationClient SDK.
/// </summary>
public class SdkConfig
{
    /// <summary>The base URL of the Experimentation Platform API (e.g. "https://api.example.com").</summary>
    public string BaseUrl { get; init; }

    /// <summary>The API key used for authentication.</summary>
    public string ApiKey { get; init; }

    /// <summary>How long to cache feature flag responses in seconds. Default: 300 (5 minutes).</summary>
    public int CacheTtlSeconds { get; init; } = 300;

    /// <summary>HTTP request timeout in seconds. Default: 10.</summary>
    public int TimeoutSeconds { get; init; } = 10;

    /// <summary>Maximum number of entries to hold in the in-memory cache. Default: 1000.</summary>
    public int MaxCacheSize { get; init; } = 1000;

    /// <summary>
    /// Initialises a new SdkConfig.
    /// </summary>
    /// <param name="baseUrl">Required. The API base URL (must not be null or empty).</param>
    /// <param name="apiKey">Required. The API key (must not be null or empty).</param>
    /// <exception cref="ArgumentException">Thrown if baseUrl or apiKey is null or empty.</exception>
    public SdkConfig(string baseUrl, string apiKey)
    {
        if (string.IsNullOrWhiteSpace(baseUrl))
            throw new ArgumentException("BaseUrl is required and must not be empty.", nameof(baseUrl));
        if (string.IsNullOrWhiteSpace(apiKey))
            throw new ArgumentException("ApiKey is required and must not be empty.", nameof(apiKey));

        BaseUrl = baseUrl.TrimEnd('/');
        ApiKey = apiKey;
    }
}
