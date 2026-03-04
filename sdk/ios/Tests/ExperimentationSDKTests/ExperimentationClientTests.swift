import XCTest
@testable import ExperimentationSDK

// MARK: - Mock URLProtocol

/// URLProtocol subclass that intercepts all URLSession requests during tests.
/// Set `MockURLProtocol.mockData` and `MockURLProtocol.mockStatusCode` before each test.
final class MockURLProtocol: URLProtocol {
    static var mockData: Data?
    static var mockStatusCode: Int = 200
    static var mockError: Error?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        if let error = MockURLProtocol.mockError {
            client?.urlProtocol(self, didFailWithError: error)
            return
        }

        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: MockURLProtocol.mockStatusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: MockURLProtocol.mockData ?? Data())
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

// MARK: - ExperimentationClientTests

final class ExperimentationClientTests: XCTestCase {

    // MARK: - Helpers

    /// Returns a URLSession configured to use MockURLProtocol.
    private func makeMockSession(responseData: Data, statusCode: Int = 200) -> URLSession {
        MockURLProtocol.mockData = responseData
        MockURLProtocol.mockStatusCode = statusCode
        MockURLProtocol.mockError = nil

        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        return URLSession(configuration: config)
    }

    private func makeClient(responseData: Data, statusCode: Int = 200) -> ExperimentationClient {
        let session = makeMockSession(responseData: responseData, statusCode: statusCode)
        let sdkConfig = SdkConfig(baseURL: "http://localhost:8000", apiKey: "test-key")
        let client = ExperimentationClient(config: sdkConfig)
        client.http = HTTPClient(
            baseURL: "http://localhost:8000",
            apiKey: "test-key",
            session: session
        )
        return client
    }

    private func makeFlag(
        key: String = "test-flag",
        enabled: Bool = true,
        rollout: Double = 100.0,
        variants: [Variant]? = nil
    ) -> FeatureFlag {
        FeatureFlag(key: key, enabled: enabled, rolloutPercentage: rollout, variants: variants)
    }

