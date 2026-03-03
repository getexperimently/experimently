package com.experimentationplatform.sdk;

import com.experimentationplatform.sdk.config.SdkConfig;
import com.experimentationplatform.sdk.exception.ExperimentationException;
import com.experimentationplatform.sdk.model.ExperimentAssignment;
import com.experimentationplatform.sdk.model.FeatureFlag;
import com.experimentationplatform.sdk.model.User;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration-style unit tests for {@link ExperimentationClient} using OkHttp's
 * {@link MockWebServer} to simulate real HTTP interactions.
 */
@DisplayName("ExperimentationClient")
class ExperimentationClientTest {

    private MockWebServer mockServer;
    private SdkConfig config;
    private ExperimentationClient client;
    private ObjectMapper objectMapper;

    @BeforeEach
    void setUp() throws IOException {
        mockServer = new MockWebServer();
        mockServer.start();

        String baseUrl = mockServer.url("/").toString();
        // Strip trailing slash — SdkConfig.Builder does this automatically
        config = SdkConfig.builder("test-api-key", baseUrl)
                .timeoutMs(5000)
                .cacheSize(100)
                .cacheTtlMs(60_000L)
                .build();

        OkHttpClient httpClient = new OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(5, TimeUnit.SECONDS)
                .build();

        client = new ExperimentationClient(config, httpClient);
        objectMapper = new ObjectMapper();
    }

    @AfterEach
    void tearDown() throws IOException {
        client.close();
        mockServer.shutdown();
    }

    // =========================================================================
    // evaluateFeatureFlag
    // =========================================================================

    @Test
    @DisplayName("evaluateFeatureFlag sends GET request with correct headers")
    void testEvaluateFeatureFlagMakesCorrectApiCall() throws InterruptedException {
        // Arrange: enabled flag at 100% → all users in rollout
        FeatureFlag flag = new FeatureFlag("id-1", "my-feature", true, 100.0, null);
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();

        // Act
        String result = client.evaluateFeatureFlag(user, "my-feature");

        // Assert: result is "on" (boolean flag, 100% rollout)
        assertEquals("on", result);

        // Assert: correct request was made
        RecordedRequest request = mockServer.takeRequest();
        assertEquals("GET", request.getMethod());
        assertTrue(request.getPath().contains("/api/v1/feature-flags/my-feature/evaluate"),
                "Path should contain the feature flag evaluate endpoint");
        assertEquals("test-api-key", request.getHeader("X-API-Key"),
                "X-API-Key header should be set");
        assertEquals("user-123", request.getHeader("X-User-ID"),
                "X-User-ID header should be set");
    }

