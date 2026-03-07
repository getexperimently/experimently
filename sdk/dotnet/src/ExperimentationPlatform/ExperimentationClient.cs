using ExperimentationPlatform.Exceptions;
using ExperimentationPlatform.Models;

namespace ExperimentationPlatform;

/// <summary>
/// High-level SDK client for evaluating feature flags, getting experiment assignments,
/// and tracking analytics events.
/// </summary>
public class ExperimentationClient : IDisposable
{
    private readonly SdkConfig _config;
    private readonly ExperimentationHttpClient _httpClient;
    private readonly SdkCache<FeatureFlag> _flagCache;
    private bool _disposed;

    /// <summary>
    /// Creates a new client.
    /// </summary>
    /// <param name="config">Required SDK configuration.</param>
    /// <param name="httpClient">
    /// Optional pre-configured <see cref="System.Net.Http.HttpClient"/> for testability.
    /// If not supplied the SDK creates and manages its own instance.
    /// </param>
    public ExperimentationClient(SdkConfig config, System.Net.Http.HttpClient? httpClient = null)
    {
        _config = config ?? throw new ArgumentNullException(nameof(config));
        _httpClient = new ExperimentationHttpClient(config, httpClient);
        _flagCache = new SdkCache<FeatureFlag>(
            maxSize: config.MaxCacheSize,
            defaultTtl: TimeSpan.FromSeconds(config.CacheTtlSeconds));
    }

    // Internal constructor for testing with a pre-built http wrapper.
    internal ExperimentationClient(SdkConfig config, ExperimentationHttpClient httpClient, SdkCache<FeatureFlag>? cache = null)
    {
        _config = config;
        _httpClient = httpClient;
        _flagCache = cache ?? new SdkCache<FeatureFlag>(
            maxSize: config.MaxCacheSize,
            defaultTtl: TimeSpan.FromSeconds(config.CacheTtlSeconds));
    }

    // -----------------------------------------------------------------
    // Public API
    // -----------------------------------------------------------------

    /// <summary>
    /// Evaluates a feature flag for a specific user.
    /// Fetches the flag from the API (with caching) and performs local bucket evaluation.
    /// </summary>
    /// <param name="flagKey">The feature flag key.</param>
    /// <param name="userId">The user ID.</param>
    /// <param name="attributes">Optional user attributes for future targeting rules.</param>
    /// <param name="defaultValue">Returned as <c>Value</c> when the flag is disabled or evaluation fails.</param>
    /// <returns>A <see cref="FlagEvaluationResult"/> (never throws; returns a safe default on error).</returns>
    public async Task<FlagEvaluationResult> EvaluateFlagAsync(
        string flagKey,
        string userId,
        Dictionary<string, object>? attributes = null,
        object? defaultValue = null)
    {
        try
        {
            var flag = await GetFlagAsync(flagKey).ConfigureAwait(false);
            var variant = FeatureFlagEvaluator.Evaluate(flag, userId, attributes);

            return new FlagEvaluationResult
            {
                Enabled = variant != null,
                Variant = variant?.Key,
                Value = variant?.Value ?? (variant != null ? (object)true : defaultValue)
            };
        }
        catch (Exception)
        {
            // Never throw — return safe defaults.
            return new FlagEvaluationResult
            {
                Enabled = false,
                Variant = null,
                Value = defaultValue
            };
        }
    }

    /// <summary>
    /// Retrieves the experiment assignment for a specific user.
    /// </summary>
    /// <param name="experimentKey">The experiment key.</param>
    /// <param name="userId">The user ID.</param>
    /// <param name="attributes">Optional user attributes.</param>
    /// <returns>An <see cref="Assignment"/>, or <c>null</c> on error.</returns>
    public async Task<Assignment?> GetAssignmentAsync(
        string experimentKey,
        string userId,
        Dictionary<string, object>? attributes = null)
    {
        try
        {
            var path = BuildAssignmentPath(experimentKey, userId, attributes);
            var assignment = await _httpClient.GetAsync<Assignment>(path).ConfigureAwait(false);
            return assignment;
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>
    /// Sends an analytics tracking event.
    /// </summary>
    /// <param name="eventName">The event name.</param>
    /// <param name="userId">The user who triggered the event.</param>
    /// <param name="properties">Optional event properties.</param>
    /// <returns><c>true</c> if the event was accepted; <c>false</c> on any error (never throws).</returns>
    public async Task<bool> TrackAsync(
        string eventName,
        string userId,
        Dictionary<string, object>? properties = null)
    {
        try
        {
            var payload = new TrackEvent
            {
                EventName = eventName,
                UserId = userId,
                Properties = properties
            };
            await _httpClient.PostAsync<object>("api/v1/events/track", payload).ConfigureAwait(false);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    // -----------------------------------------------------------------
    // Private helpers
    // -----------------------------------------------------------------

    private async Task<FeatureFlag> GetFlagAsync(string flagKey)
    {
        // Attempt cache hit first.
        var cached = _flagCache.Get(flagKey);
        if (cached != null)
            return cached;

        // Fetch from API.
        var flag = await _httpClient.GetAsync<FeatureFlag>($"api/v1/flags/{flagKey}").ConfigureAwait(false);
        _flagCache.Set(flagKey, flag);
        return flag;
    }

    private static string BuildAssignmentPath(
        string experimentKey,
        string userId,
        Dictionary<string, object>? attributes)
    {
        var encoded = Uri.EscapeDataString(userId);
        return $"api/v1/experiments/{experimentKey}/assignment?user_id={encoded}";
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        _httpClient.Dispose();
        GC.SuppressFinalize(this);
    }
}
