package com.experimentationplatform.sdk;

import com.experimentationplatform.sdk.model.FeatureFlag;
import com.experimentationplatform.sdk.model.User;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for {@link FeatureFlagEvaluator}.
 *
 * <p>Includes cross-validation against the Python Lambda consistent_hash.py implementation
 * to ensure byte-level parity of the MD5 little-endian hashing algorithm.
 */
@DisplayName("FeatureFlagEvaluator")
class FeatureFlagEvaluatorTest {

    private FeatureFlagEvaluator evaluator;

    @BeforeEach
    void setUp() {
        evaluator = new FeatureFlagEvaluator();
    }

    // -------------------------------------------------------------------------
    // computeHash tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("computeHash returns value in [0.0, 1.0)")
    void testComputeHashReturnsValueBetweenZeroAndOne() {
        double hash = evaluator.computeHash("user1", "flag1");
        assertTrue(hash >= 0.0, "hash should be >= 0.0");
        assertTrue(hash < 1.0, "hash should be < 1.0");
    }

    @Test
    @DisplayName("computeHash is deterministic for same input")
    void testComputeHashIsConsistentForSameInput() {
        double hash1 = evaluator.computeHash("user1", "flag1");
        double hash2 = evaluator.computeHash("user1", "flag1");
        double hash3 = evaluator.computeHash("user1", "flag1");
        assertEquals(hash1, hash2, "Same input must produce same hash");
        assertEquals(hash2, hash3, "Same input must produce same hash on repeated calls");
    }

    @Test
    @DisplayName("computeHash produces different values for different user IDs")
    void testComputeHashDifferentForDifferentUsers() {
        double hashAlice = evaluator.computeHash("alice", "checkout-v2");
        double hashBob = evaluator.computeHash("bob", "checkout-v2");
        assertNotEquals(hashAlice, hashBob,
                "Different users should (almost certainly) produce different hashes");
    }

    @Test
    @DisplayName("computeHash produces different values for different salts")
    void testComputeHashDifferentForDifferentSalts() {
        double hash1 = evaluator.computeHash("user1", "flag1");
        double hash2 = evaluator.computeHash("user1", "flag2");
        assertNotEquals(hash1, hash2,
                "Different salts should (almost certainly) produce different hashes");
    }

    /**
     * Cross-validates the Java implementation against known Python outputs.
     *
     * <p>Python reference (consistent_hash.py):
     * <pre>
     *   combined = f"{user_id}:{salt}".encode('utf-8')
     *   hash_bytes = hashlib.md5(combined).digest()[:4]
     *   hash_value = struct.unpack('&lt;I', hash_bytes)[0]   # little-endian
     *   return hash_value / 0x100000000
     * </pre>
     *
     * <p>Expected values computed with Python:
     * <ul>
     *   <li>("user1", "flag1")        → 0.2281730449944362</li>
     *   <li>("user-123", "my-feature") → 0.1742990910820663</li>
     *   <li>("alice", "checkout-v2")  → 0.9276319702807069</li>
     *   <li>("bob", "checkout-v2")    → 0.9467693545855582</li>
     * </ul>
     */
    @Test
    @DisplayName("computeHash matches Python Lambda consistent_hash.py algorithm")
    void testComputeHashMatchesPythonAlgorithm() {
        double delta = 1e-9; // tolerance for floating-point comparison

        // ("user1", "flag1") => raw=979995766, normalized=0.2281730450
        assertEquals(0.2281730450, evaluator.computeHash("user1", "flag1"), delta,
                "Hash for (user1, flag1) must match Python output");

        // ("user-123", "my-feature") => raw=748608896, normalized=0.1742990911
        assertEquals(0.1742990911, evaluator.computeHash("user-123", "my-feature"), delta,
                "Hash for (user-123, my-feature) must match Python output");

        // ("alice", "checkout-v2") => raw=3984148975, normalized=0.9276319703
        assertEquals(0.9276319703, evaluator.computeHash("alice", "checkout-v2"), delta,
                "Hash for (alice, checkout-v2) must match Python output");

        // ("bob", "checkout-v2") => raw=4066343415, normalized=0.9467693546
        assertEquals(0.9467693546, evaluator.computeHash("bob", "checkout-v2"), delta,
                "Hash for (bob, checkout-v2) must match Python output");
    }