    @Test
    @DisplayName("evaluateFeatureFlag returns 'off' when flag is disabled")
    void testEvaluateFeatureFlagReturnsOffWhenFlagDisabled() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "disabled-flag", false, 100.0, null);
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();
        String result = client.evaluateFeatureFlag(user, "disabled-flag");

        assertEquals("off", result,
                "Disabled flag should return 'off'");
    }

    @Test
    @DisplayName("evaluateFeatureFlag returns correct variant for multi-variant flag")
    void testEvaluateFeatureFlagReturnsVariant() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "mv-flag", true, 100.0,
                Arrays.asList(
                        new FeatureFlag.Variant("control", 0.5),
                        new FeatureFlag.Variant("treatment", 0.5)
                ));
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();
        String result = client.evaluateFeatureFlag(user, "mv-flag");

        assertNotNull(result);
        assertTrue(result.equals("control") || result.equals("treatment"),
                "Result should be a known variant name, got: " + result);
    }

    @Test
    @DisplayName("evaluateFeatureFlag returns cached result on second call (no second HTTP request)")
    void testEvaluateFeatureFlagUsesCache() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "cached-flag", true, 100.0, null);
        // Enqueue only ONE response — second call should hit cache
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();

        String result1 = client.evaluateFeatureFlag(user, "cached-flag");
        String result2 = client.evaluateFeatureFlag(user, "cached-flag");

        assertEquals("on", result1);
        assertEquals("on", result2, "Second call should return same cached result");

        // Only one HTTP request should have been made
        assertEquals(1, mockServer.getRequestCount(),
                "Only one HTTP request should have been made (second call served from cache)");
    }

    @Test
    @DisplayName("evaluateFeatureFlag throws ExperimentationException on 401 Unauthorized")
    void testEvaluateFeatureFlagThrowsOn401() {
        mockServer.enqueue(new MockResponse().setResponseCode(401));

        User user = User.builder("user-123").build();
        ExperimentationException ex = assertThrows(ExperimentationException.class,
                () -> client.evaluateFeatureFlag(user, "my-feature"));

        assertEquals(401, ex.getStatusCode());
        assertTrue(ex.isApiError());
    }

    @Test
    @DisplayName("evaluateFeatureFlag throws ExperimentationException on 404 Not Found")
    void testEvaluateFeatureFlagThrowsOn404() {
        mockServer.enqueue(new MockResponse().setResponseCode(404));

        User user = User.builder("user-123").build();
        ExperimentationException ex = assertThrows(ExperimentationException.class,
                () -> client.evaluateFeatureFlag(user, "unknown-flag"));

        assertEquals(404, ex.getStatusCode());
    }

    @Test
    @DisplayName("evaluateFeatureFlag throws ExperimentationException on 500 Internal Server Error")
    void testEvaluateFeatureFlagThrowsOnApiError() {
        mockServer.enqueue(new MockResponse().setResponseCode(500));

        User user = User.builder("user-123").build();
        ExperimentationException ex = assertThrows(ExperimentationException.class,
                () -> client.evaluateFeatureFlag(user, "my-feature"));

        assertEquals(500, ex.getStatusCode());
        assertTrue(ex.getMessage().contains("500"),
                "Exception message should contain status code");
    }

    @Test
    @DisplayName("evaluateFeatureFlag throws IllegalArgumentException for null user")
    void testEvaluateFeatureFlagThrowsForNullUser() {
        assertThrows(IllegalArgumentException.class,
                () -> client.evaluateFeatureFlag(null, "my-feature"));
    }

    @Test
    @DisplayName("evaluateFeatureFlag throws IllegalArgumentException for empty flagKey")
    void testEvaluateFeatureFlagThrowsForEmptyFlagKey() {
        User user = User.builder("user-123").build();
        assertThrows(IllegalArgumentException.class,
                () -> client.evaluateFeatureFlag(user, ""));
    }

    @Test
    @DisplayName("invalidateCache forces fresh API call on next evaluation")
    void testInvalidateCacheForcesFreshApiCall() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "my-feature", true, 100.0, null);
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();

        client.evaluateFeatureFlag(user, "my-feature");
        assertEquals(1, mockServer.getRequestCount(), "First call should hit API");

        client.invalidateCache("user-123", "my-feature");
        client.evaluateFeatureFlag(user, "my-feature");
        assertEquals(2, mockServer.getRequestCount(),
                "After cache invalidation, second call should hit API again");
    }

    // =========================================================================
    // getExperimentAssignment
    // =========================================================================

    @Test
    @DisplayName("getExperimentAssignment sends POST request with correct payload")
    void testGetExperimentAssignmentSendsCorrectRequest() throws InterruptedException, IOException {
        ExperimentAssignment assignment = new ExperimentAssignment(
                "exp-id-1", "checkout-test", "user-123", "treatment", true, "hash_assignment"
        );
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(assignment)));

        User user = User.builder("user-123")
                .attribute("country", "US")
                .build();

        ExperimentAssignment result = client.getExperimentAssignment(user, "checkout-test");

        // Assert response is deserialized correctly
        assertNotNull(result);
        assertEquals("exp-id-1", result.getExperimentId());
        assertEquals("checkout-test", result.getExperimentKey());
        assertEquals("user-123", result.getUserId());
        assertEquals("treatment", result.getVariantKey());
        assertTrue(result.isInExperiment());

        // Assert request structure
        RecordedRequest request = mockServer.takeRequest();
        assertEquals("POST", request.getMethod());
        assertTrue(request.getPath().contains("/api/v1/assignments"));
        assertEquals("test-api-key", request.getHeader("X-API-Key"));

        String body = request.getBody().readUtf8();
        Map<?, ?> payload = objectMapper.readValue(body, Map.class);
        assertEquals("user-123", payload.get("user_id"));
        assertEquals("checkout-test", payload.get("experiment_key"));
    }

    @Test
    @DisplayName("getExperimentAssignment throws ExperimentationException on 404")
    void testGetExperimentAssignmentThrowsOn404() {
        mockServer.enqueue(new MockResponse().setResponseCode(404));

        User user = User.builder("user-123").build();
        ExperimentationException ex = assertThrows(ExperimentationException.class,
                () -> client.getExperimentAssignment(user, "nonexistent-experiment"));

        assertEquals(404, ex.getStatusCode());
    }

    @Test
    @DisplayName("getExperimentAssignment throws IllegalArgumentException for null user")
    void testGetExperimentAssignmentThrowsForNullUser() {
        assertThrows(IllegalArgumentException.class,
                () -> client.getExperimentAssignment(null, "checkout-test"));
    }

    @Test
    @DisplayName("getExperimentAssignment throws IllegalArgumentException for empty experimentKey")
    void testGetExperimentAssignmentThrowsForEmptyKey() {
        User user = User.builder("user-123").build();
        assertThrows(IllegalArgumentException.class,
                () -> client.getExperimentAssignment(user, ""));
    }

    // =========================================================================
    // trackEvent
    // =========================================================================

    @Test
    @DisplayName("trackEvent sends async POST to events endpoint")
    void testTrackEventFiresAndForgets() throws InterruptedException {
        mockServer.enqueue(new MockResponse().setResponseCode(202));

        Map<String, Object> props = new HashMap<>();
        props.put("page", "home");
        props.put("button", "checkout");

        client.trackEvent("user-123", "button_clicked", props);

        // Wait for the async request
        RecordedRequest request = mockServer.takeRequest(3, TimeUnit.SECONDS);
        assertNotNull(request, "Event tracking request should have been sent");
        assertEquals("POST", request.getMethod());
        assertTrue(request.getPath().contains("/api/v1/events"));
        assertEquals("test-api-key", request.getHeader("X-API-Key"));

        String body = request.getBody().readUtf8();
        assertTrue(body.contains("user-123"), "Request body should contain user_id");
        assertTrue(body.contains("button_clicked"), "Request body should contain event_name");
    }

    @Test
    @DisplayName("trackEvent does not throw when server returns 500")
    void testTrackEventDoesNotThrowOnServerError() throws InterruptedException {
        mockServer.enqueue(new MockResponse().setResponseCode(500));

        // Should not throw — fire and forget
        assertDoesNotThrow(() -> client.trackEvent("user-123", "some_event", null));

        // Give the async call time to complete
        Thread.sleep(200);
    }

    @Test
    @DisplayName("trackEvent with null properties does not throw")
    void testTrackEventWithNullPropertiesDoesNotThrow() throws InterruptedException {
        mockServer.enqueue(new MockResponse().setResponseCode(202));
        assertDoesNotThrow(() -> client.trackEvent("user-123", "page_view", null));
        // Brief wait for async request
        Thread.sleep(200);
    }

    @Test
    @DisplayName("trackEvent with empty userId is silently ignored (no request sent)")
    void testTrackEventWithEmptyUserIdIsIgnored() throws InterruptedException {
        // No mock enqueued — if a request is made the test will likely hang or fail

        client.trackEvent("", "some_event", null);

        // Give any potential async call time to fire (it shouldn't)
        Thread.sleep(100);

        assertEquals(0, mockServer.getRequestCount(),
                "No HTTP request should be made for empty userId");
    }

    // =========================================================================
    // clearCache
    // =========================================================================

    @Test
    @DisplayName("clearCache causes next evaluation to make fresh API call")
    void testClearCacheCausesFreshApiCall() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "my-feature", true, 100.0, null);
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));

        User user = User.builder("user-123").build();

        client.evaluateFeatureFlag(user, "my-feature");
        assertEquals(1, mockServer.getRequestCount());

        client.clearCache();
        client.evaluateFeatureFlag(user, "my-feature");
        assertEquals(2, mockServer.getRequestCount(),
                "After clearCache, next call should hit API");
    }

    // =========================================================================
    // getCacheSize
    // =========================================================================

    @Test
    @DisplayName("getCacheSize reflects number of cached entries")
    void testGetCacheSizeReflectsEntries() throws InterruptedException {
        FeatureFlag flag = new FeatureFlag("id-1", "flag-a", true, 100.0, null);
        FeatureFlag flag2 = new FeatureFlag("id-2", "flag-b", true, 100.0, null);

        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag)));
        mockServer.enqueue(new MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(toJson(flag2)));

        assertEquals(0, client.getCacheSize(), "Cache should be empty initially");

        User user = User.builder("user-123").build();
        client.evaluateFeatureFlag(user, "flag-a");
        assertEquals(1, client.getCacheSize());

        client.evaluateFeatureFlag(user, "flag-b");
        assertEquals(2, client.getCacheSize());
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            throw new RuntimeException("Failed to serialize to JSON", e);
        }
    }
}
