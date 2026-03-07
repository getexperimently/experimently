using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using ExperimentationPlatform;
using ExperimentationPlatform.Exceptions;
using ExperimentationPlatform.Models;
using Xunit;

namespace ExperimentationPlatform.Tests;

/// <summary>
/// Tests for <see cref="ExperimentationClient"/> — high-level SDK behaviour including
/// flag evaluation, caching, experiment assignment, event tracking, and disposal.
/// </summary>
public class ExperimentationClientTests
{
    // -----------------------------------------------------------------------
    // Controllable mock handler
    // -----------------------------------------------------------------------

    private class MockHandler : HttpMessageHandler
    {
        private readonly Queue<(HttpStatusCode status, string body)> _responses = new();
        public int CallCount { get; private set; }

        public void EnqueueResponse(HttpStatusCode status, string body) =>
            _responses.Enqueue((status, body));

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            CallCount++;
            if (_responses.TryDequeue(out var queued))
            {
                var response = new HttpResponseMessage(queued.status)
                {
                    Content = new StringContent(queued.body, Encoding.UTF8, "application/json")
                };
                return Task.FromResult(response);
            }

            // Default: 404.
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound)
            {
                Content = new StringContent("{\"detail\":\"not found\"}", Encoding.UTF8, "application/json")
            });
        }
    }

    private static string Serialize<T>(T obj) =>
        JsonSerializer.Serialize(obj, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            WriteIndented = false
        });

    private static (ExperimentationClient client, MockHandler handler) BuildClient(
        int cacheTtl = 60,
        int cacheSize = 100)
    {
        var handler = new MockHandler();
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://test-api/") };
        var config = new SdkConfig("http://test-api", "test-key")
        {
            CacheTtlSeconds = cacheTtl,
            MaxCacheSize = cacheSize
        };
        var client = new ExperimentationClient(config, httpClient);
        return (client, handler);
    }

    // -----------------------------------------------------------------------
    // EvaluateFlagAsync — basic evaluation
    // -----------------------------------------------------------------------

    [Fact]
    public async Task EvaluateFlagAsync_EnabledFlag_ReturnsEnabledResult()
    {
        var (client, handler) = BuildClient();
        var flag = new FeatureFlag
        {
            Key = "test-flag",
            Enabled = true,
            RolloutPercentage = 100.0,
            Variants = new List<Variant> { new() { Key = "on", Name = "On", Value = true } }
        };
        handler.EnqueueResponse(HttpStatusCode.OK, Serialize(flag));

        var result = await client.EvaluateFlagAsync("test-flag", "user-1");

        Assert.True(result.Enabled);
        Assert.NotNull(result.Variant);
    }

    [Fact]
    public async Task EvaluateFlagAsync_DisabledFlag_ReturnsNotEnabled()
    {
        var (client, handler) = BuildClient();
        var flag = new FeatureFlag
        {
            Key = "off-flag",
            Enabled = false,
            RolloutPercentage = 100.0,
            Variants = new List<Variant> { new() { Key = "on", Name = "On" } }
        };
        handler.EnqueueResponse(HttpStatusCode.OK, Serialize(flag));

        var result = await client.EvaluateFlagAsync("off-flag", "user-1");

        Assert.False(result.Enabled);
        Assert.Null(result.Variant);
    }

    // -----------------------------------------------------------------------
    // EvaluateFlagAsync — caching (second call must not issue HTTP)
    // -----------------------------------------------------------------------

    [Fact]
    public async Task EvaluateFlagAsync_SecondCall_UsesCache_NoExtraHttp()
    {
        var (client, handler) = BuildClient(cacheTtl: 60);
        var flag = new FeatureFlag
        {
            Key = "cached-flag",
            Enabled = true,
            RolloutPercentage = 100.0,
            Variants = new List<Variant> { new() { Key = "v", Name = "V" } }
        };
        // Only one response queued; second call must hit cache.
        handler.EnqueueResponse(HttpStatusCode.OK, Serialize(flag));

        var first = await client.EvaluateFlagAsync("cached-flag", "user-1");
        var second = await client.EvaluateFlagAsync("cached-flag", "user-1");

        Assert.Equal(1, handler.CallCount);
        Assert.Equal(first.Enabled, second.Enabled);
        Assert.Equal(first.Variant, second.Variant);
    }

    // -----------------------------------------------------------------------
    // EvaluateFlagAsync — safe defaults on error
    // -----------------------------------------------------------------------

    [Fact]
    public async Task EvaluateFlagAsync_OnApiError_ReturnsDefault_DoesNotThrow()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.InternalServerError, "{\"detail\":\"boom\"}");

        object? defaultValue = "fallback";
        var result = await client.EvaluateFlagAsync("broken-flag", "user-1", defaultValue: defaultValue);

        Assert.False(result.Enabled);
        Assert.Null(result.Variant);
        Assert.Equal(defaultValue, result.Value);
    }

    [Fact]
    public async Task EvaluateFlagAsync_OnAuthError_ReturnsDefault_DoesNotThrow()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.Unauthorized, "{\"detail\":\"unauthorized\"}");

        var result = await client.EvaluateFlagAsync("any-flag", "user-1");

        Assert.False(result.Enabled);
    }

    // -----------------------------------------------------------------------
    // GetAssignmentAsync
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAssignmentAsync_ValidExperiment_ReturnsAssignment()
    {
        var (client, handler) = BuildClient();
        var assignment = new Assignment
        {
            ExperimentKey = "exp-checkout",
            UserId = "user-42",
            IsInExperiment = true,
            Variant = new Variant { Key = "treatment", Name = "Treatment" }
        };
        handler.EnqueueResponse(HttpStatusCode.OK, Serialize(assignment));

        var result = await client.GetAssignmentAsync("exp-checkout", "user-42");

        Assert.NotNull(result);
        Assert.Equal("exp-checkout", result.ExperimentKey);
        Assert.True(result.IsInExperiment);
        Assert.Equal("treatment", result.Variant?.Key);
    }

    [Fact]
    public async Task GetAssignmentAsync_OnError_ReturnsNull_DoesNotThrow()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.NotFound, "{\"detail\":\"not found\"}");

        var result = await client.GetAssignmentAsync("ghost-exp", "user-1");

        Assert.Null(result);
    }

    // -----------------------------------------------------------------------
    // TrackAsync
    // -----------------------------------------------------------------------

    [Fact]
    public async Task TrackAsync_SuccessfulRequest_ReturnsTrue()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.OK, "{\"status\":\"ok\"}");

        bool result = await client.TrackAsync("button_clicked", "user-99");

        Assert.True(result);
    }

    [Fact]
    public async Task TrackAsync_WithProperties_ReturnsTrue()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.OK, "{\"status\":\"ok\"}");

        bool result = await client.TrackAsync(
            "purchase",
            "user-1",
            new Dictionary<string, object> { { "amount", 99.99 }, { "currency", "USD" } });

        Assert.True(result);
    }

    [Fact]
    public async Task TrackAsync_OnApiError_ReturnsFalse_DoesNotThrow()
    {
        var (client, handler) = BuildClient();
        handler.EnqueueResponse(HttpStatusCode.InternalServerError, "{\"detail\":\"error\"}");

        bool result = await client.TrackAsync("event", "user-1");

        Assert.False(result);
    }

    [Fact]
    public async Task TrackAsync_OnNetworkError_ReturnsFalse_DoesNotThrow()
    {
        // Queue nothing — default 404 response from MockHandler simulates an error path.
        var (client, _) = BuildClient();
        // Force a network error by using a handler that throws.
        var handler = new ThrowingHandler(new HttpRequestException("Connection refused"));
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://test/") };
        var config = new SdkConfig("http://test", "key");
        var throwingClient = new ExperimentationClient(config, httpClient);

        bool result = await throwingClient.TrackAsync("event", "user-1");

        Assert.False(result);
    }

    // -----------------------------------------------------------------------
    // Dispose
    // -----------------------------------------------------------------------

    [Fact]
    public void Dispose_DoesNotThrow()
    {
        var handler = new MockHandler();
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://test/") };
        var config = new SdkConfig("http://test", "key");
        var client = new ExperimentationClient(config, httpClient);

        var ex = Record.Exception(() => client.Dispose());
        Assert.Null(ex);
    }

    [Fact]
    public void Dispose_CalledTwice_DoesNotThrow()
    {
        var handler = new MockHandler();
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://test/") };
        var config = new SdkConfig("http://test", "key");
        var client = new ExperimentationClient(config, httpClient);

        client.Dispose();
        var ex = Record.Exception(() => client.Dispose());
        Assert.Null(ex);
    }

    // -----------------------------------------------------------------------
    // Helper
    // -----------------------------------------------------------------------

    private class ThrowingHandler : HttpMessageHandler
    {
        private readonly Exception _ex;
        public ThrowingHandler(Exception ex) => _ex = ex;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => throw _ex;
    }
}