    @Test
    @DisplayName("computeHash uses little-endian byte order (not big-endian)")
    void testComputeHashUsesLittleEndianByteOrder() {
        // The Python algorithm uses struct.unpack('<I', ...) which is little-endian.
        // This test verifies the known raw value 979995766 for ("user1", "flag1").
        // If big-endian were used, the result would differ.
        double hash = evaluator.computeHash("user1", "flag1");
        // Expected: 979995766 / 2^32 = 0.2281730449944...
        assertEquals(979995766.0 / FeatureFlagEvaluator.HASH_DIVISOR, hash, 1e-10,
                "Hash must match little-endian byte interpretation");
    }

    @Test
    @DisplayName("computeHash handles empty string inputs")
    void testComputeHashHandlesEmptyStrings() {
        // Should not throw; MD5("" + ":" + "") is valid
        double hash = evaluator.computeHash("", "");
        assertTrue(hash >= 0.0 && hash < 1.0,
                "Hash of empty strings should still be in [0.0, 1.0)");
    }

    @Test
    @DisplayName("computeHash handles unicode characters in user ID")
    void testComputeHashHandlesUnicode() {
        double hash = evaluator.computeHash("用户-123", "flag1");
        assertTrue(hash >= 0.0 && hash < 1.0,
                "Hash of unicode user ID should be in [0.0, 1.0)");
    }

    // -------------------------------------------------------------------------
    // evaluate tests
    // -------------------------------------------------------------------------

    @Test
    @DisplayName("evaluate returns null when flag is null")
    void testEvaluateReturnsNullWhenFlagIsNull() {
        User user = User.builder("user1").build();
        assertNull(evaluator.evaluate(user, null),
                "evaluate should return null for null flag");
    }

    @Test
    @DisplayName("evaluate returns null when flag is disabled")
    void testEvaluateReturnsNullWhenFlagDisabled() {
        User user = User.builder("user1").build();
        FeatureFlag flag = new FeatureFlag("id-1", "flag1", false, 100.0, null);
        assertNull(evaluator.evaluate(user, flag),
                "evaluate should return null when flag.enabled=false");
    }

    @Test
    @DisplayName("evaluate returns 'on' for all users when rollout is 100%")
    void testEvaluateReturnsOnForUserInRolloutAt100Percent() {
        // At 100% rollout, hash is always < 1.0, so all users should be "on"
        User user1 = User.builder("user1").build();
        User user2 = User.builder("user-abc-999").build();
        User user3 = User.builder("alice").build();

        FeatureFlag flag = new FeatureFlag("id-1", "flag1", true, 100.0, null);

        assertEquals("on", evaluator.evaluate(user1, flag));
        assertEquals("on", evaluator.evaluate(user2, flag));
        assertEquals("on", evaluator.evaluate(user3, flag));
    }

    @Test
    @DisplayName("evaluate returns null for all users when rollout is 0%")
    void testEvaluateReturnsNullForUserNotInRollout() {
        User user1 = User.builder("user1").build();
        User user2 = User.builder("alice").build();

        FeatureFlag flag = new FeatureFlag("id-1", "flag1", true, 0.0, null);

        assertNull(evaluator.evaluate(user1, flag),
                "No user should be in 0% rollout");
        assertNull(evaluator.evaluate(user2, flag),
                "No user should be in 0% rollout");
    }

    @Test
    @DisplayName("evaluate is consistent for the same user across multiple calls")
    void testEvaluateIsConsistentForSameUser() {
        User user = User.builder("user-123").build();
        FeatureFlag flag = new FeatureFlag("id-1", "my-feature", true, 50.0, null);

        String result1 = evaluator.evaluate(user, flag);
        String result2 = evaluator.evaluate(user, flag);
        String result3 = evaluator.evaluate(user, flag);

        assertEquals(result1, result2, "Same user should always get same evaluation");
        assertEquals(result2, result3, "Same user should always get same evaluation");
    }

    @Test
    @DisplayName("evaluate at 50% rollout puts approximately half of users in rollout")
    void testRolloutPercentageAt50Percent() {
        FeatureFlag flag = new FeatureFlag("id-1", "half-rollout", true, 50.0, null);

        int inRollout = 0;
        int total = 1000;
        for (int i = 0; i < total; i++) {
            User user = User.builder("user-" + i).build();
            if (evaluator.evaluate(user, flag) != null) {
                inRollout++;
            }
        }

        // Expect roughly 50% ± 5% (i.e., between 450 and 550 out of 1000)
        double pct = (double) inRollout / total;
        assertTrue(pct >= 0.45 && pct <= 0.55,
                "Expected ~50% rollout, got " + (pct * 100) + "%");
    }

