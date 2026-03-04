package com.experimentationplatform.android

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

/**
 * Local feature flag evaluator using MD5 consistent hash.
 *
 * Hash spec (byte-for-byte compatible with Java/Python/Go/iOS/JS SDKs):
 *   1. Compute MD5 of "{userId}:{flagKey}" encoded as UTF-8.
 *   2. Read first 4 bytes as a little-endian unsigned 32-bit integer.
 *   3. Divide by 0x100000000L (2^32) to normalize to [0.0, 1.0).
 *
 * This is identical to the Java SDK algorithm in FeatureFlagEvaluator.java
 * and the Python lambda in consistent_hash.py (get_normalized_hash).
 */
object FeatureFlagEvaluator {

    /**
     * Divisor used to normalize the hash to [0.0, 1.0).
     * Matches Java SDK: HASH_DIVISOR = 0x100000000L
     * Matches Python SDK: MAX_HASH_VALUE + 1 = 0xFFFFFFFF + 1
     */
    private const val HASH_DIVISOR = 0x100000000L

    /**
     * Computes a deterministic float in [0, 1) for user+flag combination.
     *
     * Algorithm:
     *   input  = "$userId:$flagKey" encoded as UTF-8
     *   bytes  = MD5(input)
     *   uint32 = bytes[0..3] interpreted as little-endian unsigned 32-bit int
     *   result = uint32 / 2^32
     *
     * Matches Java SDK computeHash() and Python get_normalized_hash().
     */
    fun hashUser(userId: String, flagKey: String): Double {
        val input = "$userId:$flagKey"
        val digest = MessageDigest.getInstance("MD5")
        val bytes = digest.digest(input.toByteArray(Charsets.UTF_8))

        // Read first 4 bytes as little-endian unsigned 32-bit integer.
        // Matches Java SDK:
        //   long hash = (bytes[0] & 0xFFL) | ((bytes[1] & 0xFFL) << 8) |
        //               ((bytes[2] & 0xFFL) << 16) | ((bytes[3] & 0xFFL) << 24);
        val v = ((bytes[0].toLong() and 0xFFL))
            .or((bytes[1].toLong() and 0xFFL) shl 8)
            .or((bytes[2].toLong() and 0xFFL) shl 16)
            .or((bytes[3].toLong() and 0xFFL) shl 24)

        return v.toDouble() / HASH_DIVISOR.toDouble()
    }

    /**
     * Evaluates whether a feature flag is enabled for a user.
     *
     * @param flag the feature flag to evaluate
     * @param user the user being evaluated
     * @return EvalResult indicating enabled state, variant, and reason
     */
    fun evaluate(flag: FeatureFlag, user: User): EvalResult {
        if (!flag.enabled) {
            return EvalResult(enabled = false, reason = "flag_disabled")
        }

        val hash = hashUser(user.id, flag.key)
        val rolloutFraction = flag.rolloutPercentage / 100.0

        if (hash >= rolloutFraction) {
            return EvalResult(enabled = false, reason = "out_of_rollout")
        }

        if (flag.variants.isNotEmpty()) {
            val variantKey = assignVariant(flag.variants, hash, rolloutFraction)
            return EvalResult(enabled = true, variantKey = variantKey, reason = "variant_assigned")
        }

        return EvalResult(enabled = true, reason = "in_rollout")
    }

    /**
     * Assigns a variant to a user based on their hash value within the rollout band.
     * Re-scales hash from [0, rolloutFraction) to [0, 1) for proportional variant selection.
     */
    private fun assignVariant(
        variants: List<Variant>,
        hash: Double,
        rolloutFraction: Double
    ): String {
        val normalized = if (rolloutFraction > 0.0) hash / rolloutFraction else 0.0
        val totalWeight = variants.sumOf { it.weight }
        var cumulative = 0.0

        for (variant in variants) {
            cumulative += variant.weight / totalWeight
            if (normalized < cumulative) {
                return variant.key
            }
        }
        // Fallback to last variant (floating-point rounding safety)
        return variants.last().key
    }
}
