import Foundation

// MARK: - SDK Configuration

/// Configuration for the ExperimentationSDK client.
public struct SdkConfig {
    /// Base URL of the experimentation platform API.
    public let baseURL: String
    /// API key for authenticating requests.
    public let apiKey: String
    /// Network request timeout in seconds.
    public let timeout: TimeInterval
    /// Maximum number of flags to keep in the in-memory cache.
    public let cacheSize: Int
    /// Time-to-live for cached flags in seconds (default: 5 minutes).
    public let cacheTTL: TimeInterval
    /// Whether to evaluate flags locally instead of making API calls when possible.
    public let enableLocalEval: Bool

    public init(
        baseURL: String = "http://localhost:8000",
        apiKey: String,
        timeout: TimeInterval = 10.0,
        cacheSize: Int = 1000,
        cacheTTL: TimeInterval = 300,
        enableLocalEval: Bool = true
    ) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.timeout = timeout
        self.cacheSize = cacheSize
        self.cacheTTL = cacheTTL
        self.enableLocalEval = enableLocalEval
    }
}

// MARK: - User

/// Represents a platform user for flag evaluation and experiment assignment.
public struct User: Codable {
    /// Unique identifier for the user.
    public let id: String
    /// Optional key-value attributes for targeting rules.
    public let attributes: [String: AnyCodable]?

    public init(id: String, attributes: [String: Any]? = nil) {
        self.id = id
        self.attributes = attributes.map { dict in
            dict.mapValues { AnyCodable($0) }
        }
    }
}

// MARK: - Feature Flag

/// A feature flag definition returned from the API.
public struct FeatureFlag: Codable {
    /// Unique string key identifying the flag.
    public let key: String
    /// Whether the flag is globally enabled.
    public let enabled: Bool
    /// Percentage of users (0–100) who receive this flag.
    public let rolloutPercentage: Double
    /// Optional list of variants for multi-variant flags.
    public let variants: [Variant]?

    enum CodingKeys: String, CodingKey {
        case key, enabled
        case rolloutPercentage = "rollout_percentage"
        case variants
    }
}

// MARK: - Variant

/// A single variant within a feature flag.
public struct Variant: Codable {
    /// Unique key for this variant (e.g., "control", "treatment").
    public let key: String
    /// Relative weight used for proportional assignment. Weights across all variants should sum to 1.0.
    public let weight: Double
    /// Optional value associated with this variant.
    public let value: AnyCodable?
}

// MARK: - Assignment

/// Result of assigning a user to an experiment variant.
public struct Assignment: Codable {
    /// The experiment's unique string key.
    public let experimentKey: String
    /// The variant key the user was assigned to.
    public let variantKey: String
    /// The user ID used for the assignment.
    public let userId: String

    enum CodingKeys: String, CodingKey {
        case experimentKey = "experiment_key"
        case variantKey = "variant_key"
        case userId = "user_id"
    }
}

// MARK: - EvalResult

/// The result of evaluating a feature flag for a specific user.
public struct EvalResult {
    /// Whether the flag is enabled for this user.
    public let enabled: Bool
    /// The variant key assigned to the user, if any.
    public let variantKey: String?
    /// The value associated with the assigned variant, if any.
    public let value: Any?
    /// A human-readable reason explaining the evaluation outcome.
    public let reason: String

    public init(enabled: Bool, variantKey: String?, value: Any?, reason: String) {
        self.enabled = enabled
        self.variantKey = variantKey
        self.value = value
        self.reason = reason
    }
}

// MARK: - TrackEvent

/// An analytics event to be recorded for an experiment or feature flag.
public struct TrackEvent: Codable {
    /// The ID of the user performing the event.
    public let userId: String
    /// The name of the event (e.g., "button_clicked", "purchase_completed").
    public let eventName: String
    /// Optional additional properties associated with the event.
    public let properties: [String: AnyCodable]?

    enum CodingKeys: String, CodingKey {
        case userId = "user_id"
        case eventName = "event_name"
        case properties
    }

    public init(userId: String, eventName: String, properties: [String: Any]? = nil) {
        self.userId = userId
        self.eventName = eventName
        self.properties = properties.map { dict in
            dict.mapValues { AnyCodable($0) }
        }
    }
}

// MARK: - AnyCodable

/// A type-erased wrapper that supports encoding and decoding arbitrary JSON values.
/// Handles String, Int, Double, Bool, [Any], [String: Any], and nil.
public struct AnyCodable: Codable {
    /// The underlying value.
    public let value: Any

    public init(_ value: Any) {
        self.value = value
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            self.value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            self.value = bool
        } else if let int = try? container.decode(Int.self) {
            self.value = int
        } else if let double = try? container.decode(Double.self) {
            self.value = double
        } else if let string = try? container.decode(String.self) {
            self.value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            self.value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            self.value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "AnyCodable: unsupported JSON value type"
            )
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let float as Float:
            try container.encode(Double(float))
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            let wrapped = array.map { AnyCodable($0) }
            try container.encode(wrapped)
        case let dict as [String: Any]:
            let wrapped = dict.mapValues { AnyCodable($0) }
            try container.encode(wrapped)
        default:
            let context = EncodingError.Context(
                codingPath: encoder.codingPath,
                debugDescription: "AnyCodable: unsupported value type \(type(of: value))"
            )
            throw EncodingError.invalidValue(value, context)
        }
    }
}

// MARK: - ExperimentationError

/// Errors that can be thrown by the ExperimentationSDK.
public enum ExperimentationError: Error, LocalizedError {
    /// The SDK configuration is invalid.
    case invalidConfig(String)
    /// A network-level error occurred.
    case networkError(Error)
    /// The server response could not be decoded.
    case decodingError(Error)
    /// The requested feature flag key was not found.
    case flagNotFound(String)
    /// The server returned an HTTP error response.
    case serverError(Int, String)
    /// The operation was cancelled.
    case cancelled

    public var errorDescription: String? {
        switch self {
        case .invalidConfig(let msg):
            return "Invalid SDK configuration: \(msg)"
        case .networkError(let err):
            return "Network error: \(err.localizedDescription)"
        case .decodingError(let err):
            return "Decoding error: \(err.localizedDescription)"
        case .flagNotFound(let key):
            return "Feature flag not found: '\(key)'"
        case .serverError(let code, let msg):
            return "Server error \(code): \(msg)"
        case .cancelled:
            return "Operation was cancelled"
        }
    }
}