    @Test
    @DisplayName("evaluate returns correct variant for a multi-variant flag")
    void testEvaluateReturnsVariantForMultiVariantFlag() {
        // user-123 has hash 0.1742990911 for "my-feature" (< 100% rollout)
        User user = User.builder("user-123").build();

        List<FeatureFlag.Variant> variants = Arrays.asList(
                new FeatureFlag.Variant("control", 0.5),
                new FeatureFlag.Variant("treatment", 0.5)
        );
        FeatureFlag flag = new FeatureFlag("id-1", "my-feature", true, 100.0, variants);

        String result = evaluator.evaluate(user, flag);
        assertNotNull(result, "User should be in 100% rollout");
        assertTrue(result.equals("control") || result.equals("treatment"),
                "Result should be one of the defined variants, got: " + result);
    }

    @Test
    @DisplayName("evaluate distributes users across variants proportionally")
    void testVariantDistributionIsProportional() {
        List<FeatureFlag.Variant> variants = Arrays.asList(
                new FeatureFlag.Variant("control", 0.5),
                new FeatureFlag.Variant("treatment", 0.5)
        );
        FeatureFlag flag = new FeatureFlag("id-1", "distribution-test", true, 100.0, variants);

        int controlCount = 0;
        int treatmentCount = 0;
        int total = 2000;

        for (int i = 0; i < total; i++) {
            User user = User.builder("user-" + i).build();
            String result = evaluator.evaluate(user, flag);
            if ("control".equals(result)) controlCount++;
            else if ("treatment".equals(result)) treatmentCount++;
        }

        // Expect roughly 50/50 split ± 5%
        double controlPct = (double) controlCount / total;
        assertTrue(controlPct >= 0.45 && controlPct <= 0.55,
                "Expected ~50% control, got " + (controlPct * 100) + "%");
    }

    @Test
    @DisplayName("evaluate returns 'on' for boolean flag (no variants defined)")
    void testEvaluateReturnsSingleOnForBooleanFlag() {
        // user1 hash for "flag1" is ~0.228, which is < 0.5 (50% rollout)
        User user = User.builder("user1").build();
        FeatureFlag flag = new FeatureFlag("id-1", "flag1", true, 50.0, null);

        String result = evaluator.evaluate(user, flag);
        assertEquals("on", result,
                "Boolean flag should return 'on' for user in rollout");
    }

    @Test
    @DisplayName("evaluate returns null for user outside rollout band")
    void testEvaluateReturnsNullForUserOutsideRollout() {
        // alice has hash ~0.9276 for "checkout-v2", which is >= 0.5 (50% rollout)
        User alice = User.builder("alice").build();
        FeatureFlag flag = new FeatureFlag("id-1", "checkout-v2", true, 50.0, null);

        assertNull(evaluator.evaluate(alice, flag),
                "alice (hash ~0.9276) should not be in 50% rollout");
    }

    @Test
    @DisplayName("evaluate with empty variants list returns 'on' (treated as boolean)")
    void testEvaluateWithEmptyVariantsListReturnsSingleOn() {
        User user = User.builder("user1").build();
        FeatureFlag flag = new FeatureFlag("id-1", "flag1", true, 100.0,
                Collections.emptyList());

        assertEquals("on", evaluator.evaluate(user, flag),
                "Empty variants list should be treated as boolean flag returning 'on'");
    }

    @Test
    @DisplayName("evaluate assigns user to one valid variant from multi-variant flag across many users")
    void testEvaluateAlwaysReturnsKnownVariantName() {
        List<FeatureFlag.Variant> variants = Arrays.asList(
                new FeatureFlag.Variant("red", 0.33),
                new FeatureFlag.Variant("green", 0.33),
                new FeatureFlag.Variant("blue", 0.34)
        );
        FeatureFlag flag = new FeatureFlag("id-1", "color-test", true, 100.0, variants);
        Set<String> validVariants = new HashSet<>(Arrays.asList("red", "green", "blue"));

        for (int i = 0; i < 500; i++) {
            User user = User.builder("user-" + i).build();
            String result = evaluator.evaluate(user, flag);
            assertNotNull(result, "Result should not be null for 100% rollout");
            assertTrue(validVariants.contains(result),
                    "Result '" + result + "' should be one of: " + validVariants);
        }
    }
}
