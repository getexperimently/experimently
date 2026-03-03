package com.experimentationplatform.sdk;

import com.experimentationplatform.sdk.config.SdkConfig;
import com.experimentationplatform.sdk.exception.ExperimentationException;
import com.experimentationplatform.sdk.model.ExperimentAssignment;
import com.experimentationplatform.sdk.model.FeatureFlag;
import com.experimentationplatform.sdk.model.User;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import okhttp3.*;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * Main client for the Experimentation Platform SDK.
 *
 * <p>Provides high-level methods for:
 * <ul>
 *   <li>Feature flag evaluation (remote API with local consistent-hash fallback)</li>
 *   <li>Experiment assignment retrieval</li>
 *   <li>Event tracking (fire-and-forget)</li>
 * </ul>
 *
 * <h2>Usage</h2>
 * <pre>
 *     SdkConfig config = SdkConfig.builder("my-api-key", "https://api.example.com")
 *         .timeoutMs(3000)
 *         .cacheSize(500)
 *         .cacheTtlMs(60_000L)
 *         .build();
 *
 *     try (ExperimentationClient client = new ExperimentationClient(config)) {
 *         User user = User.builder("user-123")
 *             .attribute("country", "US")
 *             .build();
 *
 *         String variant = client.evaluateFeatureFlag(user, "my-feature");
 *         // "on", "off", "control", "treatment", etc.
 *
 *         client.trackEvent("user-123", "button_clicked", Map.of("page", "home"));
 *     }
 * </pre>
 *
 * <p>The client is thread-safe. It implements {@link AutoCloseable} — always close it
 * (or use try-with-resources) to release the underlying HTTP connection pool.
 */
public class ExperimentationClient implements AutoCloseable {

    static final MediaType JSON = MediaType.parse("application/json; charset=utf-8");

    private final SdkConfig config;
    private final OkHttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final FeatureFlagEvaluator evaluator;
    private final AssignmentCache cache;

    /**
     * Creates a new ExperimentationClient with the provided configuration.
     *
     * @param config SDK configuration (API key, base URL, timeouts, cache settings)
     */
    public ExperimentationClient(SdkConfig config) {
        this.config = config;
        this.httpClient = new OkHttpClient.Builder()
                .connectTimeout(config.getTimeoutMs(), TimeUnit.MILLISECONDS)
                .readTimeout(config.getTimeoutMs(), TimeUnit.MILLISECONDS)
                .writeTimeout(config.getTimeoutMs(), TimeUnit.MILLISECONDS)
                .build();
        this.objectMapper = new ObjectMapper();
        this.evaluator = new FeatureFlagEvaluator();
        this.cache = new AssignmentCache(config.getCacheSize(), config.getCacheTtlMs());
    }

    /**
     * Package-private constructor for testing with a custom OkHttpClient (e.g., MockWebServer).
     */
    ExperimentationClient(SdkConfig config, OkHttpClient httpClient) {
        this.config = config;
        this.httpClient = httpClient;
        this.objectMapper = new ObjectMapper();
        this.evaluator = new FeatureFlagEvaluator();
        this.cache = new AssignmentCache(config.getCacheSize(), config.getCacheTtlMs());
    }

    /**
     * Evaluates a feature flag for a user.
     *
     * <p>Flow:
     * <ol>
     *   <li>Check the in-memory cache. If hit and not expired, return the cached value.</li>
     *   <li>Fetch the flag configuration from {@code GET /api/v1/feature-flags/{flagKey}/evaluate}.</li>
     *   <li>Evaluate locally using consistent hashing.</li>
     *   <li>Cache the result and return it.</li>
     * </ol>
     *
     * <p>Returns {@code "off"} if the flag is disabled or the user is not in the rollout.
     * Returns {@code "on"} for boolean flags where the user is in the rollout.
     * Returns the variant name for multi-variant flags.
     *
     * @param user    the user to evaluate the flag for
     * @param flagKey the feature flag key (e.g., "new-checkout-flow")
     * @return variant name or {@code "off"}
     * @throws ExperimentationException if the API returns a non-success response or a network error occurs
     */
    public String evaluateFeatureFlag(User user, String flagKey) {
        if (user == null) throw new IllegalArgumentException("user must not be null");
        if (flagKey == null || flagKey.isEmpty()) throw new IllegalArgumentException("flagKey must not be empty");

        String cacheKey = user.getUserId() + ":" + flagKey;
        String cached = cache.get(cacheKey);
        if (cached != null) {
            return cached;
        }

        String url = config.getBaseUrl() + "/api/v1/feature-flags/" + flagKey + "/evaluate";
        Request request = new Request.Builder()
                .url(url)
                .header("X-API-Key", config.getApiKey())
                .header("X-User-ID", user.getUserId())
                .get()
                .build();

        try (Response response = httpClient.newCall(request).execute()) {
            if (!response.isSuccessful()) {
                throw new ExperimentationException(
                        "API error evaluating flag '" + flagKey + "': HTTP " + response.code(),
                        response.code()
                );
            }
            ResponseBody body = response.body();
            if (body == null) {
                throw new ExperimentationException("Empty response body from API for flag: " + flagKey);
            }
            FeatureFlag flag = objectMapper.readValue(body.string(), FeatureFlag.class);
            String variant = evaluator.evaluate(user, flag);
            String result = (variant != null) ? variant : "off";
            cache.put(cacheKey, result);
            return result;
        } catch (IOException e) {
            throw new ExperimentationException("Network error evaluating flag '" + flagKey + "': " + e.getMessage(), e);
        }
    }

