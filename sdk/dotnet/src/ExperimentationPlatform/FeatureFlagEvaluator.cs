using System.Security.Cryptography;
using System.Text;
using ExperimentationPlatform.Models;

namespace ExperimentationPlatform;

/// <summary>
/// Provides local (client-side) evaluation of feature flags using consistent hashing.
/// </summary>
public static class FeatureFlagEvaluator
{
    /// <summary>
    /// Computes a deterministic bucket value in [0.0, 1.0) for a user/flag pair.
    ///
    /// Algorithm: MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → divide by 2^32.
    ///
    /// Cross-SDK test vector: HashUser("user-123", "my-flag") == 0.6927449859213084
    /// </summary>
    /// <param name="userId">The user identifier.</param>
    /// <param name="flagKey">The feature flag key.</param>
    /// <returns>A value in [0.0, 1.0).</returns>
    public static double HashUser(string userId, string flagKey)
    {
        byte[] input = Encoding.UTF8.GetBytes($"{userId}:{flagKey}");
        byte[] hash = MD5.HashData(input);

        // Explicit little-endian reconstruction for cross-platform portability.
        // BitConverter.ToUInt32 is architecture-dependent on big-endian systems.
        uint v = (uint)(hash[0] | (hash[1] << 8) | (hash[2] << 16) | (hash[3] << 24));
        return v / 4294967296.0;
    }

    /// <summary>
    /// Evaluates a feature flag for a specific user locally.
    /// </summary>
    /// <param name="flag">The feature flag definition retrieved from the API.</param>
    /// <param name="userId">The user ID to evaluate for.</param>
    /// <param name="attributes">Optional user attributes (reserved for future targeting rule evaluation).</param>
    /// <returns>
    /// The <see cref="Variant"/> assigned to this user, or <c>null</c> if the flag is disabled,
    /// the user falls outside the rollout percentage, or no variants are defined.
    /// </returns>
    public static Variant? Evaluate(
        FeatureFlag flag,
        string userId,
        Dictionary<string, object>? attributes = null)
    {
        if (!flag.Enabled)
            return null;

        // Bucket [0, 100): compare against rollout percentage.
        double bucket = HashUser(userId, flag.Key) * 100.0;
        if (bucket >= flag.RolloutPercentage)
            return null;

        if (flag.Variants == null || flag.Variants.Count == 0)
            return null;

        // Select a variant deterministically from the set.
        double variantBucket = HashUser(userId, $"{flag.Key}:variant") * flag.Variants.Count;
        int index = (int)variantBucket;

        // Clamp to valid range as a safety guard.
        index = Math.Max(0, Math.Min(index, flag.Variants.Count - 1));
        return flag.Variants[index];
    }
}
