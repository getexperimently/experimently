package com.experimentationplatform.sdk;

import com.experimentationplatform.sdk.model.FeatureFlag;
import com.experimentationplatform.sdk.model.User;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;

/**
 * Evaluates feature flags locally using consistent hashing.
 *
 * <h2>Algorithm</h2>
 * <p>The hash algorithm is byte-for-byte compatible with the Python Lambda
 * implementation in {@code backend/lambda/shared/consistent_hash.py}:
 * <ol>
 *   <li>Compute MD5 of {@code "{userId}:{salt}"} encoded as UTF-8.</li>
 *   <li>Interpret the first 4 bytes as a <strong>little-endian</strong> unsigned 32-bit integer.</li>
 *   <li>Divide by {@code 0x100000000L} (2^32) to normalize to [0.0, 1.0).</li>
 * </ol>
 *
 * <p>The same input always produces the same normalized value, ensuring deterministic
 * and consistent assignment across all SDK implementations (Java, Python, JS).
 *
 * <h2>Evaluation Logic</h2>
 * <ul>
 *   <li>If the flag is null or disabled, returns {@code null} (user not in rollout).</li>
 *   <li>If {@code hash >= rolloutPercentage/100.0}, user is outside the rollout → {@code null}.</li>
 *   <li>For boolean flags (no variants), returns {@code "on"} for users in rollout.</li>
 *   <li>For multi-variant flags, picks a variant proportionally using the same hash
 *       re-scaled within the rollout band.</li>
 * </ul>
 */
public class FeatureFlagEvaluator {

    /**
     * Maximum unsigned 32-bit value + 1 (2^32). Used as the divisor to normalize the hash.
     * Matches Python: {@code MAX_HASH_VALUE + 1 == 0x100000000}.
     */
    static final long HASH_DIVISOR = 0x100000000L;

    /**
     * Computes a normalized hash value in [0.0, 1.0) for the given user ID and salt.
     *
     * <p>The algorithm matches {@code ConsistentHasher._hash()} and
     * {@code ConsistentHasher.get_normalized_hash()} from the Python Lambda:
     * <pre>
     *     combined = f"{user_id}:{salt}".encode('utf-8')
     *     hash_bytes = hashlib.md5(combined).digest()[:4]
     *     hash_value = struct.unpack('&lt;I', hash_bytes)[0]   # little-endian unsigned int
     *     return hash_value / (MAX_HASH_VALUE + 1)          # normalize
     * </pre>
     *
     * @param userId  the user's unique identifier
     * @param salt    the salt string (flag key, experiment key, or suffixed key)
     * @return normalized hash in [0.0, 1.0)
     * @throws RuntimeException if MD5 is unexpectedly unavailable (never in practice)
     */
    public double computeHash(String userId, String salt) {
        try {
            String input = userId + ":" + salt;
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] bytes = md.digest(input.getBytes(StandardCharsets.UTF_8));

            // Little-endian unsigned 32-bit integer from first 4 bytes.
            // Python: struct.unpack('<I', hash_bytes)[0]
            // '<I' = little-endian unsigned int:
            //   byte[0] is least significant, byte[3] is most significant.
            long hash = ((bytes[0] & 0xFFL))
                      | ((bytes[1] & 0xFFL) << 8)
                      | ((bytes[2] & 0xFFL) << 16)
                      | ((bytes[3] & 0xFFL) << 24);

            // Divide by 2^32 to normalize to [0.0, 1.0)
            return hash / (double) HASH_DIVISOR;
        } catch (NoSuchAlgorithmException e) {
            throw new RuntimeException("MD5 MessageDigest not available on this JVM", e);
        }
    }

    /**
     * Evaluates whether a user should receive a feature flag, and which variant.
     *
     * <p>Returns {@code null} if the flag is disabled or the user is outside the rollout.
     * Returns the variant name if the user is in rollout (e.g., {@code "on"}, {@code "control"},
     * {@code "treatment"}).
     *
     * @param user the user to evaluate
     * @param flag the feature flag configuration
     * @return variant name, or {@code null} if the user is not in rollout
     */
    public String evaluate(User user, FeatureFlag flag) {
        if (flag == null || !flag.isEnabled()) {
            return null;
        }

        double hash = computeHash(user.getUserId(), flag.getKey());
        double rolloutFraction = flag.getRolloutPercentage() / 100.0;

        // User is outside the rollout band
        if (hash >= rolloutFraction) {
            return null;
        }

        List<FeatureFlag.Variant> variants = flag.getVariants();

        // Boolean flag: no variants defined → return "on"
        if (variants == null || variants.isEmpty()) {
            return "on";
        }

        // Multi-variant: re-scale hash within the rollout band [0, rolloutFraction)
        // to [0.0, 1.0) and pick a variant proportionally by weight.
        double variantHash = (rolloutFraction > 0.0) ? (hash / rolloutFraction) : 0.0;

        double cumulative = 0.0;
        for (FeatureFlag.Variant variant : variants) {
            cumulative += variant.getWeight();
            if (variantHash < cumulative) {
                return variant.getName();
            }
        }

        // Fallback to last variant in case of floating-point rounding
        return variants.get(variants.size() - 1).getName();
    }
}
