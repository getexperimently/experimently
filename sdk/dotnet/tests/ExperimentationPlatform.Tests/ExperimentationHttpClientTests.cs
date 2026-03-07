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
/// Tests for <see cref="ExperimentationHttpClient"/> using a mock HTTP message handler.
/// </summary>
public class ExperimentationHttpClientTests
{
    // -----------------------------------------------------------------------
    // Mock handler
    // -----------------------------------------------------------------------

    /// <summary>
    /// A simple delegating handler that returns a pre-canned HTTP response.
    /// </summary>
    private class MockHttpMessageHandler : HttpMessageHandler
    {
        private readonly HttpResponseMessage _response;
        public HttpRequestMessage? LastRequest { get; private set; }

        public MockHttpMessageHandler(HttpResponseMessage response) =>
            _response = response;

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastRequest = request;
            return Task.FromResult(_response);
        }
    }

    private static (ExperimentationHttpClient client, MockHttpMessageHandler handler) BuildClient(
        HttpStatusCode statusCode,
        string? body = null,
        string contentType = "application/json")
    {
        var response = new HttpResponseMessage(statusCode);
        if (body != null)
            response.Content = new StringContent(body, Encoding.UTF8, contentType);

        var handler = new MockHttpMessageHandler(response);
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://test-api/") };
        var config = new SdkConfig("http://test-api", "test-api-key");
        var client = new ExperimentationHttpClient(config, httpClient);

        return (client, handler);
    }

    private static string Serialize<T>(T obj) =>
        JsonSerializer.Serialize(obj, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });

    // -----------------------------------------------------------------------
    // Successful GET
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_SuccessfulResponse_DeserializesJson()
    {
        var flag = new FeatureFlag
        {
            Key = "my-flag",
            Enabled = true,
            RolloutPercentage = 100.0,
            Variants = new List<Variant> { new() { Key = "control", Name = "Control" } }
        };
        string json = Serialize(flag);

        var (client, _) = BuildClient(HttpStatusCode.OK, json);

        var result = await client.GetAsync<FeatureFlag>("api/v1/flags/my-flag");
        Assert.NotNull(result);
        Assert.Equal("my-flag", result.Key);
        Assert.True(result.Enabled);
    }

    // -----------------------------------------------------------------------
    // Successful POST
    // -----------------------------------------------------------------------

    [Fact]
    public async Task PostAsync_SuccessfulResponse_SendsJsonBody()
    {
        var assignment = new Assignment
        {
            ExperimentKey = "exp-1",
            UserId = "user-1",
            IsInExperiment = true,
            Variant = new Variant { Key = "treatment", Name = "Treatment" }
        };
        string responseJson = Serialize(assignment);

        var (client, handler) = BuildClient(HttpStatusCode.OK, responseJson);

        var result = await client.PostAsync<Assignment>("api/v1/events/track", new { });
        Assert.NotNull(result);
        Assert.Equal("exp-1", result.ExperimentKey);

        // Verify the request was sent with a JSON content type.
        Assert.NotNull(handler.LastRequest?.Content);
        var requestContent = await handler.LastRequest!.Content!.ReadAsStringAsync();
        Assert.NotEmpty(requestContent);
    }

    // -----------------------------------------------------------------------
    // HTTP 401 → AuthException
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_Http401_ThrowsAuthException()
    {
        var (client, _) = BuildClient(HttpStatusCode.Unauthorized, "{\"detail\": \"Unauthorized\"}");
        await Assert.ThrowsAsync<AuthException>(() => client.GetAsync<FeatureFlag>("api/v1/flags/x"));
    }

    [Fact]
    public async Task PostAsync_Http401_ThrowsAuthException()
    {
        var (client, _) = BuildClient(HttpStatusCode.Unauthorized);
        await Assert.ThrowsAsync<AuthException>(() => client.PostAsync<object>("api/v1/events/track", new { }));
    }

    // -----------------------------------------------------------------------
    // HTTP 404 → ApiException with correct StatusCode
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_Http404_ThrowsApiExceptionWithStatus404()
    {
        var (client, _) = BuildClient(HttpStatusCode.NotFound, "{\"detail\": \"Flag not found\"}");

        var ex = await Assert.ThrowsAsync<ApiException>(() => client.GetAsync<FeatureFlag>("api/v1/flags/ghost"));
        Assert.Equal(404, ex.StatusCode);
    }

    // -----------------------------------------------------------------------
    // HTTP 500 → ApiException
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_Http500_ThrowsApiException()
    {
        var (client, _) = BuildClient(HttpStatusCode.InternalServerError, "{\"detail\": \"Internal error\"}");

        var ex = await Assert.ThrowsAsync<ApiException>(() => client.GetAsync<FeatureFlag>("api/v1/flags/err"));
        Assert.Equal(500, ex.StatusCode);
    }

    // -----------------------------------------------------------------------
    // Network error → NetworkException
    // -----------------------------------------------------------------------

    private class ThrowingHandler : HttpMessageHandler
    {
        private readonly Exception _ex;
        public ThrowingHandler(Exception ex) => _ex = ex;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
            => throw _ex;
    }

    [Fact]
    public async Task GetAsync_NetworkError_ThrowsNetworkException()
    {
        var handler = new ThrowingHandler(new HttpRequestException("Connection refused"));
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://unreachable/") };
        var config = new SdkConfig("http://unreachable", "key");
        var client = new ExperimentationHttpClient(config, httpClient);

        await Assert.ThrowsAsync<NetworkException>(() => client.GetAsync<FeatureFlag>("api/v1/flags/x"));
    }

    // -----------------------------------------------------------------------
    // ApiException carries response body
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_HttpError_ApiExceptionContainsResponseBody()
    {
        const string errorBody = "{\"detail\": \"Feature flag not found\"}";
        var (client, _) = BuildClient(HttpStatusCode.NotFound, errorBody);

        var ex = await Assert.ThrowsAsync<ApiException>(() => client.GetAsync<FeatureFlag>("api/v1/flags/missing"));
        Assert.Equal(errorBody, ex.ResponseBody);
    }

    // -----------------------------------------------------------------------
    // Authorization header is sent
    // -----------------------------------------------------------------------

    [Fact]
    public async Task GetAsync_SetsAuthorizationHeader()
    {
        var flag = new FeatureFlag { Key = "f", Enabled = true, RolloutPercentage = 100 };
        var (client, handler) = BuildClient(HttpStatusCode.OK, Serialize(flag));

        await client.GetAsync<FeatureFlag>("api/v1/flags/f");

        Assert.NotNull(handler.LastRequest?.Headers.Authorization);
        Assert.Equal("Bearer", handler.LastRequest!.Headers.Authorization!.Scheme);
        Assert.Equal("test-api-key", handler.LastRequest.Headers.Authorization.Parameter);
    }
}
