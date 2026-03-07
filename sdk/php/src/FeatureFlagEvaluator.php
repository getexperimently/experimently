<?php

declare(strict_types=1);

namespace ExperimentationPlatform;

/**
 * Evaluates feature flags locally using the cross-SDK consistent hash algorithm.
 *
 * Hash formula (must match all other SDKs):
 *   MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → divide by 2^32
 *
 * Known test vector: hashUser("user-123", "my-flag") === 0.6927449859213084
 */
class FeatureFlagEvaluator
{
    /**
     * Compute a deterministic bucket value in [0.0, 1.0) for the given user + flag combination.
     *
     * This hash is consistent across all Experimentation Platform SDKs (JS, Python, Java, React, PHP).
     *
     * @param string $userId  User identifier
     * @param string $flagKey Feature flag key
     * @return float Value in [0.0, 1.0)
     */
    public static function hashUser(string $userId, string $flagKey): float
    {
        // Raw binary MD5 output
        $raw = md5("{$userId}:{$flagKey}", true);

        // Unpack first 4 bytes as unsigned little-endian 32-bit integer
        $unpacked = unpack('V', substr($raw, 0, 4));
        $v = $unpacked[1];

        // Divide by 2^32 to get a value in [0.0, 1.0)
        return $v / 4294967296.0;
    }

    /**
     * Evaluate a feature flag for a given user using local consistent hashing.
     *
     * @param array  $flag       Feature flag data from the API (must have 'enabled', 'key', 'rollout_percentage', 'variants')
     * @param string $userId     User identifier
     * @param array  $attributes Additional user attributes (used for future targeting rules; currently ignored in local eval)
     * @return array|null        The matched variant array, or null if the user is not in the rollout / flag is disabled
     */
    public static function evaluate(array $flag, string $userId, array $attributes = []): ?array
    {
        // Short-circuit if flag is disabled
        if (!($flag['enabled'] ?? false)) {
            return null;
        }

        // Compute the user's bucket (0–100 scale)
        $bucket = self::hashUser($userId, $flag['key']) * 100.0;

        // Exclude user if their bucket is at or above the rollout threshold
        $rolloutPercentage = (float)($flag['rollout_percentage'] ?? 0);
        if ($bucket >= $rolloutPercentage) {
            return null;
        }

        // No variants means nothing to assign
        $variants = $flag['variants'] ?? [];
        if (empty($variants)) {
            return null;
        }

        // Re-hash with ':variant' suffix to evenly distribute users across variants
        $variantBucket = self::hashUser($userId, $flag['key'] . ':variant') * count($variants);
        $variantIndex = (int)$variantBucket;

        return $variants[$variantIndex];
    }
}
