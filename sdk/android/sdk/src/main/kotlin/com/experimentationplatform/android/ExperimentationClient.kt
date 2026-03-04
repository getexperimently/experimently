package com.experimentationplatform.android

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.locks.ReentrantReadWriteLock
import kotlin.concurrent.read
import kotlin.concurrent.write

/**
 * Main Experimentation Platform SDK client for Android.
 *
 * Provides:
 * - Feature flag evaluation with local caching and offline fallback
 * - Experiment assignment via API
 * - Event tracking (fire-and-forget)
 * - Bulk flag refresh
 *
 * All network operations use Kotlin Coroutines and run on Dispatchers.IO.
 * The client is thread-safe and suitable for use across multiple coroutines.
 *
 * Usage:
 * ```kotlin
 * val client = ExperimentationClient(
 *     SdkConfig(baseUrl = "https://api.example.com", apiKey = "your-key")
 * )
 * val result = client.evaluateFlag("new-dashboard", User("user-123"))
 * if (result.enabled) { showNewDashboard() }
 * ```
 */
class ExperimentationClient(
    private val config: SdkConfig,
    private val httpClient: HttpClient = HttpClient(config.baseUrl, config.apiKey, config.timeoutMs),
    private val cache: FlagCache = FlagCache(config.cacheSize, config.cacheTtlMs),
    private val offlineStore: OfflineStore = OfflineStore()
) {
    // Background scope for fire-and-forget operations (SupervisorJob: child failures don't cancel parent)
    private val backgroundScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val flagsLock = ReentrantReadWriteLock()
    private val localFlags = mutableMapOf<String, FeatureFlag>()

    /**
     * Evaluates a feature flag for the given user.
     *
     * Resolution order:
     *   1. In-memory LRU cache (fast path, ~O(1))
     *   2. Local flags map (populated by refreshFlags)
     *   3. API fetch with offline fallback on error
     *
     * @param flagKey the feature flag's unique key
     * @param user    the user to evaluate the flag for
     * @return EvalResult with enabled state, optional variant, and reason
     * @throws ExperimentationException.FlagNotFoundException if the flag doesn't exist anywhere
     * @throws ExperimentationException.NetworkException on irrecoverable network failure
     */
    suspend fun evaluateFlag(flagKey: String, user: User): EvalResult {
        // 1. Check in-memory cache (fastest path)
        cache.get(flagKey)?.let { flag ->
            return FeatureFlagEvaluator.evaluate(flag, user)
        }

        // 2. Check local flags map (populated by refreshFlags())
        val localFlag = flagsLock.read { localFlags[flagKey] }
        if (localFlag != null) {
            cache.set(flagKey, localFlag)
            return FeatureFlagEvaluator.evaluate(localFlag, user)
        }

        // 3. Fetch from API (may fall back to offline store on failure)
        val flag = fetchFlag(flagKey)
        cache.set(flagKey, flag)
        flagsLock.write { localFlags[flagKey] = flag }
        return FeatureFlagEvaluator.evaluate(flag, user)
    }

    /**
     * Gets a server-side experiment assignment for the given user.
     *
     * @param experimentKey unique key for the experiment
     * @param user          the user requesting assignment
     * @return Assignment containing experiment key, variant key, and user id
     * @throws ExperimentationException.ServerException on API error
     * @throws ExperimentationException.NetworkException on network failure
     */
    suspend fun getAssignment(experimentKey: String, user: User): Assignment {
        val body = JSONObject().apply {
            put("user_id", user.id)
            val attrsJson = JSONObject()
            user.attributes.forEach { (k, v) ->
                when (v) {
                    null -> attrsJson.put(k, JSONObject.NULL)
                    else -> attrsJson.put(k, v)
                }
            }
            put("attributes", attrsJson)
        }
        val response = httpClient.post("/api/v1/experiments/$experimentKey/assign", body)
        return Assignment.fromJson(response)
    }

    /**
     * Tracks a user event asynchronously. Fire-and-forget — does not throw on failure.
     *
     * @param event the event to track
     */
    suspend fun track(event: TrackEvent) {
        backgroundScope.launch {
            try {
                httpClient.post("/api/v1/events", event.toJson())
            } catch (e: Exception) {
                // Swallow errors — tracking must never crash the caller
            }
        }
    }

    /**
     * Refreshes all feature flags from the API and updates cache + offline store.
     *
     * Call this at app startup or periodically for proactive cache warming.
     *
     * @throws ExperimentationException.ServerException on API error
     * @throws ExperimentationException.NetworkException on network failure
     */
    suspend fun refreshFlags() {
        val response = httpClient.get("/api/v1/feature-flags")
        val flagsArray = response.optJSONArray("items") ?: JSONArray()
        val newFlags = mutableMapOf<String, FeatureFlag>()
        for (i in 0 until flagsArray.length()) {
            val flag = FeatureFlag.fromJson(flagsArray.getJSONObject(i))
            newFlags[flag.key] = flag
            cache.set(flag.key, flag)
            offlineStore.saveFlag(flag)
        }
        flagsLock.write {
            localFlags.clear()
            localFlags.putAll(newFlags)
        }
    }

    /**
     * Cleans up resources. Call when the client is no longer needed
     * (e.g., in Activity.onDestroy()).
     */
    fun close() {
        cache.clear()
    }

    /**
     * Returns a snapshot of all locally cached flag keys.
     */
    fun getCachedFlagKeys(): Set<String> = flagsLock.read { localFlags.keys.toSet() }

    // ---- Private helpers ----

    private suspend fun fetchFlag(flagKey: String): FeatureFlag {
        return try {
            val response = httpClient.get("/api/v1/feature-flags/$flagKey")
            FeatureFlag.fromJson(response).also { flag ->
                offlineStore.saveFlag(flag)
            }
        } catch (e: ExperimentationException.ServerException) {
            if (e.statusCode == 404) {
                // Try offline fallback before giving up
                offlineStore.loadFlag(flagKey)
                    ?: throw ExperimentationException.FlagNotFoundException(flagKey)
            } else {
                throw e
            }
        } catch (e: ExperimentationException) {
            // Network error — try offline fallback
            offlineStore.loadFlag(flagKey)
                ?: throw ExperimentationException.NetworkException(
                    "Failed to fetch flag '$flagKey' and no offline data available", e
                )
        }
    }
}
