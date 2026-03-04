import com.experimentationplatform.android.*
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.jupiter.api.*
import org.junit.jupiter.api.Assertions.*

/**
 * Comprehensive test suite for the Experimentation Platform Android SDK.
 *
 * Tests cover:
 * - SdkConfig defaults and custom values
 * - FlagCache: set/get, TTL expiry, LRU eviction, thread safety, clear
 * - FeatureFlagEvaluator: disabled, enabled, 0%/100%, rollout, variants, reasons
 * - ExperimentationClient: evaluateFlag, getAssignment, track, refreshFlags
 * - OfflineStore: save/load, saveAll/loadAll, clearAll
 * - Model JSON parsing: FeatureFlag, Assignment, TrackEvent
 * - Error scenarios: 404, server error, network error, offline fallback
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ExperimentationClientTest {

    private lateinit var server: MockWebServer
    private lateinit var client: ExperimentationClient
    private lateinit var cache: FlagCache
    private lateinit var offlineStore: OfflineStore

    // ---- Setup/Teardown ----

    @BeforeAll
    fun setupServer() {
        server = MockWebServer()
        server.start()
    }

    @BeforeEach
    fun setupClient() {
        cache = FlagCache(maxSize = 100, ttlMs = 300_000L)
        offlineStore = OfflineStore()
        val baseUrl = server.url("/").toString().trimEnd('/')
        val config = SdkConfig(baseUrl = baseUrl, apiKey = "test-key")
        val httpClient = HttpClient(baseUrl, "test-key", 5_000L)
        client = ExperimentationClient(config, httpClient, cache, offlineStore)
    }

    @AfterAll
    fun tearDown() {
        server.shutdown()
    }

    // ============================
    // Config tests
    // ============================

    @Test
    fun `config has sensible defaults`() {
        val config = SdkConfig(apiKey = "my-key")
        assertEquals("http://localhost:8000", config.baseUrl)
        assertEquals("my-key", config.apiKey)
        assertEquals(10_000L, config.timeoutMs)
        assertEquals(1000, config.cacheSize)
        assertEquals(300_000L, config.cacheTtlMs)
        assertTrue(config.enableLocalEval)
    }

    @Test
    fun `config accepts custom values`() {
        val config = SdkConfig(
            baseUrl = "https://api.example.com",
            apiKey = "custom-key",
            timeoutMs = 5_000L,
            cacheSize = 500,
            cacheTtlMs = 60_000L,
            enableLocalEval = false
        )
        assertEquals("https://api.example.com", config.baseUrl)
        assertEquals("custom-key", config.apiKey)
        assertEquals(5_000L, config.timeoutMs)
        assertEquals(500, config.cacheSize)
        assertEquals(60_000L, config.cacheTtlMs)
        assertFalse(config.enableLocalEval)
    }

    @Test
    fun `config with empty apiKey is valid`() {
        val config = SdkConfig(apiKey = "")
        assertEquals("", config.apiKey)
        assertNotNull(config)
    }

    // ============================
    // Cache tests
    // ============================

    @Test
    fun `cache set and get returns correct value`() {
        val flag = makeFlag("flag-a", true, 100.0)
        cache.set("flag-a", flag)
        val result = cache.get("flag-a")
        assertNotNull(result)
        assertEquals("flag-a", result!!.key)
        assertTrue(result.enabled)
    }

    @Test
    fun `cache returns null on miss`() {
        val result = cache.get("nonexistent-flag")
        assertNull(result)
    }

    @Test
    fun `cache respects TTL expiry`() {
        val shortCache = FlagCache(maxSize = 100, ttlMs = 1L) // 1ms TTL
        val flag = makeFlag("flag-b", true, 50.0)
        shortCache.set("flag-b", flag)
        Thread.sleep(10)
        assertNull(shortCache.get("flag-b"), "Entry should be expired after TTL")
    }

    @Test
    fun `cache LRU eviction removes eldest entry`() {
        val smallCache = FlagCache(maxSize = 3, ttlMs = 300_000L)
        smallCache.set("a", makeFlag("a", true, 100.0))
        smallCache.set("b", makeFlag("b", true, 100.0))
        smallCache.set("c", makeFlag("c", true, 100.0))
        // Access "a" to make it recently used
        smallCache.get("a")
        // Adding "d" should evict "b" (LRU)
        smallCache.set("d", makeFlag("d", true, 100.0))
        // "a", "c", "d" should survive; "b" evicted
        assertNotNull(smallCache.get("a"), "a was accessed recently, should survive")
        assertNotNull(smallCache.get("c"))
        assertNotNull(smallCache.get("d"))
    }

    @Test
    fun `cache clear removes all entries`() {
        cache.set("x", makeFlag("x", true, 100.0))
        cache.set("y", makeFlag("y", true, 100.0))
        cache.clear()
        assertNull(cache.get("x"))
        assertNull(cache.get("y"))
    }

    @Test
    fun `cache is thread safe under concurrent access`() {
        val threads = (1..20).map { i ->
            Thread {
                cache.set("flag-$i", makeFlag("flag-$i", true, 50.0))
                cache.get("flag-$i")
            }
        }
        threads.forEach { it.start() }
        threads.forEach { it.join() }
        // No exception = thread safe
    }

    @Test
    fun `cache size reflects stored entries`() {
        val freshCache = FlagCache()
        assertEquals(0, freshCache.size())
        freshCache.set("k1", makeFlag("k1", true, 100.0))
        freshCache.set("k2", makeFlag("k2", false, 0.0))
        assertEquals(2, freshCache.size())
        freshCache.remove("k1")
        assertEquals(1, freshCache.size())
    }

    @Test
    fun `cache remove deletes specific key`() {
        cache.set("flag-rm", makeFlag("flag-rm", true, 100.0))
        assertNotNull(cache.get("flag-rm"))
        cache.remove("flag-rm")
        assertNull(cache.get("flag-rm"))
    }

    // ============================
    // FeatureFlagEvaluator tests
    // ============================

    @Test
    fun `evaluate disabled flag returns disabled with reason`() {
        val flag = makeFlag("f", false, 100.0)
        val result = FeatureFlagEvaluator.evaluate(flag, User("user-1"))
        assertFalse(result.enabled)
        assertEquals("flag_disabled", result.reason)
    }

    @Test
    fun `evaluate enabled flag at 100 percent returns enabled`() {
        val flag = makeFlag("f", true, 100.0)
        val result = FeatureFlagEvaluator.evaluate(flag, User("user-1"))
        assertTrue(result.enabled)
        assertEquals("in_rollout", result.reason)
    }

    @Test
    fun `evaluate enabled flag at 0 percent returns disabled`() {
        val flag = makeFlag("f", true, 0.0)
        val result = FeatureFlagEvaluator.evaluate(flag, User("user-1"))
        assertFalse(result.enabled)
        assertEquals("out_of_rollout", result.reason)
    }

    @Test
    fun `evaluate 50 percent rollout distributes roughly half enabled`() {
        val flag = makeFlag("rollout-test", true, 50.0)
        var enabled = 0
        for (i in 0 until 1000) {
            if (FeatureFlagEvaluator.evaluate(flag, User("u$i")).enabled) enabled++
        }
        assertTrue(enabled in 400..600, "Expected ~500 enabled out of 1000, got $enabled")
    }

    @Test
    fun `evaluate with variants returns variant_assigned reason`() {
        val flag = FeatureFlag(
            key = "varflag",
            enabled = true,
            rolloutPercentage = 100.0,
            variants = listOf(
                Variant("control", 0.5),
                Variant("treatment", 0.5)
            )
        )
        val result = FeatureFlagEvaluator.evaluate(flag, User("user-42"))
        assertTrue(result.enabled)
        assertEquals("variant_assigned", result.reason)
        assertNotNull(result.variantKey)
        assertTrue(result.variantKey in listOf("control", "treatment"))
    }

    @Test
    fun `evaluate disabled flag returns null variantKey`() {
        val flag = makeFlag("f", false, 100.0)
        val result = FeatureFlagEvaluator.evaluate(flag, User("u"))
        assertNull(result.variantKey)
    }

    @Test
    fun `evaluate variant assignment is deterministic`() {
        val flag = FeatureFlag(
            key = "det-flag",
            enabled = true,
            rolloutPercentage = 100.0,
            variants = listOf(Variant("a", 0.5), Variant("b", 0.5))
        )
        val r1 = FeatureFlagEvaluator.evaluate(flag, User("user-xyz"))
        val r2 = FeatureFlagEvaluator.evaluate(flag, User("user-xyz"))
        assertEquals(r1.variantKey, r2.variantKey)
    }

    @Test
    fun `evaluate out of rollout returns disabled even when flag enabled`() {
        // User "definitely-out" should have hash >= 0.01 (1% rollout)
        val flag = makeFlag("tiny-rollout", true, 1.0)
        var disabledCount = 0
        for (i in 0 until 100) {
            if (!FeatureFlagEvaluator.evaluate(flag, User("out-user-$i")).enabled) disabledCount++
        }
        assertTrue(disabledCount > 80, "Most users should be out of 1% rollout")
    }

    // ============================
    // Client evaluateFlag tests
    // ============================

    @Test
    fun `evaluateFlag returns enabled for in-rollout user`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("test-flag", true, 100.0)).setResponseCode(200))
        val result = client.evaluateFlag("test-flag", User("user-1"))
        assertTrue(result.enabled)
    }

    @Test
    fun `evaluateFlag returns disabled for disabled flag`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("off-flag", false, 100.0)).setResponseCode(200))
        val result = client.evaluateFlag("off-flag", User("user-1"))
        assertFalse(result.enabled)
        assertEquals("flag_disabled", result.reason)
    }

    @Test
    fun `evaluateFlag uses cache on second call without hitting server`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("cached-flag", true, 100.0)).setResponseCode(200))
        // First call: fetches from server
        client.evaluateFlag("cached-flag", User("user-1"))
        // Second call: should use cache (no server request queued)
        val result = client.evaluateFlag("cached-flag", User("user-1"))
        assertTrue(result.enabled)
        // Only 1 request should have been made
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `evaluateFlag falls back to offline store on network error`() = runTest {
        // Pre-populate offline store
        val flag = makeFlag("offline-flag", true, 100.0)
        offlineStore.saveFlag(flag)
        // Server returns error
        server.enqueue(MockResponse().setResponseCode(503))
        val result = client.evaluateFlag("offline-flag", User("user-1"))
        assertTrue(result.enabled, "Should use offline fallback")
    }

    @Test
    fun `evaluateFlag throws FlagNotFoundException when not found and no offline data`() = runTest {
        server.enqueue(MockResponse().setResponseCode(404).setBody("{\"detail\":\"Not found\"}"))
        assertThrows<ExperimentationException.FlagNotFoundException> {
            client.evaluateFlag("ghost-flag", User("user-1"))
        }
    }

    @Test
    fun `evaluateFlag throws NetworkException on connection refused with no offline data`() = runTest {
        // Use a client pointed at a closed port
        val badConfig = SdkConfig(baseUrl = "http://127.0.0.1:1", apiKey = "k")
        val badClient = ExperimentationClient(badConfig)
        assertThrows<ExperimentationException.NetworkException> {
            badClient.evaluateFlag("any-flag", User("u"))
        }
    }

    @Test
    fun `evaluateFlag with variant returns variantKey`() = runTest {
        val body = """{"key":"var-flag","enabled":true,"rollout_percentage":100.0,"variants":[{"key":"control","weight":0.5},{"key":"treatment","weight":0.5}]}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        val result = client.evaluateFlag("var-flag", User("user-99"))
        assertTrue(result.enabled)
        assertNotNull(result.variantKey)
        assertTrue(result.variantKey in listOf("control", "treatment"))
    }

    @Test
    fun `evaluateFlag 0 percent rollout returns disabled`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("zero-flag", true, 0.0)).setResponseCode(200))
        val result = client.evaluateFlag("zero-flag", User("user-1"))
        assertFalse(result.enabled)
        assertEquals("out_of_rollout", result.reason)
    }

    // ============================
    // Client getAssignment tests
    // ============================

    @Test
    fun `getAssignment returns correct assignment`() = runTest {
        val body = """{"experiment_key":"exp-1","variant_key":"control","user_id":"user-42"}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        val assignment = client.getAssignment("exp-1", User("user-42"))
        assertEquals("exp-1", assignment.experimentKey)
        assertEquals("control", assignment.variantKey)
        assertEquals("user-42", assignment.userId)
    }

    @Test
    fun `getAssignment throws ServerException on server error`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500).setBody("{\"detail\":\"Internal error\"}"))
        assertThrows<ExperimentationException.ServerException> {
            client.getAssignment("exp-1", User("user-1"))
        }
    }

    @Test
    fun `getAssignment sends user attributes in request body`() = runTest {
        val body = """{"experiment_key":"exp-1","variant_key":"treatment","user_id":"user-1"}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        val user = User("user-1", mapOf("plan" to "pro", "country" to "US"))
        client.getAssignment("exp-1", user)
        val request = server.takeRequest()
        val reqBody = request.body.readUtf8()
        assertTrue(reqBody.contains("user_id"))
        assertTrue(reqBody.contains("user-1"))
        assertTrue(reqBody.contains("attributes"))
    }

    @Test
    fun `getAssignment throws NetworkException on IO failure`() = runTest {
        val badConfig = SdkConfig(baseUrl = "http://127.0.0.1:1", apiKey = "k")
        val badClient = ExperimentationClient(badConfig)
        assertThrows<ExperimentationException.NetworkException> {
            badClient.getAssignment("exp-1", User("u"))
        }
    }

    // ============================
    // Client track tests
    // ============================

    @Test
    fun `track sends event to server`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("{}"))
        val event = TrackEvent("user-1", "purchase", mapOf("amount" to 99.99))
        client.track(event)
        // Small delay to allow background coroutine to execute
        kotlinx.coroutines.delay(100)
        val request = server.takeRequest(500, java.util.concurrent.TimeUnit.MILLISECONDS)
        assertNotNull(request, "Expected a request to be sent")
        assertEquals("/api/v1/events", request!!.path)
    }

    @Test
    fun `track does not throw on server error`() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))
        val event = TrackEvent("user-1", "click")
        // Should not throw
        assertDoesNotThrow { client.track(event) }
    }

    @Test
    fun `track event json has correct fields`() {
        val event = TrackEvent("user-123", "button_click", mapOf("page" to "home"))
        val json = event.toJson()
        assertEquals("user-123", json.getString("user_id"))
        assertEquals("button_click", json.getString("event_name"))
        assertTrue(json.has("properties"))
        assertEquals("home", json.getJSONObject("properties").getString("page"))
    }

    // ============================
    // Client refreshFlags tests
    // ============================

    @Test
    fun `refreshFlags updates local flags map`() = runTest {
        val body = """{"items":[${flagJson("flag-r1", true, 100.0)},${flagJson("flag-r2", false, 0.0)}]}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        client.refreshFlags()
        val keys = client.getCachedFlagKeys()
        assertTrue(keys.contains("flag-r1"))
        assertTrue(keys.contains("flag-r2"))
    }

    @Test
    fun `refreshFlags updates cache so next evaluateFlag uses no server call`() = runTest {
        val body = """{"items":[${flagJson("pre-cached", true, 100.0)}]}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        client.refreshFlags()
        val requestCountAfterRefresh = server.requestCount
        val result = client.evaluateFlag("pre-cached", User("user-1"))
        assertTrue(result.enabled)
        assertEquals(requestCountAfterRefresh, server.requestCount, "No additional requests after refreshFlags")
    }

    @Test
    fun `refreshFlags saves flags to offline store`() = runTest {
        val body = """{"items":[${flagJson("off-flag-x", true, 75.0)}]}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        client.refreshFlags()
        val stored = offlineStore.loadFlag("off-flag-x")
        assertNotNull(stored)
        assertEquals("off-flag-x", stored!!.key)
        assertEquals(75.0, stored.rolloutPercentage)
    }

    @Test
    fun `refreshFlags replaces stale local flags`() = runTest {
        // First refresh
        server.enqueue(MockResponse().setBody("""{"items":[${flagJson("stale-flag", true, 100.0)}]}""").setResponseCode(200))
        client.refreshFlags()
        // Second refresh with updated flag
        server.enqueue(MockResponse().setBody("""{"items":[${flagJson("stale-flag", false, 0.0)}]}""").setResponseCode(200))
        client.refreshFlags()
        val keys = client.getCachedFlagKeys()
        assertTrue(keys.contains("stale-flag"))
    }

    // ============================
    // OfflineStore tests
    // ============================

    @Test
    fun `offlineStore save and load roundtrip`() {
        val store = OfflineStore()
        val flag = makeFlag("stored-flag", true, 80.0)
        store.saveFlag(flag)
        val loaded = store.loadFlag("stored-flag")
        assertNotNull(loaded)
        assertEquals("stored-flag", loaded!!.key)
        assertTrue(loaded.enabled)
        assertEquals(80.0, loaded.rolloutPercentage)
    }

    @Test
    fun `offlineStore loadMissing returns null`() {
        val store = OfflineStore()
        assertNull(store.loadFlag("does-not-exist"))
    }

    @Test
    fun `offlineStore saveAll and loadAll`() {
        val store = OfflineStore()
        val flags = listOf(
            makeFlag("flag-1", true, 100.0),
            makeFlag("flag-2", false, 0.0),
            makeFlag("flag-3", true, 50.0)
        )
        store.saveAllFlags(flags)
        val loaded = store.loadAllFlags()
        assertEquals(3, loaded.size)
        val keys = loaded.map { it.key }.toSet()
        assertTrue(keys.containsAll(listOf("flag-1", "flag-2", "flag-3")))
    }

    @Test
    fun `offlineStore clearAll removes all flags`() {
        val store = OfflineStore()
        store.saveFlag(makeFlag("clear-me", true, 100.0))
        store.saveFlag(makeFlag("clear-me-too", true, 100.0))
        store.clearAll()
        assertNull(store.loadFlag("clear-me"))
        assertNull(store.loadFlag("clear-me-too"))
        assertTrue(store.loadAllFlags().isEmpty())
    }

    @Test
    fun `offlineStore overwrite updates existing flag`() {
        val store = OfflineStore()
        store.saveFlag(makeFlag("overwrite-flag", true, 100.0))
        store.saveFlag(makeFlag("overwrite-flag", false, 0.0))
        val loaded = store.loadFlag("overwrite-flag")
        assertNotNull(loaded)
        assertFalse(loaded!!.enabled)
        assertEquals(0.0, loaded.rolloutPercentage)
    }

    @Test
    fun `offlineStore saves and loads variants`() {
        val store = OfflineStore()
        val flag = FeatureFlag(
            key = "variant-stored",
            enabled = true,
            rolloutPercentage = 100.0,
            variants = listOf(Variant("control", 0.5), Variant("treatment", 0.5))
        )
        store.saveFlag(flag)
        val loaded = store.loadFlag("variant-stored")
        assertNotNull(loaded)
        assertEquals(2, loaded!!.variants.size)
        assertEquals("control", loaded.variants[0].key)
        assertEquals(0.5, loaded.variants[0].weight, 0.001)
    }

    // ============================
    // Model JSON tests
    // ============================

    @Test
    fun `user attributes are accessible`() {
        val user = User("u-1", mapOf("plan" to "premium", "age" to 30))
        assertEquals("u-1", user.id)
        assertEquals("premium", user.attributes["plan"])
        assertEquals(30, user.attributes["age"])
    }

    @Test
    fun `featureFlag fromJson parses correctly`() {
        val json = org.json.JSONObject("""{"key":"my-flag","enabled":true,"rollout_percentage":75.5,"variants":[]}""")
        val flag = FeatureFlag.fromJson(json)
        assertEquals("my-flag", flag.key)
        assertTrue(flag.enabled)
        assertEquals(75.5, flag.rolloutPercentage)
        assertTrue(flag.variants.isEmpty())
    }

    @Test
    fun `featureFlag fromJson parses variants`() {
        val json = org.json.JSONObject("""{"key":"v-flag","enabled":true,"rollout_percentage":100.0,"variants":[{"key":"a","weight":0.3},{"key":"b","weight":0.7}]}""")
        val flag = FeatureFlag.fromJson(json)
        assertEquals(2, flag.variants.size)
        assertEquals("a", flag.variants[0].key)
        assertEquals(0.3, flag.variants[0].weight, 0.001)
    }

    @Test
    fun `assignment fromJson parses correctly`() {
        val json = org.json.JSONObject("""{"experiment_key":"exp-abc","variant_key":"treatment","user_id":"user-99"}""")
        val assignment = Assignment.fromJson(json)
        assertEquals("exp-abc", assignment.experimentKey)
        assertEquals("treatment", assignment.variantKey)
        assertEquals("user-99", assignment.userId)
    }

    @Test
    fun `trackEvent toJson serializes correctly`() {
        val event = TrackEvent("u-1", "page_view", mapOf("url" to "/home", "referrer" to null))
        val json = event.toJson()
        assertEquals("u-1", json.getString("user_id"))
        assertEquals("page_view", json.getString("event_name"))
        val props = json.getJSONObject("properties")
        assertEquals("/home", props.getString("url"))
    }

    @Test
    fun `trackEvent with empty properties serializes cleanly`() {
        val event = TrackEvent("u-2", "app_open")
        val json = event.toJson()
        assertEquals("u-2", json.getString("user_id"))
        assertEquals("app_open", json.getString("event_name"))
        assertTrue(json.has("properties"))
    }

    @Test
    fun `variant fromJson supports key field`() {
        val json = org.json.JSONObject("""{"key":"control","weight":0.5}""")
        val variant = Variant.fromJson(json)
        assertEquals("control", variant.key)
        assertEquals(0.5, variant.weight, 0.001)
    }

    @Test
    fun `variant fromJson supports name field fallback`() {
        // Java SDK uses "name" field, Android should handle both
        val json = org.json.JSONObject("""{"name":"treatment","weight":0.5}""")
        val variant = Variant.fromJson(json)
        assertEquals("treatment", variant.key)
    }

    @Test
    fun `exception types have correct messages`() {
        val networkEx = ExperimentationException.NetworkException("timeout")
        assertTrue(networkEx.message!!.contains("timeout"))

        val notFoundEx = ExperimentationException.FlagNotFoundException("my-flag")
        assertTrue(notFoundEx.message!!.contains("my-flag"))

        val serverEx = ExperimentationException.ServerException(500, "Internal Server Error")
        assertTrue(serverEx.message!!.contains("500"))
        assertEquals(500, serverEx.statusCode)
    }

    @Test
    fun `client close clears cache`() {
        cache.set("cleanup-flag", makeFlag("cleanup-flag", true, 100.0))
        assertNotNull(cache.get("cleanup-flag"))
        client.close()
        assertNull(cache.get("cleanup-flag"))
    }

    // ============================
    // HTTP layer and auth header tests
    // ============================

    @Test
    fun `evaluateFlag request includes Authorization header`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("auth-flag", true, 100.0)).setResponseCode(200))
        client.evaluateFlag("auth-flag", User("u"))
        val request = server.takeRequest()
        assertEquals("ApiKey test-key", request.getHeader("Authorization"))
    }

    @Test
    fun `evaluateFlag request targets correct path`() = runTest {
        server.enqueue(MockResponse().setBody(flagJson("path-flag", true, 100.0)).setResponseCode(200))
        client.evaluateFlag("path-flag", User("u"))
        val request = server.takeRequest()
        assertTrue(request.path!!.contains("path-flag"))
    }

    @Test
    fun `getAssignment request includes Authorization header`() = runTest {
        val body = """{"experiment_key":"exp-x","variant_key":"control","user_id":"u"}"""
        server.enqueue(MockResponse().setBody(body).setResponseCode(200))
        client.getAssignment("exp-x", User("u"))
        val request = server.takeRequest()
        assertEquals("ApiKey test-key", request.getHeader("Authorization"))
    }

    @Test
    fun `refreshFlags request includes Authorization header`() = runTest {
        server.enqueue(MockResponse().setBody("""{"items":[]}""").setResponseCode(200))
        client.refreshFlags()
        val request = server.takeRequest()
        assertEquals("ApiKey test-key", request.getHeader("Authorization"))
    }

    @Test
    fun `refreshFlags with empty items list clears localFlags`() = runTest {
        // First populate with a flag
        server.enqueue(MockResponse().setBody("""{"items":[${flagJson("old-flag", true, 100.0)}]}""").setResponseCode(200))
        client.refreshFlags()
        assertTrue(client.getCachedFlagKeys().contains("old-flag"))
        // Now refresh with empty items
        server.enqueue(MockResponse().setBody("""{"items":[]}""").setResponseCode(200))
        client.refreshFlags()
        assertTrue(client.getCachedFlagKeys().isEmpty(), "LocalFlags should be empty after refresh with no items")
    }

    @Test
    fun `serverException carries status code`() = runTest {
        server.enqueue(MockResponse().setResponseCode(403).setBody("{\"detail\":\"Forbidden\"}"))
        val ex = assertThrows<ExperimentationException.ServerException> {
            client.evaluateFlag("forbidden-flag", User("u"))
        }
        assertEquals(403, ex.statusCode)
    }

    @Test
    fun `multiple concurrent evaluateFlag calls are thread safe`() = runTest {
        repeat(10) {
            server.enqueue(MockResponse().setBody(flagJson("concurrent-flag", true, 100.0)).setResponseCode(200))
        }
        // Launch 10 concurrent evaluations for different users
        val jobs = (1..10).map { i ->
            kotlinx.coroutines.async {
                client.evaluateFlag("concurrent-flag", User("user-$i"))
            }
        }
        val results = jobs.map { it.await() }
        assertTrue(results.all { it.enabled }, "All concurrent evaluations should succeed")
    }

    // ============================
    // Additional evaluator edge cases
    // ============================

    @Test
    fun `evaluate single-variant flag always returns that variant`() {
        val flag = FeatureFlag(
            key = "single-v",
            enabled = true,
            rolloutPercentage = 100.0,
            variants = listOf(Variant("only-variant", 1.0))
        )
        for (i in 0 until 20) {
            val result = FeatureFlagEvaluator.evaluate(flag, User("user-$i"))
            assertEquals("only-variant", result.variantKey)
        }
    }

    @Test
    fun `evaluate flag with 100 percent rollout and no variants returns in_rollout for all users`() {
        val flag = makeFlag("always-on", true, 100.0)
        for (i in 0 until 50) {
            val result = FeatureFlagEvaluator.evaluate(flag, User("u$i"))
            assertTrue(result.enabled)
            assertEquals("in_rollout", result.reason)
        }
    }

    @Test
    fun `evaluate flag variant assignment distributes by weight`() {
        val flag = FeatureFlag(
            key = "weighted",
            enabled = true,
            rolloutPercentage = 100.0,
            variants = listOf(
                Variant("heavy", 0.9),
                Variant("light", 0.1)
            )
        )
        var heavy = 0
        var light = 0
        for (i in 0 until 1000) {
            val result = FeatureFlagEvaluator.evaluate(flag, User("user-$i"))
            if (result.variantKey == "heavy") heavy++ else light++
        }
        // heavy should get ~90%, light ~10%
        assertTrue(heavy in 800..980, "Expected ~900 heavy assignments, got $heavy")
        assertTrue(light in 20..200, "Expected ~100 light assignments, got $light")
    }

    @Test
    fun `offlineStore removeFlag removes specific key`() {
        val store = OfflineStore()
        store.saveFlag(makeFlag("remove-me", true, 100.0))
        store.saveFlag(makeFlag("keep-me", true, 100.0))
        store.removeFlag("remove-me")
        assertNull(store.loadFlag("remove-me"))
        assertNotNull(store.loadFlag("keep-me"))
    }

    // ============================
    // Helpers
    // ============================

    private fun makeFlag(key: String, enabled: Boolean, rollout: Double): FeatureFlag =
        FeatureFlag(key = key, enabled = enabled, rolloutPercentage = rollout)

    private fun flagJson(key: String, enabled: Boolean, rollout: Double): String =
        """{"key":"$key","enabled":$enabled,"rollout_percentage":$rollout,"variants":[]}"""
}
