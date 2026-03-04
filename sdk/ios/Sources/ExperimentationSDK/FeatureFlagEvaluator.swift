import Foundation
import CommonCrypto

/// Local feature flag evaluator using MD5-based consistent hashing.
///
/// ## Hash Algorithm
/// The algorithm is byte-for-byte compatible with all other SDK implementations
/// (Java, Python, JavaScript) and the backend Lambda consistent_hash.py:
///
/// 1. Compute MD5 of `"{userId}:{flagKey}"` encoded as UTF-8.
/// 2. Read the first 4 bytes as a little-endian unsigned 32-bit integer.
/// 3. Divide by `0x100000000` (2^32) to normalize to `[0.0, 1.0)`.
///
/// ## Evaluation Logic
/// - If the flag is disabled globally, returns `EvalResult(enabled: false, reason: "flag_disabled")`.
/// - If `hash >= rolloutPercentage / 100.0`, the user is outside the rollout band → `enabled: false`.
/// - For boolean flags (no variants), returns `enabled: true` with `reason: "in_rollout"`.
/// - For multi-variant flags, the hash is re-scaled within the rollout band to pick a variant
///   proportionally by weight.
public struct FeatureFlagEvaluator {

    /// Divisor used to normalize the 32-bit hash value into [0.0, 1.0).
    /// Equals 2^32 = 4294967296, matching Python's `MAX_HASH_VALUE + 1`.
    static let hashDivisor: Double = 0x100000000  // 4294967296.0

    // MARK: - Public Interface

    /// Computes a deterministic, normalized hash value in `[0.0, 1.0)` for the
    /// given user ID and flag key combination.
    ///
    /// The hash is cross-SDK compatible: given the same inputs, Java, Python, JS,
    /// and Swift implementations all produce the same output.
    ///
    /// - Parameters:
    ///   - userId: The user's unique identifier.
    ///   - flagKey: The feature flag's unique key (used as salt).
    /// - Returns: A value in `[0.0, 1.0)`.
    public static func hashUser(_ userId: String, flagKey: String) -> Double {
        let input = "\(userId):\(flagKey)"
        guard let data = input.data(using: .utf8) else { return 0.0 }

        var digest = [UInt8](repeating: 0, count: Int(CC_MD5_DIGEST_LENGTH))
        data.withUnsafeBytes { ptr in
            _ = CC_MD5(ptr.baseAddress, CC_LONG(data.count), &digest)
        }

        // Read first 4 bytes as little-endian unsigned 32-bit integer.
        // This matches Java:  ((bytes[0] & 0xFF)) | ((bytes[1] & 0xFF) << 8) | ...
        // And Python: struct.unpack('<I', hash_bytes[:4])[0]
        let v = UInt32(digest[0])
            | UInt32(digest[1]) << 8
            | UInt32(digest[2]) << 16
            | UInt32(digest[3]) << 24

        // Divide by 2^32 (not 2^32 - 1) to normalize to [0.0, 1.0).
        // This matches Java's HASH_DIVISOR = 0x100000000L and Python's MAX_HASH_VALUE + 1.
        return Double(v) / hashDivisor
    }

    /// Evaluates whether a feature flag is enabled for a given user and, if applicable,
    /// which variant they are assigned to.
    ///
    /// - Parameters:
    ///   - flag: The feature flag configuration from the API.
    ///   - user: The user to evaluate.
    /// - Returns: An `EvalResult` describing the evaluation outcome.
    public static func evaluate(_ flag: FeatureFlag, user: User) -> EvalResult {
        // Fast path: flag globally disabled.
        guard flag.enabled else {
            return EvalResult(enabled: false, variantKey: nil, value: nil, reason: "flag_disabled")
        }

        let hash = hashUser(user.id, flagKey: flag.key)
        let rolloutFraction = flag.rolloutPercentage / 100.0

        // User's hash falls outside the rollout band.
        guard hash < rolloutFraction else {
            return EvalResult(enabled: false, variantKey: nil, value: nil, reason: "out_of_rollout")
        }

        // Multi-variant flag: assign a variant proportionally.
        if let variants = flag.variants, !variants.isEmpty {
            let variantKey = assignVariant(variants, hash: hash, rolloutFraction: rolloutFraction)
            return EvalResult(
                enabled: true,
                variantKey: variantKey,
                value: nil,
                reason: "variant_assigned"
            )
        }

        // Boolean flag: user is simply in rollout.
        return EvalResult(enabled: true, variantKey: nil, value: nil, reason: "in_rollout")
    }

    // MARK: - Private Helpers

    /// Picks a variant for a user who is within the rollout band.
    ///
    /// The user's hash is re-scaled from the rollout band `[0, rolloutFraction)` to
    /// `[0.0, 1.0)` and compared against cumulative variant weights.
    ///
    /// - Parameters:
    ///   - variants: The list of variants with relative weights.
    ///   - hash: The user's normalized hash value.
    ///   - rolloutFraction: The rollout fraction (rolloutPercentage / 100).
    /// - Returns: The key of the selected variant.
    private static func assignVariant(
        _ variants: [Variant],
        hash: Double,
        rolloutFraction: Double
    ) -> String {
        // Normalize the hash to [0.0, 1.0) within the rollout band.
        let normalized = rolloutFraction > 0.0 ? hash / rolloutFraction : 0.0

        let totalWeight = variants.reduce(0.0) { $0 + $1.weight }
        var cumulative = 0.0

        for variant in variants {
            cumulative += variant.weight / totalWeight
            if normalized < cumulative {
                return variant.key
            }
        }

        // Fallback to last variant for floating-point edge cases.
        return variants.last?.key ?? ""
    }
}
