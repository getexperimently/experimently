import Foundation

// MARK: - Protocol

/// Defines the public interface for the ExperimentationSDK client.
///
/// Use this protocol for dependency injection and testing.
public protocol ExperimentationClientProtocol {
    /// Evaluates a feature flag for the given user.
    func evaluateFlag(_ flagKey: String, user: User) async throws -> EvalResult
    /// Retrieves an experiment assignment for the given user.
    func getAssignment(_ experimentKey: String, user: User) async throws -> Assignment
    /// Records a tracking event.
    func track(_ event: TrackEvent) async throws
    /// Fetches all flags from the API and updates the local cache.
    func refreshFlags() async throws
    /// Clears caches and releases resources.
    func close()
}

// MARK: - ExperimentationClient

/// The main entry point for the ExperimentationSDK.
///
/// ## Evaluation Flow
/// When `evaluateFlag` is called:
/// 1. Check the in-memory `FlagCache` for a non-expired entry.
/// 2. If local evaluation is enabled and the flag is in `localFlags` (populated by `refreshFlags`),
///    evaluate it locally without a network call.
/// 3. Fetch the flag from the API if not found locally.
/// 4. Evaluate the flag locally using `FeatureFlagEvaluator`.
/// 5. Cache the flag and return the `EvalResult`.
///
/// If the network is unavailable and no in-memory entry exists, the client falls back
/// to `OfflineStore` (last known values persisted to UserDefaults).
///
/// ## Thread Safety
/// All flag reads and writes are protected by `flagsLock`. The `FlagCache` and
/// `OfflineStore` are themselves thread-safe.
public class ExperimentationClient: ExperimentationClientProtocol {

    // MARK: - Properties

    private let config: SdkConfig
    internal var http: HTTPClient
    private let cache: FlagCache
    private let offlineStore: OfflineStore
    private var localFlags: [String: FeatureFlag] = [:]
    private let flagsLock = NSLock()

    // MARK: - Initializers

    /// Initializes the client with a full configuration object.
    ///
    /// - Parameter config: The `SdkConfig` specifying base URL, API key, cache settings, etc.
    public init(config: SdkConfig) {
        self.config = config
        self.http = HTTPClient(
            baseURL: config.baseURL,
            apiKey: config.apiKey,
            timeout: config.timeout
        )
        self.cache = FlagCache(ttl: config.cacheTTL)
        self.offlineStore = OfflineStore()
    }

    /// Convenience initializer for the most common use case.
    ///
    /// Uses default values for all other configuration parameters.
    ///
    /// - Parameters:
    ///   - baseURL: The API base URL (e.g., `"http://localhost:8000"`).
    ///   - apiKey: The API key for authentication.
    public convenience init(baseURL: String, apiKey: String) {
        self.init(config: SdkConfig(baseURL: baseURL, apiKey: apiKey))
    }

    // MARK: - ExperimentationClientProtocol

    /// Evaluates a feature flag for the given user.
    ///
    /// Attempts local evaluation from the in-memory cache or `localFlags` map before
    /// falling back to a network request. On network failure, serves from `OfflineStore`.
    ///
    /// - Parameters:
    ///   - flagKey: The unique string key of the feature flag.
    ///   - user: The user to evaluate the flag for.
    /// - Returns: An `EvalResult` describing whether the flag is enabled and any variant assignment.
    /// - Throws: `ExperimentationError` if the flag cannot be fetched and no fallback is available.
    public func evaluateFlag(_ flagKey: String, user: User) async throws -> EvalResult {
        // 1. Check in-memory TTL cache.
        if let cached = cache.get(flagKey) {
            return FeatureFlagEvaluator.evaluate(cached, user: user)
        }

        // 2. Try local flags map (populated by refreshFlags).
        if config.enableLocalEval {
            flagsLock.lock()
            let localFlag = localFlags[flagKey]
            flagsLock.unlock()

            if let flag = localFlag {
                cache.set(flagKey, flag: flag)
                return FeatureFlagEvaluator.evaluate(flag, user: user)
            }
        }

        // 3. Fetch from API.
        let flag: FeatureFlag
        do {
            flag = try await http.get(
                "/api/v1/flags/\(flagKey)",
                as: FeatureFlag.self
            )
        } catch ExperimentationError.serverError(let code, _) where code == 404 {
            throw ExperimentationError.flagNotFound(flagKey)
        } catch ExperimentationError.networkError, ExperimentationError.cancelled {
            // 4. Network unavailable — try offline store.
            if let stored = offlineStore.loadFlag(flagKey) {
                return FeatureFlagEvaluator.evaluate(stored, user: user)
            }
            throw ExperimentationError.flagNotFound(flagKey)
        }

        // 5. Cache flag and return evaluation.
        cache.set(flagKey, flag: flag)
        offlineStore.saveFlag(flag)

        flagsLock.lock()
        localFlags[flagKey] = flag
        flagsLock.unlock()

        return FeatureFlagEvaluator.evaluate(flag, user: user)
    }

    /// Retrieves an experiment variant assignment for the given user.
    ///
    /// - Parameters:
    ///   - experimentKey: The unique string key of the experiment.
    ///   - user: The user to assign.
    /// - Returns: An `Assignment` containing the experiment key, variant key, and user ID.
    /// - Throws: `ExperimentationError` on network or server failure.
    public func getAssignment(_ experimentKey: String, user: User) async throws -> Assignment {
        struct AssignmentRequest: Encodable {
            let experimentKey: String
            let userId: String
            enum CodingKeys: String, CodingKey {
                case experimentKey = "experiment_key"
                case userId = "user_id"
            }
        }

        let requestBody = AssignmentRequest(
            experimentKey: experimentKey,
            userId: user.id
        )

        return try await http.post(
            "/api/v1/assignments",
            body: requestBody,
            as: Assignment.self
        )
    }

    /// Records an analytics or conversion event for the given user.
    ///
    /// Uses a best-effort fire-and-forget approach for low-latency callers.
    /// For guaranteed delivery, call this via `track` which throws on error.
    ///
    /// - Parameter event: The `TrackEvent` to record.
    /// - Throws: `ExperimentationError` if the server cannot be reached.
    public func track(_ event: TrackEvent) async throws {
        struct TrackResponse: Decodable {
            let status: String?
        }
        _ = try await http.post("/api/v1/events", body: event, as: TrackResponse.self)
    }

    /// Fetches all feature flags from the API and populates the local flags map.
    ///
    /// Call this at app startup to warm the local cache for zero-latency local evaluation.
    /// Also persists flags to `OfflineStore` for offline fallback.
    ///
    /// - Throws: `ExperimentationError` on network or server failure.
    public func refreshFlags() async throws {
        let flags = try await http.get("/api/v1/flags", as: [FeatureFlag].self)

        flagsLock.lock()
        localFlags = Dictionary(uniqueKeysWithValues: flags.map { ($0.key, $0) })
        flagsLock.unlock()

        for flag in flags {
            cache.set(flag.key, flag: flag)
        }

        offlineStore.saveAllFlags(flags)
    }

    /// Clears all in-memory caches and releases resources.
    ///
    /// Call this when the SDK is no longer needed (e.g., on app termination or sign-out).
    /// Note: `OfflineStore` data is not cleared so it remains available on the next launch.
    public func close() {
        cache.removeAll()
        flagsLock.lock()
        localFlags.removeAll()
        flagsLock.unlock()
    }
}