    private func encodeFlag(_ flag: FeatureFlag) -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return (try? encoder.encode(flag)) ?? Data()
    }

    private func encodeFlags(_ flags: [FeatureFlag]) -> Data {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return (try? encoder.encode(flags)) ?? Data()
    }

    private func makeUser(id: String = "user-abc") -> User {
        User(id: id)
    }

    override func setUp() {
        super.setUp()
        MockURLProtocol.mockData = nil
        MockURLProtocol.mockStatusCode = 200
        MockURLProtocol.mockError = nil
    }

    // MARK: - SdkConfig Tests

    func testSdkConfig_defaults() {
        let config = SdkConfig(apiKey: "my-key")
        XCTAssertEqual(config.baseURL, "http://localhost:8000")
        XCTAssertEqual(config.apiKey, "my-key")
        XCTAssertEqual(config.timeout, 10.0)
        XCTAssertEqual(config.cacheSize, 1000)
        XCTAssertEqual(config.cacheTTL, 300.0)
        XCTAssertTrue(config.enableLocalEval)
    }

    func testSdkConfig_customValues() {
        let config = SdkConfig(
            baseURL: "https://api.example.com",
            apiKey: "prod-key",
            timeout: 30.0,
            cacheSize: 500,
            cacheTTL: 60.0,
            enableLocalEval: false
        )
        XCTAssertEqual(config.baseURL, "https://api.example.com")
        XCTAssertEqual(config.apiKey, "prod-key")
        XCTAssertEqual(config.timeout, 30.0)
        XCTAssertEqual(config.cacheSize, 500)
        XCTAssertEqual(config.cacheTTL, 60.0)
        XCTAssertFalse(config.enableLocalEval)
    }

    // MARK: - FlagCache Tests

    func testFlagCache_setAndGet() {
        let cache = FlagCache(ttl: 300)
        let flag = makeFlag(key: "flag-1")
        cache.set("flag-1", flag: flag)
        let retrieved = cache.get("flag-1")
        XCTAssertNotNil(retrieved)
        XCTAssertEqual(retrieved?.key, "flag-1")
    }

    func testFlagCache_expiry() {
        let cache = FlagCache(ttl: 0.001) // 1 ms TTL
        let flag = makeFlag(key: "short-lived")
        cache.set("short-lived", flag: flag)
        Thread.sleep(forTimeInterval: 0.05) // wait 50 ms
        XCTAssertNil(cache.get("short-lived"), "Expired entry should return nil")
    }

    func testFlagCache_removeAll() {
        let cache = FlagCache(ttl: 300)
        cache.set("a", flag: makeFlag(key: "a"))
        cache.set("b", flag: makeFlag(key: "b"))
        cache.removeAll()
        XCTAssertNil(cache.get("a"))
        XCTAssertNil(cache.get("b"))
        XCTAssertEqual(cache.count, 0)
    }

    func testFlagCache_missReturnsNil() {
        let cache = FlagCache(ttl: 300)
        XCTAssertNil(cache.get("nonexistent-flag"))
    }

    func testFlagCache_overwrite() {
        let cache = FlagCache(ttl: 300)
        cache.set("flag", flag: makeFlag(key: "flag", enabled: true))
        cache.set("flag", flag: makeFlag(key: "flag", enabled: false))
        XCTAssertEqual(cache.get("flag")?.enabled, false)
    }

    // MARK: - FeatureFlagEvaluator Tests

    func testEvaluate_flagDisabled() {
        let flag = makeFlag(enabled: false)
        let user = makeUser()
        let result = FeatureFlagEvaluator.evaluate(flag, user: user)
        XCTAssertFalse(result.enabled)
        XCTAssertNil(result.variantKey)
        XCTAssertEqual(result.reason, "flag_disabled")
    }

    func testEvaluate_100PercentRollout() {
        let flag = makeFlag(enabled: true, rollout: 100.0)
        // user-0: hash ≈ 0.83 > 0, but < 1.0, so all users should be enabled
        for i in 0..<20 {
            let user = User(id: "user-\(i)")
            let result = FeatureFlagEvaluator.evaluate(flag, user: user)
            XCTAssertTrue(result.enabled, "user-\(i) should be enabled at 100% rollout")
        }
    }

    func testEvaluate_0PercentRollout() {
        let flag = makeFlag(enabled: true, rollout: 0.0)
        for i in 0..<20 {
            let user = User(id: "user-\(i)")
            let result = FeatureFlagEvaluator.evaluate(flag, user: user)
            XCTAssertFalse(result.enabled, "user-\(i) should be disabled at 0% rollout")
        }
    }

    func testEvaluate_50PercentRollout_distribution() {
        // At 50% rollout with users 0-999, roughly half should be enabled.
        let flag = makeFlag(key: "my-flag", enabled: true, rollout: 50.0)
        var enabledCount = 0
        for i in 0..<1000 {
            let user = User(id: "user-\(i)")
            if FeatureFlagEvaluator.evaluate(flag, user: user).enabled {
                enabledCount += 1
            }
        }
        // Expect 500 ± 60 (±6%)
        XCTAssertGreaterThan(enabledCount, 440, "Too few enabled at 50%: \(enabledCount)/1000")
        XCTAssertLessThan(enabledCount, 560, "Too many enabled at 50%: \(enabledCount)/1000")
    }

    func testEvaluate_withVariants() {
        let variants = [
            Variant(key: "control", weight: 0.5, value: nil),
            Variant(key: "treatment", weight: 0.5, value: nil)
        ]
        let flag = makeFlag(enabled: true, rollout: 100.0, variants: variants)
        var controlCount = 0
        var treatmentCount = 0

        for i in 0..<1000 {
            let user = User(id: "user-\(i)")
            let result = FeatureFlagEvaluator.evaluate(flag, user: user)
            XCTAssertTrue(result.enabled)
            XCTAssertEqual(result.reason, "variant_assigned")
            if result.variantKey == "control" { controlCount += 1 }
            if result.variantKey == "treatment" { treatmentCount += 1 }
        }

        // Both variants should receive roughly equal assignment (50% ± 8%)
        XCTAssertGreaterThan(controlCount, 420, "Control variant assigned too rarely")
        XCTAssertLessThan(controlCount, 580, "Control variant assigned too often")
        XCTAssertEqual(controlCount + treatmentCount, 1000, "Every user must be assigned a variant")
    }

    func testEvaluate_withVariants_singleVariant() {
        let variants = [Variant(key: "solo", weight: 1.0, value: nil)]
        let flag = makeFlag(enabled: true, rollout: 100.0, variants: variants)
        let result = FeatureFlagEvaluator.evaluate(flag, user: makeUser())
        XCTAssertTrue(result.enabled)
        XCTAssertEqual(result.variantKey, "solo")
    }

    func testEvaluate_reason_inRollout() {
        let flag = makeFlag(enabled: true, rollout: 100.0)
        let result = FeatureFlagEvaluator.evaluate(flag, user: makeUser())
        XCTAssertEqual(result.reason, "in_rollout")
    }

    func testEvaluate_reason_outOfRollout() {
        let flag = makeFlag(enabled: true, rollout: 0.0)
        let result = FeatureFlagEvaluator.evaluate(flag, user: makeUser())
        XCTAssertEqual(result.reason, "out_of_rollout")
    }

    // MARK: - OfflineStore Tests

    func testOfflineStore_saveAndLoad() {
        let store = OfflineStore(suiteName: nil, keyPrefix: "test_ep_\(UUID().uuidString)_")
        defer { store.clearAll() }

        let flag = makeFlag(key: "offline-flag", enabled: true, rollout: 75.0)
        store.saveFlag(flag)

        let loaded = store.loadFlag("offline-flag")
        XCTAssertNotNil(loaded)
        XCTAssertEqual(loaded?.key, "offline-flag")
        XCTAssertEqual(loaded?.enabled, true)
        XCTAssertEqual(loaded?.rolloutPercentage, 75.0)
    }

    func testOfflineStore_loadMissing() {
        let store = OfflineStore(suiteName: nil, keyPrefix: "test_ep_\(UUID().uuidString)_")
        XCTAssertNil(store.loadFlag("does-not-exist"))
    }

    func testOfflineStore_saveAllAndLoadAll() {
        let store = OfflineStore(suiteName: nil, keyPrefix: "test_ep_\(UUID().uuidString)_")
        defer { store.clearAll() }

        let flags = [
            makeFlag(key: "flag-a", enabled: true, rollout: 100.0),
            makeFlag(key: "flag-b", enabled: false, rollout: 0.0),
            makeFlag(key: "flag-c", enabled: true, rollout: 50.0),
        ]
        store.saveAllFlags(flags)

        let loaded = store.loadAllFlags()
        XCTAssertEqual(loaded.count, 3)
        let keys = loaded.map { $0.key }.sorted()
        XCTAssertEqual(keys, ["flag-a", "flag-b", "flag-c"])
    }

    func testOfflineStore_clearAll() {
        let store = OfflineStore(suiteName: nil, keyPrefix: "test_ep_\(UUID().uuidString)_")
        store.saveFlag(makeFlag(key: "temp-flag"))
        store.clearAll()
        XCTAssertNil(store.loadFlag("temp-flag"))
        XCTAssertEqual(store.loadAllFlags().count, 0)
    }

    func testOfflineStore_overwriteExistingFlag() {
        let store = OfflineStore(suiteName: nil, keyPrefix: "test_ep_\(UUID().uuidString)_")
        defer { store.clearAll() }

        store.saveFlag(makeFlag(key: "updatable", enabled: true, rollout: 10.0))
        store.saveFlag(makeFlag(key: "updatable", enabled: false, rollout: 0.0))

        let loaded = store.loadFlag("updatable")
        XCTAssertEqual(loaded?.enabled, false)
        XCTAssertEqual(loaded?.rolloutPercentage, 0.0)
    }

    // MARK: - ExperimentationClient Tests (using URLProtocol mock)

    func testClient_evaluateFlag_enabled() async throws {
        let flag = makeFlag(key: "enabled-flag", enabled: true, rollout: 100.0)
        let client = makeClient(responseData: encodeFlag(flag))

        let user = makeUser()
        let result = try await client.evaluateFlag("enabled-flag", user: user)
        XCTAssertTrue(result.enabled)
    }

    func testClient_evaluateFlag_disabled() async throws {
        let flag = makeFlag(key: "disabled-flag", enabled: false, rollout: 0.0)
        let client = makeClient(responseData: encodeFlag(flag))

        let result = try await client.evaluateFlag("disabled-flag", user: makeUser())
        XCTAssertFalse(result.enabled)
        XCTAssertEqual(result.reason, "flag_disabled")
    }

    func testClient_evaluateFlag_notFound() async throws {
        let client = makeClient(
            responseData: "{\"detail\":\"Not found\"}".data(using: .utf8)!,
            statusCode: 404
        )

        do {
            _ = try await client.evaluateFlag("ghost-flag", user: makeUser())
            XCTFail("Expected flagNotFound error")
        } catch ExperimentationError.flagNotFound(let key) {
            XCTAssertEqual(key, "ghost-flag")
        }
    }

    func testClient_evaluateFlag_usesCache() async throws {
        let flag = makeFlag(key: "cached-flag", enabled: true, rollout: 100.0)
        let client = makeClient(responseData: encodeFlag(flag))

        let user = makeUser()
        // First call fetches from "API"
        _ = try await client.evaluateFlag("cached-flag", user: user)
        // Second call should use cache; break the mock so a real request would fail.
        MockURLProtocol.mockStatusCode = 500
        MockURLProtocol.mockData = "Server gone".data(using: .utf8)

        // Should still succeed from cache.
        let result = try await client.evaluateFlag("cached-flag", user: user)
        XCTAssertTrue(result.enabled)
    }

    func testClient_getAssignment_success() async throws {
        let assignment = Assignment(
            experimentKey: "exp-1",
            variantKey: "treatment",
            userId: "user-abc"
        )
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(assignment)

        let client = makeClient(responseData: data)
        let result = try await client.getAssignment("exp-1", user: makeUser("user-abc"))
        XCTAssertEqual(result.experimentKey, "exp-1")
        XCTAssertEqual(result.variantKey, "treatment")
        XCTAssertEqual(result.userId, "user-abc")
    }

    func testClient_track_success() async throws {
        // Return a minimal JSON response body
        let responseData = "{\"status\":\"ok\"}".data(using: .utf8)!
        let client = makeClient(responseData: responseData)

        let event = TrackEvent(userId: "user-abc", eventName: "button_clicked")
        // Should not throw.
        try await client.track(event)
    }

    func testClient_refreshFlags() async throws {
        let flags = [
            makeFlag(key: "flag-x", enabled: true, rollout: 80.0),
            makeFlag(key: "flag-y", enabled: false, rollout: 0.0),
        ]
        let client = makeClient(responseData: encodeFlags(flags))

        try await client.refreshFlags()

        // After refresh, flags should be available via local eval (no more network calls).
        MockURLProtocol.mockStatusCode = 500 // break network
        MockURLProtocol.mockData = "broken".data(using: .utf8)

        // user whose hash is < 0.8 for "flag-x"
        let user = makeUser("user-1")
        let result = try await client.evaluateFlag("flag-x", user: user)
        // flag-x is enabled at 80%; user-1 hash ≈ 0.27 < 0.8
        XCTAssertTrue(result.enabled)
    }

    func testClient_close() {
        let flag = makeFlag(key: "to-clear")
        let client = makeClient(responseData: encodeFlag(flag))
        client.close()
        // After close, cache should be empty; no assertion on private state,
        // but close() must not crash.
    }

    // MARK: - User Model Tests

    func testUser_encoding() throws {
        let user = User(id: "user-xyz")
        let encoder = JSONEncoder()
        let data = try encoder.encode(user)
        let decoded = try JSONDecoder().decode(User.self, from: data)
        XCTAssertEqual(decoded.id, "user-xyz")
        XCTAssertNil(decoded.attributes)
    }

    func testUser_withAttributes() throws {
        let user = User(id: "user-123", attributes: [
            "plan": "pro",
            "age": 30,
            "beta": true
        ])
        XCTAssertEqual(user.id, "user-123")
        XCTAssertNotNil(user.attributes)
        XCTAssertEqual(user.attributes?["plan"]?.value as? String, "pro")
        XCTAssertEqual(user.attributes?["age"]?.value as? Int, 30)
        XCTAssertEqual(user.attributes?["beta"]?.value as? Bool, true)
    }

    func testUser_attributesRoundtrip() throws {
        let user = User(id: "u1", attributes: ["score": 99])
        let data = try JSONEncoder().encode(user)
        let decoded = try JSONDecoder().decode(User.self, from: data)
        XCTAssertEqual(decoded.attributes?["score"]?.value as? Int, 99)
    }

    // MARK: - EvalResult Tests

    func testEvalResult_enabledFields() {
        let result = EvalResult(enabled: true, variantKey: "treatment", value: "v1", reason: "variant_assigned")
        XCTAssertTrue(result.enabled)
        XCTAssertEqual(result.variantKey, "treatment")
        XCTAssertEqual(result.value as? String, "v1")
        XCTAssertEqual(result.reason, "variant_assigned")
    }

    func testEvalResult_disabledFields() {
        let result = EvalResult(enabled: false, variantKey: nil, value: nil, reason: "flag_disabled")
        XCTAssertFalse(result.enabled)
        XCTAssertNil(result.variantKey)
        XCTAssertNil(result.value)
        XCTAssertEqual(result.reason, "flag_disabled")
    }

    // MARK: - Error Case Tests

    func testClient_networkError() async throws {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        MockURLProtocol.mockError = URLError(.notConnectedToInternet)
        MockURLProtocol.mockData = nil
        let session = URLSession(configuration: config)

        let sdkConfig = SdkConfig(baseURL: "http://localhost:8000", apiKey: "test-key")
        let client = ExperimentationClient(config: sdkConfig)
        client.http = HTTPClient(
            baseURL: "http://localhost:8000",
            apiKey: "test-key",
            session: session
        )

        do {
            _ = try await client.evaluateFlag("any-flag", user: makeUser())
            XCTFail("Should have thrown on network error")
        } catch ExperimentationError.flagNotFound {
            // Expected: network error with no offline fallback → flagNotFound
        } catch ExperimentationError.networkError {
            // Also acceptable
        }
    }

    func testClient_serverError_500() async throws {
        let client = makeClient(
            responseData: "{\"error\":\"internal server error\"}".data(using: .utf8)!,
            statusCode: 500
        )

        do {
            _ = try await client.evaluateFlag("any-flag", user: makeUser())
            XCTFail("Should have thrown on 500 error")
        } catch ExperimentationError.serverError(let code, _) {
            XCTAssertEqual(code, 500)
        }
    }

    func testClient_decodingError() async throws {
        // Return malformed JSON (not a FeatureFlag)
        let malformed = "{\"not_a_flag\": true}".data(using: .utf8)!
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        MockURLProtocol.mockData = malformed
        MockURLProtocol.mockStatusCode = 200
        MockURLProtocol.mockError = nil
        let session = URLSession(configuration: config)

        let sdkConfig = SdkConfig(baseURL: "http://localhost:8000", apiKey: "test-key")
        let client = ExperimentationClient(config: sdkConfig)
        client.http = HTTPClient(
            baseURL: "http://localhost:8000",
            apiKey: "test-key",
            session: session
        )

        do {
            _ = try await client.evaluateFlag("bad-flag", user: makeUser())
            XCTFail("Should have thrown decoding error")
        } catch ExperimentationError.decodingError {
            // Expected
        }
    }

    // MARK: - AnyCodable Tests

    func testAnyCodable_encodesString() throws {
        let val = AnyCodable("hello")
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? String, "hello")
    }

    func testAnyCodable_encodesBool() throws {
        let val = AnyCodable(true)
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Bool, true)
    }

    func testAnyCodable_encodesInt() throws {
        let val = AnyCodable(42)
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Int, 42)
    }

    func testAnyCodable_encodesDouble() throws {
        let val = AnyCodable(3.14)
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        XCTAssertEqual(decoded.value as? Double ?? 0, 3.14, accuracy: 0.001)
    }

    func testAnyCodable_encodesArray() throws {
        let val = AnyCodable(["a", "b", "c"])
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        let arr = decoded.value as? [Any]
        XCTAssertEqual(arr?.count, 3)
    }

    func testAnyCodable_encodesDict() throws {
        let val = AnyCodable(["x": 1, "y": 2])
        let data = try JSONEncoder().encode(val)
        let decoded = try JSONDecoder().decode(AnyCodable.self, from: data)
        let dict = decoded.value as? [String: Any]
        XCTAssertNotNil(dict)
    }

    // MARK: - ExperimentationError Tests

    func testError_flagNotFound_description() {
        let err = ExperimentationError.flagNotFound("my-flag")
        XCTAssertTrue(err.errorDescription?.contains("my-flag") ?? false)
    }

    func testError_serverError_description() {
        let err = ExperimentationError.serverError(500, "Internal Server Error")
        XCTAssertTrue(err.errorDescription?.contains("500") ?? false)
    }

    func testError_invalidConfig_description() {
        let err = ExperimentationError.invalidConfig("bad URL")
        XCTAssertTrue(err.errorDescription?.contains("bad URL") ?? false)
    }

    func testError_cancelled_description() {
        let err = ExperimentationError.cancelled
        XCTAssertNotNil(err.errorDescription)
    }

    // MARK: - TrackEvent Tests

    func testTrackEvent_encoding() throws {
        let event = TrackEvent(
            userId: "u1",
            eventName: "clicked",
            properties: ["page": "home"]
        )
        let encoder = JSONEncoder()
        let data = try encoder.encode(event)
        let decoded = try JSONDecoder().decode(TrackEvent.self, from: data)
        XCTAssertEqual(decoded.userId, "u1")
        XCTAssertEqual(decoded.eventName, "clicked")
    }

    // MARK: - Convenience Initializer

    func testClient_convenienceInit() {
        let client = ExperimentationClient(
            baseURL: "https://api.example.com",
            apiKey: "key-123"
        )
        XCTAssertNotNil(client)
    }
}

// MARK: - FeatureFlag Codable Conformance Extension for Tests

extension FeatureFlag {
    init(key: String, enabled: Bool, rolloutPercentage: Double, variants: [Variant]? = nil) {
        self.key = key
        self.enabled = enabled
        self.rolloutPercentage = rolloutPercentage
        self.variants = variants
    }
}

extension Variant {
    init(key: String, weight: Double, value: AnyCodable? = nil) {
        self.key = key
        self.weight = weight
        self.value = value
    }
}

extension Assignment {
    init(experimentKey: String, variantKey: String, userId: String) {
        self.experimentKey = experimentKey
        self.variantKey = variantKey
        self.userId = userId
    }
}