    /**
     * Retrieves an experiment assignment for a user.
     *
     * <p>Sends a {@code POST /api/v1/assignments} request with user ID and attributes.
     * The server performs consistent-hash-based assignment and returns the variant.
     *
     * @param user          the user to get the assignment for
     * @param experimentKey the experiment key (e.g., "checkout-button-color")
     * @return the experiment assignment (never null; check {@link ExperimentAssignment#isInExperiment()})
     * @throws ExperimentationException if the API returns an error or a network error occurs
     */
    public ExperimentAssignment getExperimentAssignment(User user, String experimentKey) {
        if (user == null) throw new IllegalArgumentException("user must not be null");
        if (experimentKey == null || experimentKey.isEmpty()) {
            throw new IllegalArgumentException("experimentKey must not be empty");
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("user_id", user.getUserId());
        payload.put("experiment_key", experimentKey);
        payload.put("attributes", user.getAttributes());

        String url = config.getBaseUrl() + "/api/v1/assignments";
        try {
            String bodyJson = objectMapper.writeValueAsString(payload);
            Request request = new Request.Builder()
                    .url(url)
                    .header("X-API-Key", config.getApiKey())
                    .post(RequestBody.create(bodyJson, JSON))
                    .build();

            try (Response response = httpClient.newCall(request).execute()) {
                if (!response.isSuccessful()) {
                    throw new ExperimentationException(
                            "API error getting assignment for experiment '" + experimentKey +
                            "': HTTP " + response.code(),
                            response.code()
                    );
                }
                ResponseBody body = response.body();
                if (body == null) {
                    throw new ExperimentationException(
                            "Empty response body for experiment: " + experimentKey);
                }
                return objectMapper.readValue(body.string(), ExperimentAssignment.class);
            }
        } catch (IOException e) {
            throw new ExperimentationException(
                    "Network error getting assignment for experiment '" + experimentKey + "': " + e.getMessage(), e);
        }
    }

    /**
     * Tracks a user event for analytics. This is a fire-and-forget operation.
     *
     * <p>Sends an async {@code POST /api/v1/events} request. Errors are silently ignored —
     * event tracking failures should never affect the user experience.
     *
     * @param userId     the user's unique identifier
     * @param eventName  the name of the event (e.g., "button_clicked", "purchase_completed")
     * @param properties optional map of event properties (may be null)
     */
    public void trackEvent(String userId, String eventName, Map<String, Object> properties) {
        if (userId == null || userId.isEmpty() || eventName == null || eventName.isEmpty()) {
            return; // silently ignore invalid inputs for fire-and-forget
        }

        try {
            Map<String, Object> payload = new HashMap<>();
            payload.put("user_id", userId);
            payload.put("event_name", eventName);
            if (properties != null) {
                payload.put("properties", properties);
            }

            String bodyJson = objectMapper.writeValueAsString(payload);
            Request request = new Request.Builder()
                    .url(config.getBaseUrl() + "/api/v1/events")
                    .header("X-API-Key", config.getApiKey())
                    .post(RequestBody.create(bodyJson, JSON))
                    .build();

            httpClient.newCall(request).enqueue(new Callback() {
                @Override
                public void onFailure(Call call, IOException e) {
                    // Fire and forget: swallow network errors silently
                }

                @Override
                public void onResponse(Call call, Response response) {
                    // Close response body to release resources
                    response.close();
                }
            });
        } catch (Exception ignored) {
            // Fire and forget: swallow serialization errors silently
        }
    }

    /**
     * Invalidates the cached result for a specific user + flag combination.
     *
     * <p>Useful when you know the flag configuration has changed and you want to force
     * a fresh API call on the next evaluation.
     *
     * @param userId  the user's ID
     * @param flagKey the feature flag key
     */
    public void invalidateCache(String userId, String flagKey) {
        cache.invalidate(userId + ":" + flagKey);
    }

    /**
     * Clears the entire assignment cache.
     */
    public void clearCache() {
        cache.clear();
    }

    /**
     * Returns the current number of entries in the assignment cache.
     *
     * @return cache size
     */
    public int getCacheSize() {
        return cache.size();
    }

    /**
     * Closes the client, releasing the HTTP connection pool and clearing the cache.
     *
     * <p>After calling this method, the client should not be used.
     */
    @Override
    public void close() {
        httpClient.dispatcher().executorService().shutdown();
        httpClient.connectionPool().evictAll();
        cache.clear();
    }
}
